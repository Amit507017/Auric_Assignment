"""Solver core: header parse + scorer mirror + facts + SAT + MUS (stdlib).

Fix 1: body lines stored VERBATIM; hedges stripped in-memory only.
Fix 4: MUS minimisation at STATEMENT level.
Fix 5: scorer mirror (squash/squash_stmt/cites) validates citations.
"""
import itertools
import re

BLOCK_RE = re.compile(r"(\d{2}:\d{2})")
ROTA_RE = re.compile(r"on the rota:\s*(.+?)\.\s*Blocks run", re.S)
ST_RE = re.compile(r"one person on each:\s*(.+?)\.", re.S)
HOLD_RE = re.compile(
    r"The people on a station (?:are|is)\s*(.+?);\s*the rest", re.S)


def parse_header(text):
    m = ROTA_RE.search(text)
    names = [n.strip() for n in m.group(1).split(",")] if m else []
    bs, seen, ordered = BLOCK_RE.findall(text.split("\n")[0]), set(), []
    for b in bs:
        if b not in seen:
            seen.add(b)
            ordered.append(b)
    m2 = ST_RE.search(text)
    sts = [s.strip() for s in m2.group(1).split(",")] if m2 else []
    m3 = HOLD_RE.search(text)
    hs = [h.strip() for h in m3.group(1).split(",")] if m3 else []
    return {"names": names, "blocks": ordered, "stations": sts,
            "holders": hs}


def split_body_lines(text):
    out = []
    for line in text.split("\n")[1:]:
        if line.strip():
            out.append((len(out), line.strip()))
    return out


HEDGES = (
    "i'm fairly sure ", "from what i recall, ", "as far as i know, ",
    "i believe ", "going off the roster, ", "if memory serves, ",
    "my recollection is that ", "unless i have this wrong, ",
    "speaking from memory, ", "i'm reasonably confident ",
)
MAX_ENV, MIN_FRAG = 3.0, 0.6


def squash(s):
    return " ".join(str(s).split()).casefold()


def squash_stmt(s):
    s = squash(s)
    head, sep, tail = s.partition(": ")
    if sep and tail and len(head) < 60:
        s = tail
    for h in HEDGES:
        if s.startswith(h):
            return s[len(h):]
    return s


def cites(got, want, text=None):
    if not got or not want:
        return False
    if len(got) < MIN_FRAG * len(want):
        return False
    if text is not None and got not in text:
        return False
    return want in got and len(got) <= MAX_ENV * len(want)


def cite_ok_for_body(citation, body_lines):
    c = squash_stmt(citation)
    hits = set()
    for ln in body_lines:
        nl = squash_stmt(ln)
        if nl and nl in c:
            hits.add(nl)
    return len(hits) <= 1
# __PART2__


def check_fact(f, block_of, station_of, order):
    t = f["t"]
    if t == "on":
        return block_of.get(f["p"]) == f["b"]
    if t == "not_on":
        return block_of.get(f["p"]) != f["b"]
    if t == "before":
        return order[block_of[f["a"]]] < order[block_of[f["b"]]]
    if t == "adj":
        return order[block_of[f["b"]]] == order[block_of[f["a"]]] + 1
    if t == "between":
        ix, iy = order[block_of[f["x"]]], order[block_of[f["y"]]]
        iz = order[block_of[f["z"]]]
        return (iy < ix < iz) or (iz < ix < iy)
    if t == "station":
        return station_of.get(f["p"]) == f["s"]
    if t == "station_not":
        return station_of.get(f["p"]) != f["s"]
    if t == "st_before_p":
        return order[block_of[f["holder_of_s"]]] < order[block_of[f["p"]]]
    if t == "p_before_st":
        return order[block_of[f["p"]]] < order[block_of[f["holder_of_s"]]]
    if t == "st_before_st":
        return order[block_of[f["holder_of_s1"]]] < order[
            block_of[f["holder_of_s2"]]]
    raise ValueError("bad fact %r" % (t,))


def _resolve(f, holder_of):
    ff = dict(f)
    t = ff["t"]
    if t in ("st_before_p", "p_before_st"):
        hp = next((p for p, s in holder_of.items() if s == ff["s"]), None)
        if hp is None:
            return None
        ff["holder_of_s"] = hp
    elif t == "st_before_st":
        h1 = next((p for p, s in holder_of.items() if s == ff["s1"]), None)
        h2 = next((p for p, s in holder_of.items() if s == ff["s2"]), None)
        if h1 is None or h2 is None:
            return None
        ff["holder_of_s1"], ff["holder_of_s2"] = h1, h2
    return ff


def _cands(header):
    names, blocks = header["names"], header["blocks"]
    sts, hs = header["stations"], header["holders"]
    order = {b: i for i, b in enumerate(blocks)}
    for bp in itertools.permutations(blocks):
        bo = dict(zip(names, bp))
        for sp in itertools.permutations(sts):
            ho = dict(zip(hs, sp))
            so = {p: None for p in names}
            for p, s in ho.items():
                so[p] = s
            yield bo, so, ho, order


def _holds(facts, bo, so, ho, order):
    for f in facts:
        ff = _resolve(f, ho)
        if ff is None:
            return False
        if not check_fact(ff, bo, so, order):
            return False
    return True


def _facts_of(facts_by_src, active):
    if active is None:
        return [f for fs in facts_by_src.values() for f in fs]
    return [f for s, fs in facts_by_src.items() if s in active for f in fs]


def solve_all(header, facts_by_src, active=None, cap=6):
    facts = _facts_of(facts_by_src, active)
    names, hs = header["names"], header["holders"]
    out = []
    for bo, so, ho, order in _cands(header):
        if _holds(facts, bo, so, ho, order):
            e = {}
            for p in names:
                d = {"block": bo[p]}
                if p in hs:
                    d["station"] = so[p]
                e[p] = d
            out.append(e)
            if len(out) >= cap:
                break
    return out


def is_sat(header, facts_by_src, active):
    facts = _facts_of(facts_by_src, active)
    for bo, so, ho, order in _cands(header):
        if _holds(facts, bo, so, ho, order):
            return True
    return False


def minimise_mus(header, facts_by_src):
    """Deletion MUS at STATEMENT level (Fix 4)."""
    const = sorted(s for s, fs in facts_by_src.items() if fs)
    if is_sat(header, facts_by_src, set(const)):
        return []
    mus = list(const)
    for s in const:
        trial = [x for x in mus if x != s]
        if not is_sat(header, facts_by_src, set(trial)):
            mus = trial
    return sorted(mus)


