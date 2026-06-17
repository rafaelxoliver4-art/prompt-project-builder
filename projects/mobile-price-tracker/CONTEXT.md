# CONTEXT — Mobile Price Tracker

> **Version:** 0.2.4 · **Last updated:** 2026-06-17 · Content decided by the Architect; written by Code.
> The *what / how / why* of this project and every decision behind it. This is the knowledge base and
> IP. If someone read only this file, they should understand the project well enough to rebuild it.
> **Standing rule (Bridge):** every CODE TASK ends by updating this file (durable knowledge) AND
> PROGRESS.md (dated log), committed + pushed — new sessions bootstrap exclusively from these files.
> See INSTRUCTIONS §2.1.

---

## 1. Goal

Track the **mobile plan prices and benefits** of Brazil's three big carriers — **Vivo, Claro, TIM** —
**every day**, and accumulate the results into a **versioned Excel time-series** so we can see how
plans and prices change over time.

## 2. Scope

- **Carriers & categories** (the plan families we track):
  - **Vivo** — Pós-pago, Controle, Vivo Easy/Lite, Pré-pago.
  - **Claro** — Pós, Controle, Flex, Pré (Prezão).
  - **TIM** — Pré-pago, Controle, Pós (TIM Black).
- **Geography:** **São Paulo (SP) first.** The design carries a `state` dimension from day one so other states can be switched on later by config, not rework.
- **Cadence:** once per day, end of day Brazil time (≈23:00 BRT → `0 2 * * *` UTC).
- **Output:** one Excel workbook, mirrored to GitHub + Google Drive.

