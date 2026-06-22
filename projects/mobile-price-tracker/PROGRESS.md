# PROGRESS — Mobile Price Tracker

> The dated running log + status board. This is the **communication channel** between the Architect
> and Code (via the Bridge). Every working cycle appends here (chronological, newest at the bottom).
> **Standing rule (Bridge):** every CODE TASK ends by updating this file AND CONTEXT.md (durable
> knowledge), committed + pushed — new sessions bootstrap exclusively from these files. See INSTRUCTIONS §2.1.

---

## Status board

| Area | State | Notes |
|------|-------|-------|
| Foundations (root docs) | ✅ done | INSTRUCTIONS / GOVERNANCE / WORKFLOW / READMEs created. |
| Project scaffold | ✅ done | Folder layout, CONTEXT, PROGRESS, config, src skeleton, tests, CI workflow. |
| Reconnaissance | ✅ done | Stacks identified (TIM=Drupal, Claro=Next.js, Vivo=AEM). See CONTEXT §3. |
| Data schema | ✅ done | `Plan` dataclass + stable **`plan_id`** (CONTEXT §6 / §4 decision); canonical key = (carrier, state, plan_id). |
| Excel writer | ✅ done (offline) | Works on fixture data; verified by demo run + unit test. |
| Adapters (vivo/claro/tim) | ✅ all three live | **Claro** (`__NEXT_DATA__`), **Vivo** (Playwright DOM), **TIM** (Drupal `ofertas` JSON) parse real SP plans. |
| Live scraping | 🟡 3 carriers live | **Claro** 13 + **Vivo** 24 + **TIM** 15 = **52** live SP plans, 2026-06-19. Claro-**prepaid** + `plan_id` pending. |
| Scheduling (GitHub Actions) | 🟡 drafted | Workflow file present; needs repo + secrets + first run. |
| GitHub + Drive backup | 🟡 partial | GitHub repo live (private, pushed by Code). Drive mirror not started. |

Legend: ✅ done · 🟡 in progress / partial · 🔌 not started · ⛔ blocked

---

