"""CLI: ./run <items.json> --budget <1x|3x|10x> --out <answers.json>.

Documented entrypoint for the submission (see CANDIDATE_BRIEF.md). Reads an
items file, solves every item through runner.run_item() (model extraction +
symbolic solve), and writes the answers JSON mapping each item id to one of
the three scoring shapes: unique / ambiguous / inconsistent.

Budget contract (enforced at the proxy via the X-Item-Id header, and
re-checked here before exit):
  1x  -> exactly one model call per item (batched extraction, no repair).
  3x  -> at least one and at most three calls per item (1 + repairs).
  10x -> at least one and at most ten calls per item (1 + repairs/votes).
Every item needs >= 1 model call in model-backed modes. --offline-symbolic
skips the model entirely (0 calls) for solver debugging and as the "-model
extraction" ablation arm, so the minimum-one-call check is bypassed there.
"""
import argparse
import json
import os
import sys

# Make sibling modules (client, runner, pipeline, verdict, solver_core)
# importable when executed directly as `python run_pipeline.py` from any
# working directory: the repo root is the dir holding this file, not cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from client import BudgetCounter, ModelClient, load_env
from runner import run_item

# Budget flag -> per-item model-call cap. Echoed into each item's diag dict
# ("budget") and the run-level diag file so ablations can be re-checked
# against the cap after the fact.
CAPS = {"1x": 1, "3x": 3, "10x": 10}


