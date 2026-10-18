"""Pipeline: model extraction -> symbolic solve -> verdict (stdlib only)."""
import json
import re

from solver_core import (
    parse_header, split_body_lines, solve_all, is_sat, minimise_mus,
    squash_stmt, cite_ok_for_body,
)

VALID_T = {"on", "not_on", "before", "adj", "between", "station",
           "station_not", "st_before_p", "p_before_st", "st_before_st"}

FACT_DOC = """\
Facts (ONLY these shapes):
{"t":"on","p":P,"b":B} {"t":"not_on","p":P,"b":B}
{"t":"before","a":A,"b":B} {"t":"adj","a":A,"b":B}
{"t":"between","x":X,"y":Y,"z":Z}
{"t":"station","s":S,"p":P} {"t":"station_not","s":S,"p":P}
{"t":"st_before_p","s":S,"p":P} {"t":"p_before_st","p":P,"s":S}
{"t":"st_before_st","s1":A,"s2":B}
"""
FILLER = """\
No facts for: site trivia; history (spring/last month/previous cycle/old
arrangement); counterfactuals (would have/had the rota); failed requests
(lobbied/declined/turned down/did not get/wanted); open questions (nobody
could remember/nothing minuted/left open/disagreement). Hedged assertions
ARE active constraints.
"""


def build_extract_prompt(header, body):
    lines = "\n".join("[%d] %s" % (i, ln) for i, ln in body)
    return (
        "Translate shift-note lines to facts.\nRoster: "
        + ", ".join(header["names"]) + ". Blocks: "
        + ", ".join(header["blocks"]) + ". Stations: "
        + ", ".join(header["stations"]) + ". Holders: "
        + ", ".join(header["holders"]) + ".\n" + FACT_DOC + FILLER
        + "Reply JSON only: [{idx,facts:[...]}] for EVERY line; "
        "filler lines get facts:[].\n" + lines)


def build_repair_prompt(header, wanted):
    lines = "\n".join("[%d] %s" % (i, ln) for i, ln in wanted)
    return (
        "Translate ONLY these shift-note lines to facts.\nRoster: "
        + ", ".join(header["names"]) + ". Blocks: "
        + ", ".join(header["blocks"]) + ". Stations: "
        + ", ".join(header["stations"]) + ".\n" + FACT_DOC + FILLER
        + "Reply JSON only: [{idx,facts:[...]}].\n" + lines)


def build_diagnose_prompt(header, wanted_with_ctx):
    """Stage2 Call2: reconsider suspect lines with current read shown."""
    parts = []
    for i, ln, cur in wanted_with_ctx:
        parts.append("[%d] %s\n  current_read=%s" % (i, ln, cur))
    lines = "\n".join(parts)
    return (
        "Reconsider ONLY these shift-note lines. Original text governs.\n"
        "Roster: " + ", ".join(header["names"]) + ". Blocks: "
        + ", ".join(header["blocks"]) + ". Stations: "
        + ", ".join(header["stations"]) + ". Holders: "
        + ", ".join(header["holders"]) + ".\n" + FACT_DOC + FILLER
        + "Rules: hedged assertions ARE active constraints; history "
        + "(spring/last month/previous cycle/old arrangement), "
        + "counterfactuals (would have/had the rota), failed requests, "
        + "open questions ARE filler (facts:[]). "
        + "Immediately/directly/straight over/back-to-back means adj, "
        + "not before.\n"
        + "Reply JSON only: [{idx,facts:[...]}] one entry per line.\n"
        + lines)


def build_verify_prompt(header, idx, verbatim):
    """Stage3 Call3: single decisive temporal/meaning check."""
    return (
        "Decisive check on ONE shift-note line. Roster: "
        + ", ".join(header["names"]) + ". Blocks: "
        + ", ".join(header["blocks"]) + ". Stations: "
        + ", ".join(header["stations"]) + ".\n" + FACT_DOC + FILLER
        + "Q: does this assert a CURRENT block/station fact, or is it "
        + "history / hypothetical / unresolved / failed-request / trivia? "
        + "If current, give its facts; else facts:[].\n"
        + "Reply JSON only: [{idx,facts:[...]}].\n"
        + "[%d] %s" % (idx, verbatim))