## Next actions (Architect's recommendation)
1. **Bridge:** create the GitHub repo and push this scaffold (CODE TASK #1).
2. **Code:** set up the Python env, install deps, run the offline demo + tests to prove the pipeline (CODE TASK #2).
3. **Code:** implement the **Claro** adapter first (cleanest — `__NEXT_DATA__` JSON), report a sample of real SP plans (CODE TASK #3).
4. Then Vivo (AEM `.model.json` probe), then TIM (HTML + image-price handling).
5. Wire GitHub Actions to run daily and commit the Excel; then add the Drive mirror.

---

## Log

### 2026-06-11 — Project initialized (Architect)
- Created the builder repo and the four root docs (INSTRUCTIONS, GOVERNANCE, WORKFLOW, README).
- Stood up the `mobile-price-tracker` project: CONTEXT, PROGRESS, `config/sources.yaml`, `src/mobile_tracker/*`, tests, and a GitHub Actions workflow.
- Ran reconnaissance on all three carriers via `web_fetch`; recorded stacks, data-access strategy, and gotchas in CONTEXT §3.
- Defined the `Plan` schema and the 4-sheet Excel layout; implemented `excel_writer.py` and a `--demo` mode in `main.py` seeded with sample data (incl. the real Vivo *60GB/R$150* offer found in recon) so the pipeline is verifiable offline.
- Wrote adapter **stubs** with documented per-carrier strategies; real parsing is deferred to Code on the live sites (sandbox is network-restricted).
- **Open questions for the Bridge:** see CONTEXT §10.
- **Handed off:** CODE TASK #1 (init repo) and #2 (env + verify pipeline).

### 2026-06-11 — Excel formula fix + offline verification (Architect)
- **Bug:** on LibreOffice recalc, the summary sheet's `MINIFS`/`MAXIFS` returned the `IFERROR` fallback (`"-"`) while `AVERAGEIFS`/`COUNTIF` worked.
- **Cause:** `MINIFS`/`MAXIFS` are post-2007 functions and must be stored with the `_xlfn.` prefix to be recognized by the OOXML engine; the pre-2007 functions don't need it.
- **Fix:** `excel_writer.py` now writes `=IFERROR(_xlfn.MINIFS(...),"-")` and `=IFERROR(_xlfn.MAXIFS(...),"-")`.
- **Verified:** rebuilt 3 synthetic snapshots (2026-06-09/10/11), recalced with LibreOffice → **0 formula errors, 12 formulas**; summary now computes real values (e.g. vivo min 14.99 / max 139, claro 59.99 / 119.99, tim 49.99 / 139.99). `pytest` → **6 passed**.
- **Status:** offline pipeline (schema → writer → 4 sheets → recalc) is green and idempotent. Ready to hand to Code.

### 2026-06-11 — Bridge decisions recorded (Architect)
- Resolved all four open questions; CONTEXT bumped to **v0.2.0** (§10 + §7/§8 + changelog).
  1. **Excel layout:** per-carrier sheets + dashboard = **backlog**, build after live pipeline works; keep interim function-sheets.
  2. **Plan depth:** **full detail** — adapters expand "ver mais"/modals. Noted in each adapter docstring + §8 (Playwright-favored, longer runs).
  3. **Drive mirror:** **rclone inside GitHub Actions** (runs unattended; desktop-sync needs machine on). One-time local `rclone config` by the user → `rclone.conf` stored as a GitHub Secret → `rclone copy` step after commit.
  4. **History:** keep all snapshots forever.
- `pytest` still **6 passed**; edited adapters parse clean.
- Unchanged: CODE TASK #1 (init repo) and #2 (offline verify) are unaffected by these choices and ready to run now. The decisions shape CODE TASK #3+ (live adapters) and the later Actions/Drive wiring.

### 2026-06-11 — CODE TASK #1 done: repo initialized and pushed (Code)
- Repo initialized and pushed: **https://github.com/rafaelxoliver4-art/prompt-project-builder** (private, branch `main`, root commit `463c0d3`). INSTRUCTIONS → **v1.1.0** (Code-writes-all-files role split; §6 "Where work is saved" added). Offline pipeline verified earlier by the Architect — 6 tests passing.
- **Caveat for the Actions wiring task:** `.github/workflows/mobile-price-tracker.yml` is **excluded from the push** (still on disk, untracked). The machine's `gh` OAuth token lacks the `workflow` scope, and GitHub rejects any push that adds a workflow file without it. Before wiring CI: run `gh auth refresh -h github.com -s workflow` (Bridge completes the device-code + email verification on github.com), then commit and push the workflow file.
- Repo-local git identity set (`rafaelxoliver4-art` / `rafaelxoliver4@gmail.com`); no global config touched. Verified no secrets staged (`.env`/`*.key`/`rclone.conf` excluded by `.gitignore`).

### 2026-06-11 — CODE TASK #2 done: offline pipeline verified on the real machine (Code)
- Environment: **Windows 11 Pro (10.0.26200), Python 3.13.13**, venv at `.venv/`, all `requirements.txt` deps installed, Playwright **Chromium installed** (ready for live tasks).
- `python -m pytest -q` → **6 passed** (17.50s).
- `python -m mobile_tracker.main --demo` → `Wrote data\mobile_plans.xlsx: 12 plans in latest (2026-06-11), 3 snapshot(s), 5 change(s).` (Note: `python -m` needs `PYTHONPATH=src` — pyproject only wires `src/` for pytest; consider `pip install -e .` or a runner script in a future task.)
- Workbook verified in **real Excel (COM recalc)**: 4 sheets (`history`/`latest`/`changes`/`summary`); summary KPIs compute real values — vivo 4 plans min R$ 14.99 / avg R$ 92.25 / max R$ 150.00; claro 4 plans 59.99 / 83.74 / 119.99; tim 4 plans 30.00 / 74.99 / 139.99. No `"-"` fallbacks.
- Demo-overwritten `data/mobile_plans.xlsx` restored via `git checkout --` (not committed, per task guardrail). **Offline pipeline verified on the real machine.**

### 2026-06-11 — Bridge standing rule: two-files closing ritual (Code, on Bridge's instruction)
- Rafael's rule, now codified: **every CODE TASK ends with BOTH PROGRESS.md (dated entry) and CONTEXT.md (durable knowledge) updated, committed, and pushed.** Rationale: new chat/Code sessions bootstrap exclusively from these files — anything not written here is lost.
- Written into INSTRUCTIONS **v1.2.0** (§2.1 "Closing ritual" + changelog) and into both files' headers. CONTEXT bumped to **0.2.2**.
- Also flagged by the Bridge: the prices in the workbook are **demo sample data, not real prices** (see CONTEXT §5 note); Bridge is raising it with the Architect. Real prices arrive with the live adapters (CODE TASK #3+).

### 2026-06-11 — Backup to Google Drive + machine transfer prep (Code)
- Bridge is moving to another computer; asked to ensure everything is saved to GitHub **and** Google Drive.
- **GitHub:** verified fully pushed — working tree clean, `origin/main` at `0587ba9` (only untracked item is `.github/`, the workflow file that can't be pushed yet — workflow-scope auth pending).
- **Google Drive:** copied the full project to **`G:\Meu Drive\prompt-project-builder`** (account `rafaelxoliver4@gmail.com`, Drive Desktop running) via `robocopy /E` excluding `.venv`/`__pycache__`/`.pytest_cache`. The Drive copy **includes `.git` history AND `.github/workflows/mobile-price-tracker.yml`** — so it is the only cloud copy that has the workflow file. ~0.2 MB; all key files verified present.
- Recorded the three-copy map + new-machine bootstrap steps in **CONTEXT §5** (v0.2.3). Key gotcha for the new machine: a fresh `git clone` will be **missing the `.github/` workflow file** — restore it from the Drive backup.
- ⚠️ Drive Desktop syncs the local `G:\Meu Drive` folder to the cloud in the background; allow a moment for upload to finish before powering down this machine.

### 2026-06-17 — CODE TASK #2.5: transfer verified on machine #2 (Code)
- **Machine:** Windows 11 **Home** Single Language (10.0.26200), **Python 3.12.10**, user `rafae`. Project arrived via **OneDrive sync**, not a fresh clone — so `.git` history and the `.github/` workflow file came across together. Working copy: `C:\Users\rafae\OneDrive\Área de Trabalho\prompt-project-builder`.
- **Git verification — identical to GitHub:** `git fetch` OK; local `HEAD == origin/main == 0f557e4` ("docs: backup-to-Drive…"); `git diff origin/main` → **no differences** (tracked tree byte-identical); ahead/behind `0 0`; only untracked item is `.github/`. (`git fsck` flagged a stale reflog entry + dangling objects — harmless residue of the folder-copy; committed history intact.)
- **Workflow file:** **already present** (no restore needed) — OneDrive carried it. Byte-identical (SHA256) to the copy under the sibling `…\CFA\prompt-project-builder\` folder.
- **Google Drive backup:** **could not be verified from this machine** — Google Drive Desktop is **not installed** here (no `DriveFS`, no mounted drive). The cloud mirror (`rafaelxoliver4@gmail.com`) presumably remains intact, untouched by the transfer; verify it later from a machine with Drive Desktop, or treat OneDrive+GitHub as sufficient redundancy.
- **⛔ Env rebuild + smoke test DEFERRED (network blocker).** Removed the stale OneDrive `.venv` (Python 3.13 from machine #1) and created a fresh Python-3.12.10 venv, but **`pip install` cannot reach PyPI**. Diagnosed: active **McAfee VPN** (MTU 1420, prioritized) is an **MTU/PMTUD black hole** — large packets to Fastly IPs (`151.101.x.x`: pypi.org, files.pythonhosted.org) are dropped (`ping -f -l 1472` → "needs fragmentation, DF set"), small packets reply. github.com/example.com fine. **So `pytest` and `--demo` were not run on this machine.** Fix (Bridge): disconnect McAfee VPN or clamp MTU, then `pip install -r requirements.txt` + `playwright install chromium` + re-run the offline smoke test (it already passed on machine #1).
- **Decision (Bridge, 2026-06-17):** git proves this copy is identical to GitHub → **continue the project from this machine.** Env/smoke re-verification deferred until the network is sorted.
- **Net:** transfer verified on the new machine (working copy == GitHub; workflow file present). Outstanding: rebuild env once McAfee VPN MTU issue is resolved; verify the Drive mirror from a Drive-enabled machine.

### 2026-06-17 — Cross-check with machine #1 Code (transfer Q&A, via Bridge)
Machine #2 sent three open questions to the still-running machine #1 Code instance; Bridge relayed the answers. Results:
- **Q1 — Google Drive mirror: CONFIRMED intact by machine #1.** The `robocopy` to `G:\Meu Drive\prompt-project-builder` finished successfully and `.github/workflows/mobile-price-tracker.yml` **is present inside the Drive copy** (re-verified on machine #1, still powered on). Caveat: a definitive "Drive Desktop finished uploading to cloud" signal only exists in the tray UI, not programmatically — but files are fully materialized locally (not dehydrated). **Moot for machine #2 anyway**, which got the project via OneDrive (already has `.git` + workflow file), so it is not dependent on the Drive copy.
- **Q2 — Local-only / gitignored files: NONE needed.** Machine #1 scan confirmed the only untracked file is `.github/workflows/mobile-price-tracker.yml` (already present on machine #2); ignored items are only regenerable caches (`.venv/`, `.pytest_cache/`, `__pycache__/`). **No `.env`, no `rclone.conf`, no `*.key`/`*.secret`, no credentials** anywhere in the tree (confirmed absent). Secrets will live in GitHub Secrets when wired.
- **Q3 — `gh` workflow-scope auth: NOT done, and per-machine.** Machine #1's token still has `gist, read:org, repo` (no `workflow`); workflow file is still **not on GitHub** (`origin/main == e8deb47`). `gh` auth is per-machine, so machine #2 must run `gh auth refresh -h github.com -s workflow` itself (device-code + email verification) before it can `git add .github/ && commit && push` the workflow file to land it on GitHub.
- **⚠️ NEW HAZARD — shared `.git` over cloud sync.** The `.git` folder lives inside the OneDrive-synced directory, and BOTH machines now sync the same folder. Machine #1 observed its local HEAD jump `0f557e4 → e8deb47` with no git command — OneDrive overwrote `.git` from machine #2's version. Currently consistent (both at `e8deb47`), but a cloud-synced `.git` written by two active machines can **corrupt the repo or create silent divergence** (`…-conflicted copy…` files in `.git/`). **Rule going forward: work on ONE machine at a time and sync between them via GitHub (`push`/`pull`), NOT by letting OneDrive/Drive replicate `.git`.** Since machine #2 is the new home, machine #1 should stop committing in this folder.
- **⚠️ Workflow bug confirmed (machine #1).** The CI workflow's **"Run tracker"** step calls `python -m mobile_tracker.main` **without `PYTHONPATH=src`**, so the first CI run will hit the same `ModuleNotFoundError` documented in CONTEXT §5. Verified on machine #2: no `PYTHONPATH` anywhere in `.github/`. Fix before the first Actions run — add `env: PYTHONPATH: src` to the step, or `pip install -e .` in the install step.
- **Note (machine #2):** a stray non-git duplicate of the project also exists at `…\Área de Trabalho\CFA\prompt-project-builder\` (no `.git`; identical workflow file). Harmless, but a candidate for cleanup to avoid confusion.
- **Net:** all three questions resolved; transfer fully corroborated from both ends. Two action items recorded for later: (a) the `.git`-over-cloud-sync hazard → use GitHub to sync, not OneDrive; (b) the workflow `PYTHONPATH=src` fix before wiring Actions.

### 2026-06-19 — Single-machine consolidation + env rebuilt + smoke test GREEN (Code)
- **Bridge clarification:** there is only **one** working machine — this one (user `Rafael`, Windows 11 Pro, **Python 3.13.14**). The machine-#1/#2 transfer track is set aside; CONTEXT §5's machine-#2 sections are now marked historical. Future PC migration will go via GitHub `git clone`, not folder sync. Working in place under OneDrive for now (single writer → no `.git` collision risk); the OneDrive relocation is deferred to the future PC change.
- **Env rebuilt (the deferred #2.7 work, done here):** removed the foreign OneDrive-synced `.venv` (the `rafae`/Python-3.12.10 one — wrong interpreter for this machine), created a fresh venv on **Python 3.13.14**. `pip install -r requirements.txt` → **completed cleanly** (exit 0; no PyPI/VPN blocker on this machine — the McAfee-VPN MTU issue was machine-#2-only). `playwright install chromium` → done.
- **Offline smoke test GREEN:** `$env:PYTHONPATH="src"; pytest -q` → **6 passed**. `--demo` → `Wrote data\mobile_plans.xlsx: 3 plans in latest (2026-06-19), 4 snapshot(s), 12 change(s).` Excel COM recalc confirmed 4 sheets + real summary KPIs (vivo R$150.00 / claro R$64.99 / tim R$30.00 — one demo plan per carrier). Demo workbook restored via `git checkout --` (not committed).
- **Still outstanding (unchanged):** `.github/workflows/mobile-price-tracker.yml` remains un-pushed (this machine's `gh` token still lacks `workflow` scope); CI workflow needs the `PYTHONPATH=src` fix before the first Actions run. Both deferred to the Actions-wiring task.
- **Next:** CODE TASK #3 — implement the Claro adapter (first live data via `__NEXT_DATA__`).

### 2026-06-19 — CODE TASK #3: Claro adapter live — FIRST REAL DATA (Code)
- **Editable install:** `pip install -e .` — `python -m mobile_tracker.main` now runs with **no `PYTHONPATH`** (kills the recurring quirk and the CI "Run tracker" bug). `pyproject.toml` already had the packaging config; no change needed.
- **Adapter** (`adapters/claro.py`): split into a **pure** `parse_next_data(data, target)` (offline-testable) + a polite `fetch()` (one `httpx` GET/page, real UA, 2–6s random delay, single retry, raw capture saved to `data/raw/`). Parses the Storyblok `__NEXT_DATA__` tree (`dynamicComponents.body[] → card_360 → data.data[]`). **No Playwright needed** — modal detail is already embedded (§3 documents the full JSON path + the two price formats).
- **Live run** `python -m mobile_tracker.main --only claro` → `Collected 13 valid plans across 4 targets. claro: 13`. (Exit code 3 is the expected vivo/tim-zero alert from a single-carrier run, not a failure.)
  - **postpaid (5):** Pós 60GB R$124,90 · Pós 50GB com GeForce NOW R$164,90 · Pós 100GB R$179,90 · Pós 150GB R$239,90 · Pós 200GB R$339,90
  - **control (4):** Controle 20GB R$44,90 · Controle 25GB R$59,90 (promo R$54,90) · Controle 30GB R$69,90 · Controle 30GB R$99,90
  - **flex (4):** Flex 15GB R$44,90 · Flex 20GB R$59,90 · Flex 30GB R$69,90 · Flex 40GB R$119,90
- **Tests:** added `tests/test_claro.py` (5 tests) against a trimmed 44KB real-capture fixture (`tests/fixtures/claro_pos_sp.json`) covering field mapping, the slug-name fallback, promo pricing, BRL parsing, and dedup. Full suite **6 → 12 passed**.
- **Findings / deferred:** (a) **Claro prepaid (Prezão)** uses a different layout (`card`/`tab_select`, no `card_360`) → 0 plans today; needs its own parser. (b) Two `Controle 30GB` tiers share a name at different prices — both kept in `history`; `latest` (keyed by name) collapses them. (c) No anti-bot wall encountered — plain GET returned full `__NEXT_DATA__`.
- Workbook restored after the live run (not committed). Raw captures stay gitignored.
- **Next (Architect):** Vivo adapter (AEM `.model.json` probe) or TIM (HTML + SVG-price), and optionally a Claro-prepaid parser.

### 2026-06-19 — CODE TASK #4: Vivo adapter live — second carrier (Code)
- **Fetch path (recon):** plain `httpx` GET → **403** (anti-bot challenge, ~6KB, no prices); `…<page>.model.json` → **also 403**; no usable embedded JSON. A real **headless Chromium (Playwright)** → **HTTP 200**, full ~1MB render, **no CAPTCHA shown**. → Vivo uses **Playwright + DOM scrape** (the sanctioned §10.2 fallback — a real browser, not evasion). Documented in CONTEXT §3.
- **Adapter** (`adapters/vivo.py`): pure `parse_vivo_html(html, target)` (selectolax scrape of `.unique-card`: name `.unique-card__plan`, price `.total-card-price-value`, data `.unique-card__header-benefit`) + Playwright `fetch()` (one load/page, cookie-banner dismiss, polite delay, raw `.html` capture). Mirrors the Claro split.
- **Live run** `python -m mobile_tracker.main --only vivo` → `Collected 24 valid plans across 4 targets. vivo: 24` (exit 3 = expected claro/tim zero-alert). **All four categories parse with one selector set:**
  - **postpaid (7):** Vivo Pós com Amazon R$150 · Globoplay R$165 · Spotify R$165 · Premiere R$180 · Netflix R$180 · Disney+ R$180 · Travel R$215 (70GB)
  - **control (8):** Vivo Controle R$59 · R$80 · Saúde/Educação/Vantagens R$90 · Música/Netflix R$95 · Entretenimento R$110
  - **lite (5):** Easy Lite Anual R$20 · Easy Lite R$30/R$40/R$35/R$50
  - **prepaid (4):** Vivo Pré R$17–R$30
- **Tests:** added `tests/test_vivo.py` (5 tests) against a trimmed 132KB real Playwright-render fixture (`tests/fixtures/vivo_postpaid_sp.html`). Full suite **12 → 17 passed**.
- **Blocks:** none (Playwright passed cleanly; no CAPTCHA). httpx 403 is documented, not evaded.
- **Backlog recorded (per Bridge):** CONTEXT §7 extended with deferred product items — (a) per-operator sheets + cross-operator "comparable plans"; (b) promotions view (promo-vs-regular over time); (c) formatted dashboard — under a **data-correctness/coverage-first** rule. Logged data-quality items: Claro-prepaid parser, and plan-name uniqueness → a stable `plan_id` (schema change, **needs Bridge YES**).
- Workbook restored after the live run (not committed). Raw captures stay gitignored.
- **Next (Architect):** TIM adapter (Drupal HTML + SVG-embedded prices, state in URL path), and/or the deferred Claro-prepaid parser / `plan_id` schema decision.

### 2026-06-19 — CODE TASK #5: TIM adapter live — all three carriers now live (Code)
- **Fetch path (recon):** TIM is server-rendered Drupal; plain `httpx` GET → **200** (no anti-bot, no browser). DOM is noisy (Acquia Site Studio, per-instance UUID classes, device sales) with **no clean plan-card class and no `<table>`**. The structured grid is embedded JSON: `<script data-drupal-selector="drupal-settings-json">` → **`settings["ofertas"][]`**. Documented in CONTEXT §3.
- **SVG-price outcome — no OCR needed.** The hero SVG `alt` carries the marketing headline price, but **every per-plan price is a clean JSON text value** (`field_preco_card_oferta`), so OCR was unnecessary (no Bridge ask required). Body-text prices (HBO Max R$20,90 etc.) are add-ons, ignored.
- **Adapter** (`adapters/tim.py`): pure `parse_tim_html(html, target)` (reads the drupal-settings JSON, walks to `ofertas`, maps `field_preco_card_oferta` → price and cleaned `title` → name+GB) + thin `httpx` `fetch()` (real UA, delay, single retry, raw `.html` capture). No Playwright.
- **Live run** `python -m mobile_tracker.main --only tim` → `Collected 15 valid plans across 3 targets. tim: 15` (exit 3 = expected vivo/claro zero-alert).
  - **control (5):** TIM Controle Plus 45GB R$64,99 · TIM Controle 41GB R$58,99 · Premium 53GB R$84,99 · Light Express 31GB R$60,99 · Pro Express R$64,99
  - **postpaid / TIM Black (7):** 70GB R$129,99 · Plus 80GB R$149,99 · Premium 110GB R$159,99 · C Ultra 95GB R$159,99 · A Express 67GB R$119,99 · B Express 82GB R$144,99 · C Express 107GB R$164,99
  - **prepaid / TIM Pré XIP (3):** 6GB R$20 · 8GB R$25 · 16GB R$30 (price = recarga amount)
- **Tests:** added `tests/test_tim.py` (5 tests) against a tiny 1KB fixture holding the real `ofertas` JSON (mapping, title cleaning incl. `[PROD]`/`[On Air]` + dash handling, price parse, dedup). Full suite **17 → 22 passed**.
- **Blocks:** none.
- **Milestone:** **all three carriers now live — 52 real SP plans** (Claro 13 + Vivo 24 + TIM 15). Parked the Bridge's cross-operator **comparison methodology** (within-category, align by price rank) in CONTEXT §7.
- Workbook restored (not committed). Raw captures gitignored.
- **Next (Architect):** the deferred items — Claro-prepaid parser, the `plan_id` schema decision (needs Bridge YES), then wiring the **daily GitHub Actions job** (first committed history) + the per-operator/promotions/dashboard backlog.

### 2026-06-19 — CODE TASK #6: stable plan_id + re-keyed latest/history/changes (Code)
- **Schema change (Bridge-approved):** added `plan_id` to the `Plan` dataclass + `COLUMNS` (after `plan_name`); CONTEXT → **v0.3.0**. `[DECISION 2026-06-19]` recorded in §4: canonical key = (carrier, state, plan_id), **never price-derived**.
- **Per-carrier plan_id (native where available, §3):**
  - **Claro** → plan **slug** (`claro:plano-controle-30gb` vs `claro:plano-controle-30gb-gaming`).
  - **Vivo** → **offer code** from the card HTML (`vivo:VIV202600029270` vs `…300`); `SELF…` fallback.
  - **TIM** → Drupal **`nid`** (`tim:155891`); `field_sku` then a name-slug as fallbacks. (Note: `nid` is a Drupal list-field `[{"value": …}]` — unwrapped via `_field`.)
  - Fallback for any card lacking a native id → `carrier:<slugified plan_name>` (deterministic). Added `slugify()` to `adapters/base.py`.
- **`excel_writer` re-keyed:** history dedup = (snapshot_date, carrier, state, plan_id); `latest` no longer collapses same-named plans; `changes` matches by (carrier, state, plan_id) and now carries a `plan_id` column. Falls back to `plan_name` if `plan_id` is ever missing (so old/demo rows don't crash).
- **Tests (22 → 27):** each adapter test asserts `plan_id` is native + unique; **collision test** proves two "Controle 30GB" with distinct ids both survive in `latest`; **per-plan price-change test** proves a move on one isn't confused with the same-named other. Rebuilt the TIM fixture to include `nid`. All offline.
- **Review run** `python -m mobile_tracker.main` (all 3 carriers) → `Collected 50 valid plans across 11 targets` (claro 13 / tim 15 / vivo 22); **`latest` = 49 distinct rows**, every `plan_id` set + unique. Confirmed the duplicate-named plans are now **separate rows**: Claro "Controle 30GB" ×2 (R$69.9 / R$99.9), Vivo "Vivo Controle" ×2 (R$59 / R$80). (50→49: one Claro flex card cross-listed on two category pages correctly shares its `plan_id`.)
- **Review workbook left at `data/mobile_plans.xlsx` (uncommitted)** for the Bridge to open — fresh single snapshot of real SP data. Not committed (per task). Raw captures gitignored.
- **Next (Architect):** wire the **daily GitHub Actions job** (first committed history; needs the one-time `gh` `workflow`-scope auth + the `PYTHONPATH=src`/editable-install fix in the workflow), then the Claro-prepaid parser and the per-operator / promotions / dashboard backlog.

### 2026-06-22 — CODE TASK #7: data-quality gaps closed (prepaid + promo) (Code)
- **Vivo prepaid: 1 → 4 tiers.** Root cause: the 4 recharge tiers (R$17/20/25/30) all share ONE page-level offer code (`VIV202600022379`) and the name "Vivo Pré", so the #6 `plan_id` collapsed them. Fix: `plan_id = vivo:<code>-<gb>gb` — the data allowance (25/9/5/4 GB; non-price) disambiguates. Vivo total 22 → **24**.
- **Claro prepaid: 0 → 1 (Prezão).** New `parse_claro_prepaid` over the `tab_select` layout (the Prezão page is NOT `card_360`): "Prezão R$1 por dia", price R$1/dia from the tab title, 12GB from the content; recarga tiers (R$15–30) noted in `price_note`, not as separate plans. Deeper Pré tiers deferred (§7). Claro total 13 → **14**.
- **Promo prices wired for all three carriers** (`price_promo_brl` + `price_note`): Claro = `price.prefix` struck regular; Vivo = `.unique-card__price-old`; TIM = `field_preco_adicional_tracejado`. Live coverage right now = **1** (Claro "Controle 25GB" R$59,90→R$54,90); Vivo/TIM mechanism present but no promo on today's fetched pages. Populates automatically when a discount is shown.
- **TIM "Controle Pro Express" `data_gb`:** left **null** — its allowance isn't in the structured `ofertas` fields (only a "500 MEGA" bonus highlight) and the title has no GB token; documented in §3 rather than inferring a misleading value.
- **Tests 27 → 30:** Vivo prepaid 4-distinct-tier test, Vivo promo (struck-price) test, Claro Prezão test. Added trimmed real fixtures `vivo_prepaid_sp.html` + `claro_prepaid_sp.json`. All offline.
- **Review run** `python -m mobile_tracker.main` → `Collected 53 valid plans` (claro 14 / tim 15 / vivo 24); **52 distinct in `latest`**, every `plan_id` unique. Vivo prepaid shows all 4 tiers; Claro prepaid present. (Bonus: `plan_id` keying also collapsed the cross-listed Claro flex card correctly — control now shows its true 3.) CONTEXT → **v0.3.1**.
- **Review workbook left at `data/mobile_plans.xlsx` (uncommitted)** for the Bridge. Not committed; raw captures gitignored.
- **Next (Architect):** the dataset is complete + correct → wire the **daily GitHub Actions job** (first committed history; needs the one-time `gh workflow`-scope auth + the editable-install/`PYTHONPATH` fix in the workflow), then the per-operator / promotions / dashboard backlog.

### 2026-06-22 — CODE TASK #9: cross-operator comparison sheet (Code)
- Added the **`comparison`** sheet (presentation-only; adapters/schema/scraping untouched). Implements the Bridge's methodology (CONTEXT §7, moved from parking-lot to built): compare like-for-like **within each category**, aligned by **price rank**.
- **Groups → category:** Pure Postpaid=`postpaid`, Control/Hybrid=`control`, Prepaid=`prepaid`, Digital={`lite`,`flex`}. Each carrier's plans sorted ascending by `price_brl`, aligned across Vivo/Claro/TIM by rank; `price_promo_brl` shown inline when present (not re-ranked). Layout: `Rank | Vivo R$ | Claro R$ | TIM R$ | Vivo/Claro/TIM plan (XGB)`.
- **Code:** `build_comparison_data` (pure, offline-testable) + `_write_comparison` in `excel_writer.py`, wired after `latest`. `history`/`latest`/`changes`/`summary` untouched (existing-sheets test updated to expect 5 sheets).
- **Review run** (`python -m mobile_tracker.main`, 53 plans / 52 latest) → comparison sheet built with per-group max ranks: **Pure Postpaid 7, Control/Hybrid 8, Prepaid 4, Digital 5.** Rank-1 postpaid row = Vivo R$150 / Claro R$124,90 / TIM R$119,99 (each carrier's cheapest). Caveats print in-sheet (prepaid unit mismatch; Digital = Vivo Lite + Claro Flex, TIM none). Claro Controle 25GB shows its promo inline.
- **Tests 30 → 35:** ascending-per-carrier + rank-alignment, Digital pulls lite+flex (TIM empty), prepaid caveat present, four groups in order, write_workbook emits `comparison` without disturbing the others. All offline.
- **Review workbook left at `data/mobile_plans.xlsx` (uncommitted)** for the Bridge — open the `comparison` tab. **First cut — expect layout iteration.** CONTEXT → **v0.3.2**.
- **Next (Architect):** react to the comparison layout; then the **daily GitHub Actions job** (committed history) + the promotions-over-time view and dashboard.

### 2026-06-22 — CODE TASK #10: per-operator sheets (one tab per carrier) (Code)
- Added **one sheet per carrier** present in the latest snapshot (Vivo / Claro / TIM; absent carriers get none, so it scales). Presentation-only — adapters/schema/scraping untouched. §7 per-operator item moved backlog → built.
- **Structure:** within each sheet, plans **grouped by category** (Postpaid → Control → Digital {lite,flex} → Prepaid) with a bold sub-header, **sorted ascending by `price_brl`**. Readable column set: **Plan | Price R$ | Promo R$ | Data | Voice | Unlimited apps | Streaming | Notes** (Data = `data_gb`+`data_note`; Notes = `extra_benefits`+`price_note`; `plan_id` omitted; blank where null).
- **Code:** `build_operator_sheets` (pure, offline-testable) + `_write_operator_sheets` in `excel_writer.py`, wired after the comparison sheet. The five prior sheets (history/latest/changes/summary/comparison) untouched → **8 sheets total**.
- **Review run** (53 plans / 52 latest) → tabs built: **Vivo** 7+8+5+4, **Claro** (postpaid/control/flex/prepaid), **TIM** (postpaid/control/prepaid). Vivo sheet verified: Postpaid 150→215, Control 59→110, Digital 30→50, Prepaid 17→30, streaming + notes populated.
- **Tests 35 → 40:** one-sheet-per-present-carrier (TIM absent → no sheet), blocks grouped-in-order + price-sorted, only that carrier's plans, the 8-column set + promo/data formatting, write_workbook emits carrier sheets without disturbing the others. All offline.
- **Review workbook left at `data/mobile_plans.xlsx` (uncommitted)** — open the Vivo/Claro/TIM tabs. **First cut — expect iteration.** CONTEXT → **v0.3.3**.
- **Next (Architect):** react to the by-operator + comparison layouts; then the **daily GitHub Actions job** (committed history) and the promotions-over-time view / dashboard.
