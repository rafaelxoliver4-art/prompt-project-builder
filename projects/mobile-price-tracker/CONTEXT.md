# CONTEXT — Mobile Price Tracker

> **Version:** 0.3.3 · **Last updated:** 2026-06-22 · Content decided by the Architect; written by Code.
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

### Claro — live structure verified (2026-06-19, CODE TASK #3) ← valuable IP

Confirmed against the live SP pages with a plain `httpx` GET (no Playwright needed). `__NEXT_DATA__` carries a **Storyblok-style CMS tree**, not a clean plan list. The plan grid is the component whose `component == "card_360"` under:

```
props.pageProps.dynamicComponents.body[]      # iterate; pick components where component == "card_360"
  → <card_360>.data.data[]                     # each entry = one plan card
```

Per card (`actions[0]` is the plan action):
- **price** → `actions[0].price.price`. **Two formats:** postpaid embeds the `R$` (`"R$ 124,90"`); **control/flex** store a bare `"54,90"` with the struck-through regular price in `actions[0].price.prefix` (`"~De R$ 59,90~ Por:"`) → we record regular as `price_brl`, effective as `price_promo_brl`, and the prefix as `price_note`.
- **name** → `actions[0].link[0].modalContent.title` when it contains "GB" (e.g. `"Pós 100GB"`); otherwise the title is generic (`"Mais detalhes"` / `"Informações sobre o plano"`) and we **derive** `"<category_label> <N>GB"` from the modal accordion slug (`…plano-pos-60gb…`).
- **features** → `card.detail[*].label` (WhatsApp ilimitado, cloud, roaming, etc.) → `unlimited_apps` / `extra_benefits`.

**Full detail (§10.2):** the "ver mais" modal content is already embedded in `__NEXT_DATA__`, so **no Playwright interaction is required** for Claro.

**Per-category coverage:** **postpaid (5), control (4), flex (4)** parse from `card_360`. **Prepaid (Prezão) does NOT use `card_360`** — its page is built from `card`/`tab_select`/`double_card` components with a different shape, so prepaid yields 0 today and needs its own parser (deferred; "best-effort" per the task). Minor: control surfaces two `Controle 30GB` tiers at different prices that share a name — both are kept in history; the `latest` sheet (keyed by plan name) shows one.

### Vivo — live structure verified (2026-06-19, CODE TASK #4) ← valuable IP

A plain `httpx` GET returns **403** (anti-bot challenge page, ~6KB, no prices); appending `.model.json` is **also 403**. There is **no usable embedded JSON** (only an Adobe Target monitor blob). A **real headless Chromium (Playwright)** loads the page (HTTP 200, ~1MB) and renders the grid — **no CAPTCHA presented**. So Vivo = **Playwright + DOM scrape** (the sanctioned §10.2 fallback; `httpx` cannot pass the AEM/Akamai JS sensor — this is *use a real browser*, not evasion).

Plan grid = the `.unique-card` component (works on **all four** category pages). Per card:
- **name** → `.unique-card__plan` (e.g. "Vivo Pós com Amazon")
- **price** → `.total-card-price-value` (e.g. "150"; the visible `{{ total }}` inside `.unique-card__price` is an **unrendered template** — ignore it)
- **data** → `.unique-card__header-benefit` ("60 GB"); franquia/bônus → `.unique-card__switch-list`
- **bundle** (Netflix/Disney+/Globoplay/Spotify/Premiere…) is in the name + `.unique-card__features-cobranded-title` → mapped to `streaming` / `extra_benefits`.

**Per-category coverage (24 live SP plans):** postpaid 7, control 8, lite (Easy/Lite) 5, prepaid 4 — **all four work** with one selector set. A single page load suffices (no per-card "ver mais" clicking for the headline fields). Same naming-uniqueness caveat as Claro: several cards share a name at different prices (e.g. two "Vivo Controle", several "Easy Lite") → kept in history, collapsed in `latest`.

### TIM — live structure verified (2026-06-19, CODE TASK #5) ← valuable IP

