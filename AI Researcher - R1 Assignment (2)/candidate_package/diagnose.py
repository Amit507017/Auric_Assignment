"""Diagnose: deterministic suspects for 3x reinference (no model calls).

Stage2 (Call2) suspects: failed lines + MUS members + missed relational
constraints + holder anomalies + lost precision + duplicate disagreements.
Stage3 (Call3): single highest-impact verify target (temporal/counterfactual).
"""
import re

from solver_core import squash_stmt

REL_PAT = re.compile(
    r"(before|earlier|after|later|precedes|between|adjacent|immediately|"
    r"directly|straight over|relieves|takes over|back to back|no block between)",
    re.I)
ADJ_WORD = re.compile(
    r"(immediately|directly|straight over|back to back)", re.I)
HIST_PAT = re.compile(
    r"(in the spring|last month|previous cycle|old arrangement|old emergency)",
    re.I)
CTR_PAT = re.compile(
    r"(would have|had the rota gone|would be on|had .* taken)", re.I)
OPEN_PAT = re.compile(
    r"(nobody could remember|nothing was minuted|left open|"
    r"disagreement about whether|came up, but nothing)", re.I)

FILLER_OBVIOUS = re.compile(
    r"(deliveries|car park|jacket|catering|recycling|maintenance ticket|"
    r"equipment survey|walkaround|interview panel|supplier training|"
    r"fire-safety|fire drill|sign-in sheet|emergency contact|visitor log|"
    r"spare key|car-share|supply cupboard)", re.I)


def _holder_anomaly_srcs(header, by_src):
    """Holders with 2+ station_not and no positive -> source lines."""
    out = []
    holders = header.get("holders", [])
    for p in holders:
        forbidding, positive = [], False
        srcs = []
        for s, fs in by_src.items():
            for f in fs or []:
                if not isinstance(f, dict):
                    continue
                if f.get("p") == p and f.get("t") == "station_not":
                    forbidding.append(f.get("s"))
                    srcs.append(s)
                if f.get("p") == p and f.get("t") == "station":
                    positive = True
        if len(set(forbidding)) >= 2 and not positive:
            out.extend(srcs)
    return out


def _lost_precision_srcs(body, by_src):
    out = []
    verb = dict(body)
    for s, fs in by_src.items():
        ln = verb.get(s, "")
        if ADJ_WORD.search(ln):
            for f in fs or []:
                if isinstance(f, dict) and f.get("t") == "before":
                    out.append(s)
                    break
    return out


def _duplicate_disagree_srcs(body, by_src):
    from collections import defaultdict
    groups = defaultdict(list)
    for i, ln in body:
        groups[squash_stmt(ln)].append(i)
    out = []
    for _, idxs in groups.items():
        if len(idxs) > 1:
            sigs = set()
            for i in idxs:
                sigs.add(repr(sorted(
                    [repr(f) for f in (by_src.get(i) or [])])))
            if len(sigs) > 1:
                out.extend(idxs)
    return out


def _sig(facts):
    return repr(sorted([repr(f) for f in (facts or [])]))


def extraction_disagreements(runs):
    """Idxs where independent runs (list of by_src) disagree. Ranked."""
    if not runs:
        return []
    keys = set()
    for r in runs:
        keys.update(r.keys())
    out = []
    for k in sorted(keys):
        if len(set(_sig(r.get(k)) for r in runs)) > 1:
            out.append(k)
    return out


def vote_facts(runs, k):
    """Majority vote over independent runs for line k.

    Returns (facts, n_runs, n_votes). Filler [] counts as a vote.
    Majority = strict > n_runs/2; else ([], 0) meaning no consensus.
    """
    if not runs:
        return [], 0, 0
    sigs = [_sig(r.get(k)) for r in runs]
    best, bestn = None, 0
    for s in sigs:
        c = sigs.count(s)
        if c > bestn:
            best, bestn = s, c
    if bestn > len(runs) / 2:
        for r in runs:
            if _sig(r.get(k)) == best:
                return list(r.get(k) or []), len(runs), bestn
    return None, len(runs), bestn


def _temporal_verify_cands(body, by_src):
    """Lines where temporal class likely wrong."""
    out = []
    verb = dict(body)
    for s, fs in by_src.items():
        ln = verb.get(s, "")
        has_facts = bool(fs)
        is_hist = bool(HIST_PAT.search(ln) or CTR_PAT.search(ln)
                        or OPEN_PAT.search(ln))
        if is_hist and has_facts:
            out.append(s)  # should probably be filler
    # also: relational line with [] that is NOT obvious filler -> maybe missed
    for i, ln in body:
        if (by_src.get(i) == [] and REL_PAT.search(ln)
                and not FILLER_OBVIOUS.search(ln)
                and not HIST_PAT.search(ln)
                and not CTR_PAT.search(ln)
                and not OPEN_PAT.search(ln)):
            if i not in out:
                out.append(i)
    return out


def diagnose_stage2(header, body, by_src, failed, sols, mus_srcs=None):
    """Ranked suspect idx list for Call2 (combined re-ask)."""
    # Priority: MUS members first (decisive), then relational empties,
    # then holder/precision/duplicate signals, then remaining failed.
    ordered = []
    if mus_srcs:
        ordered.extend(list(mus_srcs))
    for i, ln in body:
        if by_src.get(i) == [] and REL_PAT.search(ln):
            ordered.append(i)
    ordered.extend(_holder_anomaly_srcs(header, by_src))
    ordered.extend(_lost_precision_srcs(body, by_src))
    ordered.extend(_duplicate_disagree_srcs(body, by_src))
    ordered.extend(list(failed or []))
    # dedupe, keep order, clip to valid range
    n = len(body)
    seen, out = set(), []
    for c in ordered:
        if isinstance(c, int) and 0 <= c < n and c not in seen:
            seen.add(c)
            out.append(c)
    # budget guard: single repair call should stay small; keep top 8
    return out[:8]


def diagnose_stage3(header, body, by_src, failed, sols, mus_srcs=None):
    """Single highest-impact idx for Call3 verify, or []."""
    # Zero-sols: MUS members are decisive; prefer temporal-in-MUS else MUS[0].
    if isinstance(sols, list) and len(sols) == 0 and mus_srcs:
        tset = set(_temporal_verify_cands(body, by_src))
        for s in mus_srcs:
            if s in tset:
                return [s]
        return [mus_srcs[0]]
    # Under-constrained: prefer missed relational / precision signals.
    verb = dict(body)
    t = _temporal_verify_cands(body, by_src)
    if t:
        return [t[0]]
    # priority 2: lost precision
    lp = _lost_precision_srcs(body, by_src)
    if lp:
        return [lp[0]]
    # priority 3: duplicate disagreement
    dd = _duplicate_disagree_srcs(body, by_src)
    if dd:
        return [dd[0]]
    # priority 4: first MUS member, else first failed
    if mus_srcs:
        return [mus_srcs[0]]
    if failed:
        return [failed[0]]
    return []
