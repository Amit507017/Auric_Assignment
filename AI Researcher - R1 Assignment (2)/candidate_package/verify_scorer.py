"""Verify the scorer's actual behaviour (Fix 5) before trusting ablations.

Asserts, against the shipped score.py:
 1. multiple conflict_line_sets are OR-ed (any single MUS scores 1.0);
 2. citing every line fails (minimality enforced via length equality);
 3. one-short citations fail; 4. duplicate citations fail;
 5. bare-assignment form reads as unique; 6. our mirror cites() agrees.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score as SC
from solver_core import cites as M_CITES
from solver_core import squash as M_SQ, squash_stmt as M_SS

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY = json.load(open(os.path.join(ROOT, "visible_key.json"),
                     encoding="utf-8"))
ITEMS = json.load(open(os.path.join(ROOT, "items.json"), encoding="utf-8"))
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# 1. multi-set OR: each recorded MUS alone must score
iid = next(i for i, k in KEY.items() if len(k.get("conflict_line_sets",
                                                  [])) > 1)
cores = KEY[iid]["conflict_line_sets"]
texts = {t["id"]: t["text"] for t in ITEMS}
ok_each = True
for c in cores:
    sub = {iid: {"case": "inconsistent", "conflicts": list(c)}}
    r = SC.score({iid: KEY[iid]}, sub, [t for t in ITEMS
                                        if t["id"] == iid])
    if r["per_item"].get(iid) != 1.0:
        ok_each = False
check("multi-set OR (%s, %d sets)" % (iid, len(cores)), ok_each)

# 2. cite-everything fails minimality
item = next(t for t in ITEMS if t["id"] == iid)
body = [ln.strip() for ln in item["text"].split("\n")[1:] if ln.strip()]
sub = {iid: {"case": "inconsistent", "conflicts": body}}
r = SC.score({iid: KEY[iid]}, sub, [item])
check("cite-all-lines fails", r["per_item"].get(iid) == 0.0)

# 3. one-short fails
c0 = list(cores[0])
sub = {iid: {"case": "inconsistent", "conflicts": c0[:-1]}}
r = SC.score({iid: KEY[iid]}, sub, [item])
check("one-short fails", r["per_item"].get(iid) == 0.0)

# 4. duplicated citation fails
if len(c0) > 1:
    sub = {iid: {"case": "inconsistent",
                 "conflicts": c0[:-1] + [c0[0]]}}
    r = SC.score({iid: KEY[iid]}, sub, [item])
    check("duplicated citation fails", r["per_item"].get(iid) == 0.0)

# 5. bare assignment reads as unique
uk = next(i for i, k in KEY.items() if k["case"] == "unique")
bare = dict(KEY[uk]["assignments"][0])
sub = {uk: bare}
case, _ = SC.read_sub(sub[uk])
check("bare form reads unique", case == "unique")

# 6. mirror agrees with scorer normalisation on key lines
agree = True
for k in KEY.values():
    for cs in k.get("conflict_line_sets", [])[:1]:
        for ln in cs:
            if M_SS(ln) != SC.squash_stmt(ln) or M_SQ(ln) != SC.squash(ln):
                agree = False
check("mirror squash matches scorer", agree)
c, w = "As far as I know, Tomas is on the 13:00 block.", \
    "Tomas is on the 13:00 block."
check("mirror cites hedge-drop",
      M_CITES(M_SS(c), M_SS(w)) == SC.cites(SC.squash_stmt(c),
                                           SC.squash_stmt(w)))

print("FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)