def build_temporal_prompt(header, body):
    """10x Call2: independent re-extract, temporal/history emphasis."""
    lines = "\n".join("[%d] %s" % (i, ln) for i, ln in body)
    return (
        "Translate shift-note lines to facts. Focus on TEMPORAL meaning.\n"
        "Roster: " + ", ".join(header["names"]) + ". Blocks: "
        + ", ".join(header["blocks"]) + ". Stations: "
        + ", ".join(header["stations"]) + ". Holders: "
        + ", ".join(header["holders"]) + ".\n" + FACT_DOC + FILLER
        + "Decide per line: CURRENT constraint vs history "
        + "(spring/last month/previous cycle/old arrangement), "
        + "counterfactual (would have/had the rota), failed request, "
        + "open question, trivia. Only CURRENT lines get facts.\n"
        + "Reply JSON only: [{idx,facts:[...]}] for EVERY line.\n" + lines)


def build_negseq_prompt(header, body):
    """10x Call3: independent re-extract, negation/sequence emphasis."""
    lines = "\n".join("[%d] %s" % (i, ln) for i, ln in body)
    return (
        "Translate shift-note lines to facts. Focus on NEGATION and ORDER.\n"
        "Roster: " + ", ".join(header["names"]) + ". Blocks: "
        + ", ".join(header["blocks"]) + ". Stations: "
        + ", ".join(header["stations"]) + ". Holders: "
        + ", ".join(header["holders"]) + ".\n" + FACT_DOC + FILLER
        + "Careful: not/other-than/never/unavailable/rules-out means "
        + "negation (not_on/station_not). Immediately/directly/straight "
        + "over/back-to-back means adj, plain earlier/later/before/after "
        + "means before, between-Y-and-Z means between.\n"
        + "Reply JSON only: [{idx,facts:[...]}] for EVERY line.\n" + lines)


KEEP = ("t", "p", "b", "a", "x", "y", "z", "s", "s1", "s2")


def _fact_ok(f, header):
    if not isinstance(f, dict) or f.get("t") not in VALID_T:
        return False
    N = set(header["names"])
    B = set(header["blocks"])
    S = set(header["stations"])
    t = f["t"]
    if t in ("on", "not_on"):
        return f.get("p") in N and f.get("b") in B
    if t in ("before", "adj"):
        return f.get("a") in N and f.get("b") in N
    if t == "between":
        return f.get("x") in N and f.get("y") in N and f.get("z") in N
    if t in ("station", "station_not"):
        return f.get("s") in S and f.get("p") in N
    if t in ("st_before_p", "p_before_st"):
        return f.get("s") in S and f.get("p") in N
    return f.get("s1") in S and f.get("s2") in S


def parse_extraction(text, header, n):
    """(facts_by_src, failed, n_bad). Fix 2: failed tracked, never filled."""
    by_src = {i: [] for i in range(n)}
    try:
        m = re.search(r"\[.*\]", text.strip(), re.S)
        items = json.loads(m.group(0) if m else text.strip())
    except Exception:
        return by_src, list(range(n)), 0
    if not isinstance(items, list):
        return by_src, list(range(n)), 0
    seen, bad = set(), 0
    for e in items:
        if not isinstance(e, dict) or not isinstance(e.get("idx"), int):
            continue
        i = e["idx"]
        if not (0 <= i < n):
            continue
        seen.add(i)
        fs = e.get("facts", [])
        if not isinstance(fs, list):
            continue
        good = []
        for f in fs:
            if _fact_ok(f, header):
                good.append({k: f[k] for k in KEEP if k in f})
            else:
                bad += 1
        by_src[i] = good
    return by_src, [i for i in range(n) if i not in seen], bad