def main():
    # Positional `items` keeps the documented invocation shape:
    #   ./run <items.json> --budget <1x|3x|10x> --out <answers.json>
    ap = argparse.ArgumentParser()
    ap.add_argument("items", help="path to items.json")
    ap.add_argument("--budget", required=True, choices=CAPS)
    ap.add_argument("--out", required=True)
    ap.add_argument("--offline-symbolic", action="store_true",
                    help="no model calls; symbolic extractor only")
    ap.add_argument("--diag", default=None,
                    help="optional diagnostics json path")
    # Resilience flags: --resume skips ids already present in --out (safe
    # re-entry after a crash); --flush-every controls how often partial
    # answers/diags hit disk so a later crash keeps early items.
    ap.add_argument("--resume", action="store_true",
                    help="skip item ids already present in --out")
    ap.add_argument("--flush-every", type=int, default=5,
                    help="write partial outputs every N items")
    a = ap.parse_args()
    # items.json is a list of {"id", "text", ...}. Ids are used verbatim as
    # keys of answers.json; the scorer matches on exact id strings, so they
    # are never normalised or reordered (output order follows input order).
    items = json.load(open(a.items, encoding="utf-8"))
    # Numeric per-item cap shared by BudgetCounter (raises on overrun) and
    # runner.run_item (gates repair): 1x disables repair, 3x/10x enable it.
    cap = CAPS[a.budget]
    # Credentials come from the repo-root .env (never committed): base URL +
    # API key for the OpenAI-compatible endpoint serving ONLY
    # ibm-granite/granite-4.2-8b. load_env() tolerates a missing .env so
    # --offline-symbolic runs work without credentials.
    root = os.path.dirname(os.path.abspath(__file__))
    env = load_env(root)
    # One counter for the whole run: tracks used[item_id] and refuses calls
    # past cap, so a repair loop can never silently violate the budget.
    counter = BudgetCounter(cap)
    # ModelClient sends X-Item-Id on EVERY call (the counting proxy
    # attributes calls from that header; without it the run fails the
    # budget check), with brief-mandated sampling temperature=1.0,
    # top_p=0.95, reasoning disabled. offline=True makes chat() raise
    # instead of dialling the network, so accidental model use in symbolic
    # mode fails loudly rather than producing a silent zero-call answer.
    client = ModelClient(
        env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        env.get("OPENROUTER_API_KEY", ""),
        counter, offline=a.offline_symbolic)
    # Each item is solved independently (no cross-item state: the held-out
    # set uses a different seed, so per-item isolation is what is graded).
    # run_item() returns (answer, diag); answers feed answers.json, diags
    # feed --diag (failed lines, MUS members, solution counts, call counts
    # -- raw material for the ablation table and failure analysis).
    answers, diags = {}, {}
    # --resume: preload already-solved ids from a previous partial --out so
    # a re-run after a crash (e.g. a mid-run TLS drop) only pays for the
    # remaining items. Preloaded ids keep saved answers AND satisfy the
    # >=1-call rule via saved diag call counts merged back into the counter.
    if a.resume:
        try:
            prior = json.load(open(a.out, encoding="utf-8"))
            if isinstance(prior, dict):
                answers.update(prior)
        except (OSError, ValueError):
            pass
        if a.diag:
            try:
                prior_dg = json.load(open(a.diag, encoding="utf-8"))
                for pid, pdg in (prior_dg.get("items") or {}).items():
                    if pid in answers:
                        diags[pid] = pdg
                for pid, n in (prior_dg.get("calls") or {}).items():
                    if pid in answers:
                        counter.used[pid] = max(counter.used.get(pid, 0),
                                               int(n))
            except (OSError, ValueError):
                pass

    def _flush():
        # Incremental writes: a crash late in the 60-item run keeps every
        # flushed item instead of discarding the whole batch.
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(answers, f, indent=2)
        if a.diag:
            with open(a.diag, "w", encoding="utf-8") as f:
                json.dump({"budget": a.budget, "calls": counter.used,
                           "items": diags}, f, indent=2)

    # Late import keeps module import light for --help / offline use.
    from client import BudgetExceeded, TransientError
    for pos, it in enumerate(items):
        if it["id"] in answers:
            continue  # resumed answer stands; no extra model call spent
        sys.stderr.write("solving %s\n" % it["id"])
        try:
            ans, dg = run_item(it, client, cap,
                               offline_symbolic=a.offline_symbolic)
        except BudgetExceeded:
            raise
        except TransientError as e:
            # One item's endpoint outage must not kill the run: record the
            # error in diags and continue; the id stays absent from answers
            # (scores 0 there) and --resume retries it next invocation.
            diags[it["id"]] = {"id": it["id"], "budget": cap,
                               "error": "transient: %s" % e}
            continue
        answers[it["id"]] = ans
        diags[it["id"]] = dg
        if (pos + 1) % max(a.flush_every, 1) == 0:
            _flush()
    # answers.json: {item_id: {case, assignment|assignments|conflicts}}.
    # Written even if some items failed, so partial runs still score the
    # items they answered (missing ids score 0 on those items only).
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(answers, f, indent=2)
    # Optional run-level diagnostics: budget flag, per-item call counts
    # (re-verifies the budget in both directions at grading time), plus the
    # per-item dicts. Kept separate from answers.json so the submission file
    # contains exactly what score.py expects and nothing else.
    if a.diag:
        with open(a.diag, "w", encoding="utf-8") as f:
            json.dump({"budget": a.budget, "calls": counter.used,
                       "items": diags}, f, indent=2)
    # min/max calls per item, to stderr (stdout stays clean for piping).
    # Both directions matter: over the cap OR an item answered with no model
    # call at all is an auto-fail, checked by the proxy and re-checked here.
    lo = min(counter.used.get(it["id"], 0) for it in items) if items else 0
    hi = max(counter.used.get(it["id"], 0) for it in items) if items else 0
    sys.stderr.write("calls/item: min=%d max=%d cap=%d\n" % (lo, hi, cap))
    # Lower-bound guard (model modes only): every item needs >= 1 model call
    # -- the task is to make the weak model do the work, and the grader
    # checks answers change when model output changes. Exit 2 (not 1) so
    # budget violations are distinguishable from solve errors.
    if not a.offline_symbolic and lo < 1:
        sys.stderr.write("ERROR: some item got zero model calls\n")
        return 2
    # Upper-bound guard: no item may exceed the flag's cap (1/3/10). The
    # BudgetCounter should already have raised mid-run; this is the
    # defence-in-depth re-check before the grader's proxy does its own.
    if hi > cap:
        sys.stderr.write("ERROR: budget exceeded\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