Server-rendered Drupal (Acquia Site Studio). A plain `httpx` GET returns **200** (no anti-bot, no browser needed). The visible DOM is **noisy** — marketing components with per-instance UUID classes + device sales; **no clean plan-card class and no `<table>`**. The structured plan grid is embedded as JSON in `<script data-drupal-selector="drupal-settings-json" type="application/json">` → **`settings["ofertas"][]`** (one object per plan card). Per oferta:
- **price** → `field_preco_card_oferta` (clean text value, e.g. "64,99")
- **name** → `title` (e.g. "1 Card - TIM Controle Plus 45GB - [PROD]") → strip the `N Card -` prefix and the `[PROD]`/`[On Air …]` tags → "TIM Controle Plus 45GB"; `field_nome_da_oferta` is the bare-name fallback.
- **data_gb** → parsed from the cleaned title.

**SVG-embedded prices (the recon concern): RESOLVED — no OCR needed.** The hero banner price *is* in an SVG `alt` (control "45GB por R$64,99"; postpaid "Lê-se: a partir de 169 e 99"), but that's only the marketing headline. **Every per-plan price comes from the JSON text** (`field_preco_card_oferta`), so OCR is unnecessary. Body-text prices like "R$ 20,90 HBO Max" are **add-ons, not plans** — ignored.

**Per-category coverage (15 live SP plans):** control 5, postpaid (TIM Black) 7, prepaid (TIM Pré XIP) 3 — **all three parse from the same JSON path**, no Playwright. Prepaid `field_preco_card_oferta` is the recarga amount (R$20/25/30). State is in the URL path (`/sp/…`, config-templated).

### plan_id — per-carrier derivation (2026-06-19, CODE TASK #6) ← valuable IP

Stable, carrier-native, **never price-derived**, namespaced `carrier:<id>`:
- **Claro** → the plan **slug** from the modal accordion name (`claro:plano-controle-30gb` vs `claro:plano-controle-30gb-gaming`) — distinguishes the two 30GB tiers.
- **Vivo** → the **offer code** found in the `.unique-card` HTML (`vivo:VIV202600029270` vs `vivo:VIV202600029300`) — distinguishes the two "Vivo Controle"; the `SELF…` code is a fallback.
- **TIM** → the Drupal **node id** `nid` from the oferta (`tim:155891`); `field_sku` then a name slug as fallbacks.
- **Fallback (any carrier)** → `carrier:<slugified plan_name>` if a card lacks a native id (deterministic, still stable).

### Prepaid + promo gaps closed (2026-06-22, CODE TASK #7) ← valuable IP

