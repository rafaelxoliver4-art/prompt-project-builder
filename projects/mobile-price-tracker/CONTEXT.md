# CONTEXT — Mobile Price Tracker

> **Version:** 0.2.0 · **Last updated:** 2026-06-11 · Maintained by the Architect.
> The *what / how / why* of this project and every decision behind it. This is the knowledge base and
> IP. If someone read only this file, they should understand the project well enough to rebuild it.

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
- **0.2.0 — 2026-06-11** — Bridge resolved all four open questions (§10): interim function-sheets with per-carrier + dashboard layout deferred to backlog; **full-detail** capture (expand modals → Playwright-favored); **rclone-in-Actions** chosen for the Drive mirror; keep all history. Recorded interaction/runtime implications in §8.
- **0.1.0 — 2026-06-11** — Project defined; reconnaissance on all three carrier stacks; architecture, schema, Excel layout, decisions, risks, and glossary recorded.
