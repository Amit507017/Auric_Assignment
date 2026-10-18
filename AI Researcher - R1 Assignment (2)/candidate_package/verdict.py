"""Verdict: solve -> case -> answer (Fix 3 zero-solution discipline)."""
from solver_core import solve_all, minimise_mus, cite_ok_for_body


def decide(header, facts_by_src, body_lines, failed, repair_fn=None,
           max_repairs=1, stage_start=2):
    """Return (answer, diag).

    Verdict routing:
      n_solutions == 1 -> unique.
      n_solutions in 2..4 -> ambiguous (all solutions).
      n_solutions > 4 -> under-constrained; repair_fn (3x/10x) asks the
        model to extract more facts. The model must derive the missing
        constraint from the notes - never from the key.
      n_solutions == 0 -> inconsistent, but the solver only declares that
        after statement-level MUS verification. At 3x/10x repair_fn may
        re-ask the extraction (failed lines) or re-verify MUS members;
        a surviving MUS keeps the inconsistent verdict.

    max_repairs bounds sequential repair_fn calls (3x -> 2: diagnose +
    verify; 10x -> 7: stages 4..10). stage_start sets the first repair
    stage (2 for 3x, 4 for 10x since calls 2-3 are ensemble votes).
    A solver signal is never proof of model error: genuine
    inconsistent / ambiguous items keep their verdict if repair yields
    no justified correction.
    """
    diag = {"failed": list(failed)}
    sols = solve_all(header, facts_by_src)
    diag["n_solutions"] = len(sols)

    def _sorted(sols):
        return sorted(sols, key=json_key)

    def _repair_loop(facts_by_src, failed, sols, mus, stage_start=2):
        """Run up to max_repairs staged repairs; return updated state."""
        import json as _jj
        stage = stage_start
        used = 0
        while (repair_fn is not None and used < max_repairs
               and stage < stage_start + max_repairs):
            snap = (_jj.dumps(facts_by_src, sort_keys=True),
                    list(failed))
            try:
                repaired = repair_fn(facts_by_src, failed, sols,
                                     mus_srcs=mus, stage=stage)
            except Exception:
                break
            if repaired is None:
                break
            facts_by_src, failed = repaired
            sols = solve_all(header, facts_by_src)
            diag["n_solutions_after_stage%d" % stage] = len(sols)
            diag["failed_after_stage%d" % stage] = list(failed)
            used += 1
            stage += 1
            if 1 <= len(sols) <= 4:
                break
            if len(sols) == 0:
                mus = minimise_mus(header, facts_by_src)
                diag["mus_after_stage%d" % (stage - 1)] = list(mus)
            # No-progress early stop: repair changed nothing -> save budget.
            if (_jj.dumps(facts_by_src, sort_keys=True),
                    list(failed)) == snap:
                diag["stopped_no_progress_at_stage%d" % (stage - 1)] = True
                break
        return facts_by_src, failed, sols, mus

    if 1 <= len(sols) <= 4:
        if len(sols) == 1:
            return ({"case": "unique", "assignment": sols[0]}, diag)
        return ({"case": "ambiguous",
                 "assignments": sorted(sols, key=json_key)}, diag)

    if len(sols) > 4:
        if repair_fn is not None:
            facts_by_src, failed, sols, _ = _repair_loop(
                facts_by_src, failed, sols, None, stage_start=stage_start)
            diag["n_solutions_after_repair"] = len(sols)
            diag["failed_after"] = list(failed)
            if 1 <= len(sols) <= 4:
                if len(sols) == 1:
                    return ({"case": "unique",
                             "assignment": sols[0]}, diag)
                return ({"case": "ambiguous",
                         "assignments": _sorted(sols)}, diag)
        return ({"case": "ambiguous",
                 "assignments": sorted(sols[:4], key=json_key)}, diag)

    # len == 0: inconsistent OR over-constrained extraction (Fix 3).
    mus = minimise_mus(header, facts_by_src)
    diag["mus"] = list(mus)
    if repair_fn is not None and mus:
        facts_by_src, failed, sols, mus = _repair_loop(
            facts_by_src, failed, sols, mus, stage_start=stage_start)
        diag["n_solutions_after_repair"] = len(sols)
        diag["failed_after"] = list(failed)
        if 1 <= len(sols) <= 4:
            if len(sols) == 1:
                return ({"case": "unique",
                         "assignment": sols[0]}, diag)
            return ({"case": "ambiguous",
                     "assignments": _sorted(sols)}, diag)
        diag["mus_after"] = list(mus)
    if not mus:
        diag["mus_empty"] = True
        return ({"case": "inconsistent", "conflicts": []}, diag)
    verb = dict(body_lines)
    cites_out = [verb[s] for s in mus]
    bl = [ln for _, ln in body_lines]
    cites_out = [c for c in cites_out if cite_ok_for_body(c, bl)]
    return ({"case": "inconsistent", "conflicts": cites_out}, diag)


def json_key(a):
    import json as _j
    return _j.dumps(a, sort_keys=True)