The exact source URLs live in [`config/sources.yaml`](config/sources.yaml) (single source of truth — don't hardcode them in code).

## 3. Reconnaissance findings (2026-06-11)  ← valuable IP

Done via the chat's `web_fetch`. Each carrier's site is built differently, which drives the adapter design:

| Carrier | Tech stack | How to get plan data | Gotchas |
|---------|-----------|----------------------|---------|
| **TIM** | Drupal, **server-rendered HTML** | Parse the rendered HTML. | Page is **noisy** (dumps many offer names). **Some prices are baked into SVG images** (e.g. price in an SVG filename/alt text) — parser must handle image-embedded prices. **State is in the URL path** (`/sp/...`), so switching states = swapping the path segment. |
| **Claro** | **Next.js** | Prefer parsing the embedded **`__NEXT_DATA__` JSON** `<script>` (clean, structured) over scraping rendered cards. Fall back to a headless browser if needed. | City detection defaults to **São Paulo / SP** via geolocation; there's a "change city" control. State is **not** in the URL. |
| **Vivo** | **Adobe Experience Manager (AEM)** | Partially server-rendered — a headline offer is already visible in HTML (confirmed: *"60 GB por R$ 150/mês"*, offer code `SELF8221B240`). Full plan grid likely needs JS rendering; **probe for AEM `.model.json` endpoints** first (AEM often exposes a JSON model), else headless browser. | City via geolocation, defaults to SP; "trocar localização" control. State **not** in URL. Cookie consent banner present. |

**Implication:** no single scraping technique fits all three. We use a **per-carrier adapter** pattern with three strategies: JSON-extraction (Claro `__NEXT_DATA__`, maybe Vivo `.model.json`), HTML-parse (TIM), and a shared **headless-browser fallback** (Playwright) for anything that won't yield to a plain request.

## 4. Architecture

```
config/sources.yaml ─▶ orchestrator (main.py) ─▶ per-carrier Adapter ─▶ Plan records
                                                     (vivo/claro/tim)        │
                                                                             ▼
                                                                   excel_writer.py
                                                            (history / latest / changes / summary)
                                                                             │
                                                              committed to GitHub + mirrored to Drive
```

- **`config/`** — all volatile facts (URLs, states, schedule, per-carrier render hints, eventually selectors).
- **`models.py`** — the `Plan` dataclass = the canonical schema (one row per plan per snapshot).
- **`adapters/`** — `base.py` defines the interface; `vivo.py` / `claro.py` / `tim.py` implement fetching+parsing per the strategies above. Each returns a list of `Plan`.
- **`excel_writer.py`** — writes the workbook (see §6).
- **`main.py`** — loads config, runs the active adapters for the active state(s), validates, writes Excel, exits non-zero on failure (so CI/cron can alert).
- **Scheduler** — **GitHub Actions** cron, not local cron, so it runs with the user's machine off and naturally lands results on GitHub. Local cron remains a documented fallback.

### Decisions
```
[DECISION 2026-06-11] Scheduler = GitHub Actions, not local cron.
Choice: run the daily scrape in GitHub Actions; commit the refreshed Excel back to the repo.
Why: works when the user's machine is off; puts output on GitHub automatically (remote access for free);
     one mechanism satisfies "run daily" + "save to GitHub" + "access outside this machine".
Rejected: local cron/Task Scheduler — requires the machine on at 23:00 and an extra sync step to GitHub.
```
```
[DECISION 2026-06-11] Per-carrier adapter pattern + Playwright fallback.
Choice: one adapter module per carrier behind a common interface; shared headless-browser fallback.
Why: the three sites use different stacks (Drupal / Next.js / AEM); a single technique would be brittle.
Rejected: one generic scraper with CSS selectors for all — too fragile across three very different sites.
```
```
[DECISION 2026-06-11] Append-only history with snapshot_date.
Choice: each daily run appends a full set of rows tagged with snapshot_date; never overwrite past rows.
Why: the product *is* the time-series; we must be able to see price changes over time.
Rejected: overwriting a single "current prices" sheet — loses all history, defeats the purpose.
```

## 5. Tech stack

Python 3.11+ · `playwright` (headless Chromium, JS rendering) · `httpx` (fast plain requests where JS isn't needed) · `selectolax`/`beautifulsoup4` (HTML parsing) · `pandas` + `openpyxl` (Excel) · `pyyaml` (config) · `pytest` (tests). See `requirements.txt`.

### Verified execution environment (2026-06-11, CODE TASK #2)

- **Machine:** Windows 11 Pro (10.0.26200), Python **3.13.13**, venv at `projects/mobile-price-tracker/.venv/`, Playwright **Chromium installed**. Offline pipeline green here (6 tests, demo run, Excel-verified KPIs).
- **Run quirk:** `python -m mobile_tracker.main` fails with `ModuleNotFoundError` unless `PYTHONPATH=src` is set — `pyproject.toml` wires `src/` onto the path **for pytest only**. PowerShell: `$env:PYTHONPATH = "src"` before running. TODO for a future task: `pip install -e .` in CI/local setup, or a runner script, so the env var isn't needed.
- **Demo data ≠ real prices.** `--demo` seeds hardcoded sample plans (only the Vivo *60GB/R$150* figure came from real recon). Real prices arrive only with the live adapters (CODE TASK #3+).
- **Pending one-time auth:** the machine's `gh` token lacks the `workflow` scope, so `.github/workflows/mobile-price-tracker.yml` is untracked locally (pushes containing it are rejected). Before the Actions wiring task: `gh auth refresh -h github.com -s workflow` + Bridge completes the device-code/email check, then commit the workflow file.

#### Second machine verified (2026-06-17, CODE TASK #2.5)

- **Machine:** Windows 11 **Home** Single Language (10.0.26200), Python **3.12.10**, user `rafae`. The project transferred here via **OneDrive sync** (not a fresh `git clone`), so the working copy already includes both `.git` history **and** the untracked `.github/` workflow file.
- **Git verified:** local `HEAD == origin/main == 0f557e4`; `git diff origin/main` shows **no differences** (tracked tree byte-identical to GitHub); ahead/behind `0 0`; only untracked item is `.github/`. The OneDrive-synced workflow file is **byte-identical (SHA256)** to the copy in the sibling `...\Área de Trabalho\CFA\prompt-project-builder\` folder. Workflow file state: **already present (no restore needed).**
- **Minor:** `git fsck` reports one stale reflog entry + dangling objects — harmless residue from OneDrive copying `.git` mid-operation; committed history is intact (clean diff proves it). Optional cleanup: `git reflog expire --expire=now --all; git gc`.
- **⛔ Env NOT rebuilt on this machine yet — network blocker.** The stale OneDrive-synced `.venv` (Python 3.13 from machine #1) was removed; a fresh `python -m venv .venv` (Python 3.12.10) was created, but **`pip install` cannot reach PyPI.** Root cause: an active **McAfee VPN** interface (MTU 1420, InterfaceMetric 5 = prioritized) is an **MTU/PMTUD black hole** — `ping -f -l 1472` to a Fastly IP returns *"Packet needs to be fragmented but DF set"* while a 500-byte ping replies fine. General sites (example.com, github.com) work; Fastly-fronted hosts (pypi.org, files.pythonhosted.org, raw.githubusercontent.com — all `151.101.x.x`) time out on the large TLS response. **Fix (Bridge):** disconnect the McAfee VPN, or clamp the interface MTU, then re-run venv install + `playwright install chromium`. `git`/GitHub are unaffected (github.com is reachable). **pytest + `--demo` smoke test deferred** until deps install.
- **Decision (Bridge, 2026-06-17):** since git verification confirms this copy is identical to GitHub, **continue the project from this machine**; the offline smoke-test re-verification is deferred to whenever the network is sorted (it already passed on machine #1).

### Backups & machine transfer (2026-06-11)

Three copies of the project exist; **GitHub is the source of truth**, the other two are backups:

| Location | Path / URL | Contents | Notes |
|----------|-----------|----------|-------|
| **GitHub** (source of truth) | `https://github.com/rafaelxoliver4-art/prompt-project-builder` | Everything **except** `.github/workflows/*` | The workflow file is **not** pushed (workflow-scope auth still pending — see above). A fresh `git clone` will be missing it. |
| **Google Drive** (mirror) | `G:\Meu Drive\prompt-project-builder` (account `rafaelxoliver4@gmail.com`) | Full repo **including `.git` history AND the `.github/` workflow file**, minus `.venv`/caches | Made via `robocopy /E /XD .venv __pycache__ .pytest_cache`. Refreshed whenever docs change. This is the only copy that has the workflow file in cloud storage. **⚠️ Not locally verifiable from machine #2** — Google Drive Desktop is **not installed** there (no `DriveFS`, no mounted drive letter), so the cloud mirror could not be inspected on 2026-06-17; it presumably remains intact in the cloud, untouched by the transfer. |
| **OneDrive** (working copy, machine #2) | `C:\Users\rafae\OneDrive\Área de Trabalho\prompt-project-builder` | Live working tree — synced to machine #2; includes `.git` + the `.github/` workflow file | Verified identical to GitHub on 2026-06-17 (see "Second machine verified" above). A separate manual copy also exists at `...\Área de Trabalho\CFA\prompt-project-builder` (no `.git`; identical workflow file). |

**Bootstrapping on a new machine:**
1. `git clone https://github.com/rafaelxoliver4-art/prompt-project-builder` (gets everything that's pushed).
2. **Restore the workflow file** — `git clone` won't have `.github/workflows/mobile-price-tracker.yml`. Copy it from the Google Drive backup (`G:\Meu Drive\prompt-project-builder\.github\`) or recreate it; it is preserved there on purpose.
3. Recreate the environment per CODE TASK #2: `python -m venv .venv` → activate → `pip install -r requirements.txt` → `python -m playwright install chromium`. (`.venv` is intentionally **not** backed up — it's platform-specific.)
4. Set a repo-local git identity (`git config user.name/user.email`) and complete the `gh` workflow-scope auth before wiring Actions.

## 6. Data schema (one row = one plan in one snapshot)

| Column | Type | Notes |
|--------|------|-------|
| `snapshot_date` | date | YYYY-MM-DD — the daily key. |
| `snapshot_ts` | datetime | Full timestamp of the run. |
| `carrier` | str | `vivo` / `claro` / `tim`. |
| `category` | str | `postpaid` / `control` / `prepaid` / `lite` / `flex`. |
| `state` | str | `SP` for now. |
| `plan_name` | str | As shown on site (pt-BR). |
| `price_brl` | float | Headline monthly price, R$. |
| `price_promo_brl` | float? | Promo price if distinct from regular. |
| `price_note` | str? | e.g. "primeiros 3 meses", "com débito automático + conta digital". |
| `data_gb` | float? | Data allowance in GB (null/!= for unlimited — see `data_note`). |
| `data_note` | str? | Bonus/conditions, "internet ilimitada", accumulation, etc. |
| `unlimited_apps` | str? | Apps that don't consume data (WhatsApp, redes sociais…). |
| `voice` | str? | e.g. "ligações ilimitadas". |
| `sms` | str? | SMS terms. |
| `streaming` | str? | Bundled streaming (Netflix, Disney+, Max, Globoplay…). |
| `loyalty_months` | int? | Fidelity/lock-in period if any. |
| `extra_benefits` | str? | Anything else (roaming, cloud, etc.). |
| `source_url` | str | The exact page scraped. |
| `raw_ref` | str? | Path to the saved raw capture for audit. |

Nullable fields are expected to be sparse early — parsers improve over time. A row is **valid** if it has at least `carrier`, `category`, `state`, `plan_name`, and a `price_brl`.

## 7. Excel workbook layout

- **`history`** — append-only; every snapshot's rows, all columns. The time-series.
- **`latest`** — overwritten each run; the most recent snapshot only (the "what are prices today" view).
- **`changes`** — computed diff vs the previous snapshot date: new plans, removed plans, price ↑/↓.
- **`summary`** — run metadata + a few KPIs (plan counts per carrier, min/avg/max price) using Excel formulas.

> **BACKLOG (deferred, per §10.1):** target end-state is **one sheet per carrier** plus a formatted **dashboard** sheet (charts + headline KPIs). Build this only after the live pipeline is proven; the function-based sheets above are the interim layout.

## 8. Known challenges / risks

- **JS rendering & anti-bot.** Modern telecom SPAs may rate-limit or block headless browsers; we stay polite (1×/day, delays, real UA) and treat blocks as limitations to discuss, never to defeat covertly (see GOVERNANCE §3).
- **Prices inside images (TIM).** Need OCR or filename/alt parsing for some prices.
- **Promo vs regular price ambiguity.** Sites foreground discounted prices ("com débito automático…"); we capture both `price_brl` and `price_promo_brl` + a `price_note`.
- **Selector drift.** Sites redesign; selectors break. Mitigation: config-driven selectors, raw snapshots for re-parsing, a zero-rows-per-carrier alert.
- **Full-detail capture (Bridge decision §10.2).** Because we capture content behind "ver mais"/modals, adapters must click/expand before parsing — favoring Playwright across all three carriers and lengthening runs. Keep raw HTML/JSON snapshots so re-parsing never needs a re-fetch.
- **Sandbox can't reach the sites.** All live scraping runs via Code on the real machine / Actions; the chat sandbox is for design, fixtures, and offline-testable logic only.

## 9. Glossary (pt-BR → meaning)

- **Pré-pago** — prepaid (top-up). **Controle** — hybrid: capped postpaid with prepaid-like safety. **Pós-pago** — postpaid (monthly bill). **Vivo Easy/Lite** — Vivo's flexible/light line. **Claro Flex** — Claro's digital/flexible line. **Prezão** — Claro's prepaid offer. **TIM Black** — TIM's premium postpaid line. **Recarga** — top-up. **Fidelidade** — loyalty/lock-in. **Ligações ilimitadas** — unlimited calls.

## 10. Bridge decisions (resolved 2026-06-11)
1. **Excel granularity → one sheet per carrier + a dashboard, but DEFERRED.** Keep the current function-based sheets (`history`/`latest`/`changes`/`summary`) until the pipeline is proven end-to-end on live data. The per-carrier layout + a formatted dashboard is **BACKLOG** (see §7), built only after live adapters work.
2. **Plan depth → FULL DETAIL.** Capture everything, including content behind "ver mais" links and detail modals — not just the headline cards. Implication: adapters must *interact* (click/expand) before parsing, which pushes all three carriers toward Playwright rather than static HTML/JSON parsing, and means slightly longer, more fragile runs (mitigated by config-driven selectors + raw snapshots). See §3/§8.
3. **Drive mirror → `rclone` inside GitHub Actions (recommended).** Rationale: the daily job already runs unattended in Actions with the user's machine off, so the Drive write must run there too — desktop-sync needs the machine on, so it can't be the primary path. One-time setup: user runs `rclone config` locally to authorize a Drive remote (Claude never enters credentials — GOVERNANCE §1/🔴), then stores the resulting `rclone.conf` as a GitHub Secret; the workflow adds an `rclone copy` step after the commit. Desktop-sync can be layered on later for a real-time local copy by pointing a synced folder at a local clone. *(Affects GOVERNANCE §5.)*
4. **History horizon → keep ALL snapshots forever (default).** Rows are tiny; revisit roll-ups only if the file grows unwieldy.

## 11. Changelog
- **0.2.4 — 2026-06-17** — CODE TASK #2.5 (transfer verification on machine #2). Added §5 "Second machine verified": Windows 11 Home / Python 3.12.10, git verified identical to GitHub (`0f557e4`, clean diff), workflow file already present via OneDrive sync. Recorded the **McAfee VPN MTU black-hole** blocking PyPI (env rebuild + smoke test deferred), the Google-Drive-not-installed-here caveat, and the Bridge decision to continue from this machine.
- **0.2.3 — 2026-06-11** — Added §5 "Backups & machine transfer": three-copy map (GitHub = source of truth; Google Drive `G:\Meu Drive\prompt-project-builder` = full mirror incl. `.git` + the unpushed `.github/` workflow; OneDrive = working copy) and a 4-step new-machine bootstrap. Prompted by Rafael transferring to another computer.
- **0.2.2 — 2026-06-11** — Bridge standing rule added to the header: every CODE TASK ends by updating CONTEXT + PROGRESS, committed + pushed (new sessions bootstrap from these files). Mirrors INSTRUCTIONS v1.2.0 §2.1.
- **0.2.1 — 2026-06-11** — Code added §5 "Verified execution environment" after CODE TASK #2: Windows 11 / Python 3.13.13 machine verified, `PYTHONPATH=src` run quirk + `pip install -e .` TODO, demo-data-is-not-real-prices clarification, pending `workflow`-scope auth for the Actions file.
- **0.2.0 — 2026-06-11** — Bridge resolved all four open questions (§10): interim function-sheets with per-carrier + dashboard layout deferred to backlog; **full-detail** capture (expand modals → Playwright-favored); **rclone-in-Actions** chosen for the Drive mirror; keep all history. Recorded interaction/runtime implications in §8.
- **0.1.0 — 2026-06-11** — Project defined; reconnaissance on all three carrier stacks; architecture, schema, Excel layout, decisions, risks, and glossary recorded.
