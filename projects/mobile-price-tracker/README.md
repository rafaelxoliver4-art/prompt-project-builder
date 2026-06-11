# Mobile Price Tracker

Daily tracker of **Vivo / Claro / TIM** mobile plan prices and benefits in Brazil
(**Pré-pago, Controle, Pós-pago, Vivo Easy/Lite, Claro Flex**), starting with **São Paulo (SP)**,
accumulated into a versioned Excel time-series.

> **Read [`CONTEXT.md`](CONTEXT.md) and [`PROGRESS.md`](PROGRESS.md) first.** CONTEXT is the
> knowledge base (architecture, recon, schema, decisions); PROGRESS is the live status + log.

## What's here
```
config/sources.yaml        the single source of truth: carriers, categories, URLs, states, schedule
src/mobile_tracker/
  models.py                the Plan schema (one row per plan per snapshot)
  config.py                loads sources.yaml -> scrape targets
  excel_writer.py          builds the history/latest/changes/summary workbook
  adapters/                per-carrier fetch+parse (vivo / claro / tim) + a base interface
  main.py                  orchestrator (--demo offline, or live)
tests/                     offline unit tests (schema + Excel logic)
data/                      output workbook lives here (mobile_plans.xlsx)
```

## Run it
```bash
# from this folder
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium     # only needed for the live browser fallback

pytest -q                                  # run the offline tests
python -m mobile_tracker.main --demo       # offline demo -> data/mobile_plans.xlsx
python -m mobile_tracker.main              # live (requires implemented adapters + internet)
python -m mobile_tracker.main --only claro # restrict to one carrier
```

## Status
Scaffold complete and **offline-verifiable** (schema + Excel pipeline tested with sample data).
The three **adapters are stubs** with documented strategies — implementing the live parsing
(Claro `__NEXT_DATA__` first, then Vivo AEM, then TIM HTML) is the next work. See `PROGRESS.md`.

## Scheduling & backup
Daily runs are designed for **GitHub Actions** (`.github/workflows/mobile-price-tracker.yml` at the
repo root), which commits the refreshed Excel back to the repo and can mirror it to Google Drive.
See `GOVERNANCE.md §5`.
