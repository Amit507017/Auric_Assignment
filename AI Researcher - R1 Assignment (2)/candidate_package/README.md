# Shift-Notes Scheduler — Hybrid Neuro-Symbolic Pipeline

Classifies each facility shift-note page as **unique**, **ambiguous**, or
**inconsistent** and returns the corresponding assignments or conflict
citations, using the fixed weak model `ibm-granite/granite-4.2-8b`.

Full design, results (1x/3x/10x), error analysis, and roadmap are in
**[`methodology_report.docx`](methodology_report.docx)**.

## Requirements

- Python **3.9+**
- No third-party packages (stdlib only — see `requirements.txt`)

## Configuration

```powershell
copy .env.example .env    # then fill in your key
```

`.env` must define `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, and `MODEL`.
It is intentionally not committed. Runs with `--offline-symbolic` work
without it.

## Run

```powershell
# Linux/macOS
./run <items.json> --budget <1x|3x|10x> --out <answers.json>

# Windows
python run <items.json> --budget <1x|3x|10x> --out <answers.json>
```

Optional flags:

| Flag | Purpose |
|---|---|
| `--diag <path>` | write per-item diagnostics JSON |
| `--offline-symbolic` | no model calls (symbolic extractor only, no key needed) |
| `--resume` | skip item ids already present in `--out` (crash recovery) |
| `--flush-every N` | write partial output every N items (default 5) |

Budgets cap model calls per item: `1x` = exactly 1, `3x` = 1–3, `10x` = 1–10.

## Score

```powershell
python score.py visible_key.json <answers>.json
```
