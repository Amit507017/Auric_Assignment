"""Runner: one item end-to-end (budget-aware, X-Item-Id on every call)."""
import json

from client import BudgetExceeded, TransientError
from diagnose import (
    diagnose_stage2, diagnose_stage3, extraction_disagreements,
    vote_facts,
)
from solver_core import parse_header, split_body_lines
from pipeline import (
    build_extract_prompt, build_repair_prompt, build_diagnose_prompt,
    build_verify_prompt, build_temporal_prompt, build_negseq_prompt,
    parse_extraction,
)
from verdict import decide


def _vote_merge(header, body, runs):
    """Majority-vote merge of independent runs; agree lines fixed.

    Returns (merged_by_src, disagreed_idxs). Lines with strict majority
    (>n/2 incl. filler []) are fixed; the rest go to targeted re-ask.
    """
    n = len(body)
    merged = {}
    disagreed = []
    for i, _ in body:
        v, _, nv = vote_facts(runs, i)
        if v is not None:
            merged[i] = v
        else:
            merged[i] = list((runs[0].get(i)) or []) if runs else []
            disagreed.append(i)
    return merged, disagreed


def run_item(item, client, budget_cap, offline_symbolic=False, item_id=None):
    iid = item_id or item["id"]
    header = parse_header(item["text"])
    body = split_body_lines(item["text"])
    n = len(body)
    diag = {"id": iid, "budget": budget_cap}

    if offline_symbolic:
        by_src, failed = {}, []
        for i, ln in body:
            fs, is_fill = offline_interpret(ln, header)
            if fs is None:
                by_src[i] = []
                failed.append(i)
            else:
                by_src[i] = fs
        ans, d2 = decide(header, by_src, body, failed, repair_fn=None)
        diag.update(d2)
        diag["mode"] = "offline_symbolic"
        diag["calls"] = 0
        return ans, diag

    # 1x: exactly one model call, no regex constraint check.
    prompt = build_extract_prompt(header, body)
    t = client.chat(iid, [{"role": "user", "content": prompt}])
    by_src, failed, _ = parse_extraction(t, header, n)
    diag["failed_initial"] = list(failed)

    # 10x Calls 2-3: two more INDEPENDENT full extractions (fresh prompts,
    # no history shown) with temporal / negation-sequence emphasis.
    # Majority vote fixes agreed lines; disagreements go to Calls 4-6.
    runs = [dict(by_src)]
    diag["calls_after_1"] = client.counter.used.get(iid, 0)
    if budget_cap >= 10:
        try:
            t2 = client.chat(
                iid, [{"role": "user",
                       "content": build_temporal_prompt(header, body)}])
            b2, _, _ = parse_extraction(t2, header, n)
            runs.append(b2)
            diag["calls_after_2"] = client.counter.used.get(iid, 0)
            t3 = client.chat(
                iid, [{"role": "user",
                       "content": build_negseq_prompt(header, body)}])
            b3, _, _ = parse_extraction(t3, header, n)
            runs.append(b3)
            diag["calls_after_3"] = client.counter.used.get(iid, 0)
            merged, disagreed = _vote_merge(header, body, runs)
            diag["disagreed_after_vote"] = list(disagreed)
            failed = [i for i in disagreed]
            by_src = merged
            diag["failed_after_vote"] = list(failed)
        except BudgetExceeded:
            raise
        except (TransientError, RuntimeError):
            pass  # fall through with Call-1 state; repairs use leftovers

    def _patch(fbs, fail, cands, t2):
        b2, f2, _ = parse_extraction(t2, header, n)
        for c in cands:
            if c not in f2:
                fbs[c] = b2[c]
                if c in fail:
                    fail.remove(c)
        return (fbs, fail)

    def _chat(prompt):
        return client.chat(iid, [{"role": "user", "content": prompt}])

    def repair_fn(fbs, fail, sols, mus_srcs=None, stage=2):
        # Staged reinference. 3x: stage2 diagnose, stage3 verify.
        # 10x: stages 4-6 disagreements, stages 7-10 solver-guided.
        # Each stage = exactly 1 model call; BudgetExceeded stops.
        verb = dict(body)
        try:
            if stage <= 2 or (cap < 10 and stage <= 3):
                cands = diagnose_stage2(
                    header, body, fbs, fail, sols, mus_srcs)
                if cands:
                    diag["suspects_stage%d" % stage] = list(cands)
                    ctx = [(c, verb[c], json.dumps(fbs.get(c, [])))
                           for c in cands]
                    t2 = _chat(build_diagnose_prompt(header, ctx))
                    return _patch(fbs, fail, cands, t2)
                # fall back to legacy failed+MUS re-ask (same 1 call)
                cands = list(dict.fromkeys(
                    list(fail) + list(mus_srcs or [])))
                cands = [c for c in cands if 0 <= c < n]
                if not cands:
                    return None
                diag["suspects_stage%d" % stage] = list(cands)
                t2 = _chat(build_repair_prompt(
                    header, [(c, verb[c]) for c in cands]))
                return _patch(fbs, fail, cands, t2)
            if stage == 3 and cap < 10:
                # 3x stage 3: single decisive verify
                cands = diagnose_stage3(
                    header, body, fbs, fail, sols, mus_srcs)
                if not cands:
                    return None
                diag["suspects_stage3"] = list(cands)
                c = cands[0]
                t3 = _chat(build_verify_prompt(header, c, verb[c]))
                return _patch(fbs, fail, [c], t3)
            # 10x stages 4-10: solver-guided.
            # 4-6: disagreements first, then diagnose suspects.
            # 7-10: diagnose_stage3 single-line verify (contradiction /
            # missed-constraint / high-impact unresolved).
            if 4 <= stage <= 6:
                dis = extraction_disagreements(runs + [dict(fbs)])
                dis = [c for c in dis if 0 <= c < n][:8]
                if not dis:
                    dis = diagnose_stage2(
                        header, body, fbs, fail, sols, mus_srcs)[:8]
                if not dis:
                    return None
                diag["suspects_stage%d" % stage] = list(dis)
                ctx = [(c, verb[c], json.dumps(fbs.get(c, [])))
                       for c in dis]
                tx = _chat(build_diagnose_prompt(header, ctx))
                return _patch(fbs, fail, dis, tx)
            # stages 7-10
            cands = diagnose_stage3(header, body, fbs, fail, sols, mus_srcs)
            if not cands:
                return None
            diag["suspects_stage%d" % stage] = list(cands)
            c = cands[0]
            tx = _chat(build_verify_prompt(header, c, verb[c]))
            return _patch(fbs, fail, [c], tx)
        except BudgetExceeded:
            raise
        except (TransientError, RuntimeError):
            return None

    cap = budget_cap
    use_repair = cap > 1
    if cap >= 10:
        max_rep = 7  # calls 4..10
        stage0 = 4
    elif cap >= 3:
        max_rep = 2  # calls 2..3
        stage0 = 2
    else:
        max_rep = 1
        stage0 = 2
    ans, d2 = decide(header, by_src, body, failed,
                     repair_fn=repair_fn if use_repair else None,
                     max_repairs=max_rep if use_repair else 1,
                     stage_start=stage0)
    diag.update(d2)
    diag["calls"] = client.counter.used.get(iid, 0)
    return ans, diag