- **Vivo prepaid** (`/pre-pago/vivo-pre`): the 4 recharge tiers (R$17/20/25/30) are all `.unique-card`s that **share ONE page-level offer code** (`VIV202600022379`) and the same name "Vivo Pré"; they differ only by data allowance (25/9/5/4 GB). So `plan_id = vivo:<code>-<gb>gb` — the data amount (non-price) disambiguates; postpaid codes are already unique so the suffix is harmless. (The earlier collapse to 1 plan was this id collision, introduced by the #6 keying.)
- **Claro prepaid** (Prezão, `/planos-pre/prezao`): **NOT `card_360`** — the Prezão offer lives in a **`tab_select`** component (tabs "Prezão R$1 por dia", "Prezão com anúncio"), marketing-style with no clean price field. `parse_claro_prepaid` reads the tab **title** for the daily price ("R$1 por dia") + the data allowance from the tab content → the Prezão headline (R$1/dia, 12GB). The recarga tiers (R$15/20/25/30) are top-up amounts of the **same** offer → recorded in `price_note`, not as separate plans. Deeper Pré tier extraction is best-effort/deferred (§7).
- **Promo prices** (`price_promo_brl` + `price_note`) where the site shows a regular-vs-effective pair:
  - **Claro** → struck-through regular in `actions[0].price.prefix` ("~De R$ 59,90~ Por:") — already captured.
  - **Vivo** → struck-through original in `.unique-card__price-old` (hidden when no promo).
  - **TIM** → `field_preco_adicional_tracejado` (struck regular; empty when no promo).
  Coverage reflects what each site currently displays (few promos are live now); the mechanism populates automatically when a promo appears.
- **TIM "Controle Pro Express" `data_gb`**: its allowance is **not in the structured `ofertas` fields** (only a "500 MEGA" bonus highlight, which isn't the plan allowance) and the title has no GB token → `data_gb` left **null** (documented; we don't infer a misleading value).

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
```
[DECISION 2026-06-19] plan_id is the canonical per-plan key (Bridge-approved schema change).
Choice: every Plan carries a stable `plan_id`, unique within a carrier and NEVER derived from price;
latest/history/changes are keyed by (carrier, state, plan_id) — not plan_name.
Why: carriers show multiple distinct plans under one display name (two Claro "Controle 30GB",
several Vivo "Vivo Controle"); keying by name collapsed them in `latest` and broke per-plan price
history. Source per carrier (native where available): Claro = plan slug; Vivo = offer code (VIV…/SELF…);
TIM = Drupal node id (nid). Fallback = a deterministic name slug if a card lacks a native id.
Rejected: keying by plan_name (collapses distinct plans) or by price (unstable day to day).
Schema bump → CONTEXT v0.3.0.
```

## 5. Tech stack

Python 3.11+ · `playwright` (headless Chromium, JS rendering) · `httpx` (fast plain requests where JS isn't needed) · `selectolax`/`beautifulsoup4` (HTML parsing) · `pandas` + `openpyxl` (Excel) · `pyyaml` (config) · `pytest` (tests). See `requirements.txt`.

### Verified execution environment (2026-06-11, CODE TASK #2)

- **Machine:** Windows 11 Pro (10.0.26200), Python **3.13.13**, venv at `projects/mobile-price-tracker/.venv/`, Playwright **Chromium installed**. Offline pipeline green here (6 tests, demo run, Excel-verified KPIs).
- **Run quirk:** `python -m mobile_tracker.main` fails with `ModuleNotFoundError` unless `PYTHONPATH=src` is set — `pyproject.toml` wires `src/` onto the path **for pytest only**. PowerShell: `$env:PYTHONPATH = "src"` before running. TODO for a future task: `pip install -e .` in CI/local setup, or a runner script, so the env var isn't needed. **⚠️ The CI workflow has this bug today:** its "Run tracker" step calls `python -m mobile_tracker.main` without `PYTHONPATH=src`, so the first Actions run will fail with `ModuleNotFoundError`. Fix before wiring Actions — add `env: PYTHONPATH: src` to that step (or `pip install -e .` in the install step).
- **Demo data ≠ real prices.** `--demo` seeds hardcoded sample plans (only the Vivo *60GB/R$150* figure came from real recon). Real prices arrive only with the live adapters (CODE TASK #3+).
- **Pending one-time auth:** the machine's `gh` token lacks the `workflow` scope, so `.github/workflows/mobile-price-tracker.yml` is untracked locally (pushes containing it are rejected). Before the Actions wiring task: `gh auth refresh -h github.com -s workflow` + Bridge completes the device-code/email check, then commit the workflow file.

#### Current working environment (2026-06-19) — consolidated to ONE machine

- **Bridge clarification (2026-06-19):** there is only **one** working machine — **this** one (user `Rafael`, Windows 11 Pro, **Python 3.13.14**). The machine-#1/#2 "transfer" track is set aside; the two subsections below are kept as **historical record**, not current state. A future PC migration (when Rafael changes computers) will go through GitHub (`git clone`) per the "Backups & machine transfer" bootstrap steps — not folder sync.
- **Env rebuilt + offline smoke test GREEN here, in place (the deferred #2.7 work):** removed the foreign OneDrive-synced `.venv` (the `rafae`/Python-3.12.10 one), created a fresh venv on **Python 3.13.14**, `pip install -r requirements.txt` **completed** (no PyPI/VPN blocker on this machine), `playwright install chromium` done. `pytest` → **6 passed**; `--demo` wrote the 4 sheets; summary KPIs real (vivo R$150 / claro R$64.99 / tim R$30.00). Demo workbook restored (not committed).
- **OneDrive relocation: DEFERRED.** The repo still lives under OneDrive; with a single writer there is no `.git`-collision risk. Moving it out of cloud sync waits for the future PC change.

#### Second machine verified (2026-06-17, CODE TASK #2.5) — historical (superseded by the single-machine consolidation above)

- **Machine:** Windows 11 **Home** Single Language (10.0.26200), Python **3.12.10**, user `rafae`. The project transferred here via **OneDrive sync** (not a fresh `git clone`), so the working copy already includes both `.git` history **and** the untracked `.github/` workflow file.
- **Git verified:** local `HEAD == origin/main == 0f557e4`; `git diff origin/main` shows **no differences** (tracked tree byte-identical to GitHub); ahead/behind `0 0`; only untracked item is `.github/`. The OneDrive-synced workflow file is **byte-identical (SHA256)** to the copy in the sibling `...\Área de Trabalho\CFA\prompt-project-builder\` folder. Workflow file state: **already present (no restore needed).**
- **Minor:** `git fsck` reports one stale reflog entry + dangling objects — harmless residue from OneDrive copying `.git` mid-operation; committed history is intact (clean diff proves it). Optional cleanup: `git reflog expire --expire=now --all; git gc`.
- **⛔ Env NOT rebuilt on this machine yet — network blocker.** The stale OneDrive-synced `.venv` (Python 3.13 from machine #1) was removed; a fresh `python -m venv .venv` (Python 3.12.10) was created, but **`pip install` cannot reach PyPI.** Root cause: an active **McAfee VPN** interface (MTU 1420, InterfaceMetric 5 = prioritized) is an **MTU/PMTUD black hole** — `ping -f -l 1472` to a Fastly IP returns *"Packet needs to be fragmented but DF set"* while a 500-byte ping replies fine. General sites (example.com, github.com) work; Fastly-fronted hosts (pypi.org, files.pythonhosted.org, raw.githubusercontent.com — all `151.101.x.x`) time out on the large TLS response. **Fix (Bridge):** disconnect the McAfee VPN, or clamp the interface MTU, then re-run venv install + `playwright install chromium`. `git`/GitHub are unaffected (github.com is reachable). **pytest + `--demo` smoke test deferred** until deps install.
- **Decision (Bridge, 2026-06-17):** since git verification confirms this copy is identical to GitHub, **continue the project from this machine**; the offline smoke-test re-verification is deferred to whenever the network is sorted (it already passed on machine #1).
- **Cross-checked with machine #1 Code (2026-06-17, via Bridge):** (a) **Drive mirror confirmed intact** — `robocopy` finished and the `.github/` workflow file *is* present in the Drive copy (re-verified on machine #1); (b) **no local-only/gitignored files are needed** — only `.github/` is untracked, no `.env`/`rclone.conf`/credentials anywhere; (c) **`gh` workflow-scope auth is still pending and is per-machine** — machine #2 must run `gh auth refresh -h github.com -s workflow` itself before it can push the workflow file.
- **⚠️ Operational hazard — `.git` is inside the cloud-synced folder.** Both machines sync the same OneDrive directory, which contains `.git`. Machine #1 saw its HEAD change with no git command (OneDrive overwrote `.git`). A cloud-synced `.git` written by two active machines risks **repo corruption / silent divergence** (`…-conflicted copy…` files). **Rule: work on one machine at a time; sync between machines via GitHub `push`/`pull`, never by letting OneDrive/Drive replicate `.git`.** Machine #2 is now the home machine.

### Backups & machine transfer (2026-06-11)

Three copies of the project exist; **GitHub is the source of truth**, the other two are backups:

| Location | Path / URL | Contents | Notes |
|----------|-----------|----------|-------|
| **GitHub** (source of truth) | `https://github.com/rafaelxoliver4-art/prompt-project-builder` | Everything **except** `.github/workflows/*` | The workflow file is **not** pushed (workflow-scope auth still pending — see above). A fresh `git clone` will be missing it. |
| **Google Drive** (mirror) | `G:\Meu Drive\prompt-project-builder` (account `rafaelxoliver4@gmail.com`) | Full repo **including `.git` history AND the `.github/` workflow file**, minus `.venv`/caches | Made via `robocopy /E /XD .venv __pycache__ .pytest_cache`. Refreshed whenever docs change. This is the only copy that has the workflow file in cloud storage. **Confirmed intact by machine #1 on 2026-06-17** (robocopy finished; `.github/` workflow file present in the Drive copy). Not directly inspectable from machine #2 (Google Drive Desktop not installed there — no `DriveFS`/mounted drive), but machine #2 doesn't depend on it (it has the full project via OneDrive). |
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
| `plan_id` | str | **Stable per-plan key**, unique within a carrier, **never price-derived**. Native where available (Claro slug, Vivo offer code, TIM `nid`); else a deterministic name slug. Canonical key for latest/history/changes (§4 decision). |
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

> **BACKLOG (deferred, per §10.1 — presentation comes AFTER data correctness & coverage):** the interim function-sheets stay until the pipeline is proven across all three carriers. **Data quality first, presentation second.** Deferred product items (Bridge, 2026-06-19):
> 1. **Per-operator organization** — *built:* the cross-operator **comparison** sheet (#9) **and** the per-carrier **single-sheets** (#10 — one tab per carrier, grouped by category + price-sorted; see "Per-operator sheets" below).
> 2. **PROMOTIONS view/sheet** — track promo-vs-regular price over time (we already capture `price_promo_brl` + `price_note`; surface the spread and its history).
> 3. **DASHBOARD** — an attractive, formatted sheet (charts, headline KPIs, buttons/filters).
>
> **Open data-quality items:**
> - **Claro prepaid parser** — *done (#7):* Prezão headline captured (R$1/dia, 12GB). Deeper Pré recarga-tier breakdown + the "Outras ofertas Pré" tab remain **best-effort / deferred**.
> - **Plan-name uniqueness** — *resolved (#6):* stable `plan_id` adopted (carrier-native; §4 decision); `latest` no longer collapses same-named plans.
> - **Promo coverage** — *wired for all three carriers (#7);* few promos are live now, so coverage is low — revisit if a campaign adds many.
> - **TIM "Pro Express" data_gb** — left null (allowance absent from structured fields, §3); revisit if TIM exposes it.

> **Comparison methodology — IMPLEMENTED (#9, 2026-06-22):** the **`comparison`** sheet compares like-for-like WITHIN each category, aligned by **price rank**. Groups → `category`: **Pure Postpaid**=`postpaid`, **Control / Hybrid**=`control`, **Prepaid**=`prepaid`, **Digital**={`lite`,`flex`} (Vivo Lite + Claro Flex; TIM none). Each carrier's plans are sorted ascending by `price_brl`, then aligned across carriers by rank (cheapest-vs-cheapest, 2nd-vs-2nd, …); `price_promo_brl` is shown alongside when present (**not** re-ranked by it). Layout per group: a bold title, an optional caveat note, then `Rank | Vivo R$ | Claro R$ | TIM R$ | Vivo plan | Claro plan | TIM plan` (the three R$ columns adjacent so a row compares across carriers; plan cells include GB). **Caveats printed in the sheet:** prepaid isn't a clean unit (Claro Prezão is a daily fee R$1/dia vs Vivo/TIM recharge amounts); Digital = Vivo Lite + Claro Flex (TIM none). Rebuilt from the **latest snapshot** every run (`build_comparison_data` + `_write_comparison` in `excel_writer.py`). First cut — expect layout iteration from Bridge review.

> **Per-operator sheets — IMPLEMENTED (#10, 2026-06-22):** one sheet per carrier present in the latest snapshot (name = display name **Vivo / Claro / TIM**; scales as carriers are added — absent carriers get no sheet). Within each: plans **grouped by category** in order **Postpaid → Control → Digital ({lite,flex}) → Prepaid** (bold sub-header per block), sorted ascending by `price_brl`. Readable column set: **Plan | Price R$ | Promo R$ | Data | Voice | Unlimited apps | Streaming | Notes** (Data = `data_gb` + `data_note`; Notes = `extra_benefits` + `price_note`; internal `plan_id` omitted; blank where null). `build_operator_sheets` + `_write_operator_sheets` in `excel_writer.py`, wired after the comparison sheet; rebuilt from the latest snapshot every run. First cut — expect iteration.

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
- **0.3.3 — 2026-06-22** — CODE TASK #10: built the **per-operator sheets** (one tab per carrier — Vivo/Claro/TIM — present in the latest snapshot). Each groups plans by category (Postpaid → Control → Digital → Prepaid), price-sorted, with a readable column set (Plan / Price / Promo / Data / Voice / Unlimited apps / Streaming / Notes). `build_operator_sheets` + `_write_operator_sheets` in `excel_writer.py`, wired after the comparison sheet; the five prior sheets untouched (8 total). §7 per-operator item moved backlog → implemented. Tests 35 → 40.
- **0.3.2 — 2026-06-22** — CODE TASK #9: built the cross-operator **`comparison`** sheet (§7 methodology now implemented, moved from parking-lot). Four groups (Pure Postpaid / Control-Hybrid / Prepaid / Digital), each rank-aligned across Vivo/Claro/TIM by ascending `price_brl`, with the prepaid-unit + Digital caveats printed in-sheet. `excel_writer.py`: `build_comparison_data` (pure) + `_write_comparison`, wired after `latest`; history/latest/changes/summary untouched. Tests 30 → 35.
- **0.3.1 — 2026-06-22** — CODE TASK #7 (data-quality gaps before launch): **Vivo prepaid** now keeps all 4 recharge tiers (they share one offer code → `plan_id` disambiguated by data allowance); **Claro prepaid** parser added (`parse_claro_prepaid` over the `tab_select` Prezão tabs); **promo prices** wired for all three carriers (Claro prefix / Vivo `price-old` / TIM `tracejado`); TIM "Pro Express" `data_gb` left null + documented. §3 records the prepaid structures + promo locations; §7 updated. Tests 27 → 30.
- **0.3.0 — 2026-06-19** — CODE TASK #6 (schema change, Bridge-approved): added **`plan_id`** to the Plan schema (§6) and as the canonical key. §4 `[DECISION]` adopts (carrier, state, plan_id) for latest/history/changes (never price-derived). §3 documents per-carrier derivation: Claro slug, Vivo offer code (VIV…/SELF…), TIM Drupal `nid` (native), name-slug fallback. `excel_writer` re-keyed → duplicate-named plans (two Claro "Controle 30GB", two Vivo "Vivo Controle") now stay distinct in `latest`. Minor-version bump for the schema change.
- **0.2.9 — 2026-06-19** — CODE TASK #5: TIM adapter (third/last stack — all three carriers now live). Added §3 "TIM — live structure verified": server-rendered Drupal, plain `httpx`; plans come from the embedded `drupal-settings-json` → `settings["ofertas"][]` (`field_preco_card_oferta` price + `title` name) — **SVG-price concern resolved, no OCR needed**; 15 live SP plans (control 5 / Black 7 / Pré 3), no Playwright. Parked the Bridge's cross-operator **comparison methodology** (within-category, by price rank) in §7.
- **0.2.8 — 2026-06-19** — CODE TASK #4: Vivo adapter (second live carrier). Added §3 "Vivo — live structure verified": `httpx` 403 / `.model.json` 403 → **Playwright** + `.unique-card` DOM scrape (selectors documented); 24 live SP plans across all four categories (postpaid 7 / control 8 / lite 5 / prepaid 4). Extended the §7 BACKLOG with three deferred product items (per-operator + cross-operator comparison, promotions view, dashboard) under a "data correctness & coverage first" rule, and logged two open data-quality items (Claro-prepaid parser; plan-name uniqueness → stable `plan_id`, a schema change needing Bridge YES).
- **0.2.7 — 2026-06-19** — CODE TASK #3: Claro adapter implemented (first live data). Added §3 "Claro — live structure verified": the `__NEXT_DATA__` → `card_360` JSON path, the two price formats (postpaid `R$ x`; control/flex bare value + struck-through `prefix` → regular/promo), slug-derived names, no-Playwright, and that prepaid uses a different (non-`card_360`) layout → deferred. 13 live SP plans (postpaid 5 / control 4 / flex 4). Editable install (`pip install -e .`) removes the `PYTHONPATH=src` quirk + the CI "Run tracker" bug.
- **0.2.6 — 2026-06-19** — Bridge clarified there is only ONE working machine (this one — `Rafael`, Python 3.13.14). Added §5 "Current working environment": the deferred env rebuild was completed here in place (foreign 3.12.10 venv removed, fresh 3.13.14 venv, `pip install` completed, **6 tests pass**, `--demo` KPIs real); OneDrive relocation deferred to the future PC change. Marked the "Second machine verified" + machine-#1/#2 sections as historical.
- **0.2.5 — 2026-06-17** — Cross-checked the transfer with the still-running machine #1 Code instance (via Bridge). Confirmed in §5: Drive mirror **intact** (robocopy finished, workflow file present); **no local-only/gitignored files needed** (no `.env`/`rclone.conf`/credentials); `gh` workflow-scope auth **still pending and per-machine**. Recorded two new items: the **`.git`-inside-cloud-sync hazard** (both machines syncing the same OneDrive `.git` → corruption/divergence risk; sync via GitHub, not OneDrive) and the **CI workflow `PYTHONPATH=src` bug** ("Run tracker" step will `ModuleNotFoundError` on first Actions run).
- **0.2.4 — 2026-06-17** — CODE TASK #2.5 (transfer verification on machine #2). Added §5 "Second machine verified": Windows 11 Home / Python 3.12.10, git verified identical to GitHub (`0f557e4`, clean diff), workflow file already present via OneDrive sync. Recorded the **McAfee VPN MTU black-hole** blocking PyPI (env rebuild + smoke test deferred), the Google-Drive-not-installed-here caveat, and the Bridge decision to continue from this machine.
- **0.2.3 — 2026-06-11** — Added §5 "Backups & machine transfer": three-copy map (GitHub = source of truth; Google Drive `G:\Meu Drive\prompt-project-builder` = full mirror incl. `.git` + the unpushed `.github/` workflow; OneDrive = working copy) and a 4-step new-machine bootstrap. Prompted by Rafael transferring to another computer.
- **0.2.2 — 2026-06-11** — Bridge standing rule added to the header: every CODE TASK ends by updating CONTEXT + PROGRESS, committed + pushed (new sessions bootstrap from these files). Mirrors INSTRUCTIONS v1.2.0 §2.1.
- **0.2.1 — 2026-06-11** — Code added §5 "Verified execution environment" after CODE TASK #2: Windows 11 / Python 3.13.13 machine verified, `PYTHONPATH=src` run quirk + `pip install -e .` TODO, demo-data-is-not-real-prices clarification, pending `workflow`-scope auth for the Actions file.
- **0.2.0 — 2026-06-11** — Bridge resolved all four open questions (§10): interim function-sheets with per-carrier + dashboard layout deferred to backlog; **full-detail** capture (expand modals → Playwright-favored); **rclone-in-Actions** chosen for the Drive mirror; keep all history. Recorded interaction/runtime implications in §8.
- **0.1.0 — 2026-06-11** — Project defined; reconnaissance on all three carrier stacks; architecture, schema, Excel layout, decisions, risks, and glossary recorded.
