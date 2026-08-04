# CONTEXT — Mobile Price Tracker

> **Version:** 0.9.0 · **Last updated:** 2026-08-04 · Content decided by the Architect; written by Code.
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
- **Cadence:** once per day at **18:00 BRT** (`0 21 * * *` UTC). **Live via GitHub Actions since 2026-06-22** — see §5.
- **Output:** one Excel workbook, mirrored to GitHub + Google Drive.
- **Alerting:** after each run, the job **emails a digest of any plan whose price moved ≥3%** (up or down) vs the previous snapshot (see §5).

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
- **Claro prepaid** (Prezão, `/planos-pre/prezao`): **NOT `card_360`** — the Prezão offer lives in a **`tab_select`** component (tabs "Prezão R$1 por dia", "Prezão com anúncio"), marketing-style with no clean price field. `parse_claro_prepaid` originally read the tab **title** for the daily price ("R$1 por dia"). **⚠️ SUPERSEDED by #18 (see below):** the "R$1/dia" was the per-day framing, not a 30-day plan — `parse_claro_prepaid` now captures the real recarga tiers + validity from the page's rich text instead.
- **Promo prices** (`price_promo_brl` + `price_note`) where the site shows a regular-vs-effective pair:
  - **Claro** → struck-through regular in `actions[0].price.prefix` ("~De R$ 59,90~ Por:") — already captured.
  - **Vivo** → struck-through original in `.unique-card__price-old` (hidden when no promo).
  - **TIM** → `field_preco_adicional_tracejado` (struck regular; empty when no promo).
  Coverage reflects what each site currently displays (few promos are live now); the mechanism populates automatically when a promo appears.
- **TIM "Controle Pro Express" `data_gb`**: its allowance is **not in the structured `ofertas` fields** (only a "500 MEGA" bonus highlight, which isn't the plan allowance) and the title has no GB token → `data_gb` left **null** (documented; we don't infer a misleading value).

### Prepaid 30-day plans + `validity_days` (2026-06-26, CODE TASK #18) ← valuable IP

The prepaid capture now records the real **30-day plan + each plan's validity in days** (`validity_days`, schema §6), so the Pre column reflects a true monthly prepaid plan instead of the R$1/day headline. Verified by a **live re-scrape** (2026-06-26) — per carrier:

- **Claro (`__NEXT_DATA__` rich text):** the old parser grabbed "Prezão R$1 por dia" (R$1) — that's R$30 ÷ 30, NOT a plan. The real recarga tiers are described in the page's **rich text** as `"R$ <recarga>/<validity> dias – <gb>GB"` (e.g. **`R$ 30/30 dias – 12GB`** — the 30-day plan). `parse_claro_prepaid` regexes these (dash-separated, so an adjacent GB token can't bleed in), keyed by **`claro:prezao-<days>d-<gb>gb`** (validity+gb, never price-derived §4); on a (validity, gb) collision (e.g. R$30 vs R$35 both 30d/12GB — com/sem anúncio) it keeps the cheaper. Live result: **7 tiers, 12d→30d; the 30-day = R$30/12GB** (was R$1).
- **Vivo (Playwright DOM):** each `.unique-card` text carries its recarga validity (`"30 dias"`). Extracted (gated on `category == "prepaid"`) per tier: **R$30/25GB/30d, R$25/9GB/22d, R$20/5GB/17d, R$17/4GB/15d**. The 30-day = R$30.
- **TIM (`drupal-settings-json`):** there is **no clean structured validity field** — the period is in the oferta's benefits-modal HTML (`field_layout_canvas_segundo`). `validity_days` = the **MAX "N dias"** in the oferta. ⚠️ **WRONG — corrected by the #22 audit (see below):** a shared marketing line (*"…recarga de R$30 válidos por 30 dias"*) appears in **every** oferta, so MAX picked 30 for all three. The **true** validities are **R$20/6GB → 17d, R$25/8GB → 22d, R$30/16GB → 30d** (from each oferta's own *"…R$&lt;price&gt;, válido por &lt;N&gt; dias"*). So the cheapest 30-day TIM prepaid is **R$30**, not R$20 — the Pre column has been wrong since #18. ✅ **FIXED in #23** (per-oferta parsing → 17/22/30; Pre TIM now R$30 — see the #23 subsection below).
- **Matrix Pre column** = cheapest prepaid plan with `validity_days >= 28` (config `prepaid.min_validity_days`, mirrored in `excel_writer.PREPAID_MIN_VALIDITY_DAYS`), as a live `MINIFS` adding one criterion (`history!<validity_col>,">=28"`). Live Pre row (Jun-26): TIM 20 / Vivo 30 / Claro 30 (R$/mo). ⚠️ **The "TIM 20" was WRONG (R$20 is a 17-day plan) — ✅ FIXED in #23: the true 30-day TIM is R$30, and the live Pre row is now TIM 30 / Vivo 30 / Claro 30.** Displayed as **monthly R$/mo** (default); the avg-R$/day form (JPMorgan-style = price ÷ validity) is a one-line switch if the Bridge prefers it.
- **Schema-order fix (#18):** merging a pre-#18 history (no `validity_days` column) with new rows pushed the column to the END via `pd.concat`, so the matrix's column-letter formula (`history!$M:$M`) pointed at the wrong column and the Pre cell read blank. `_merge_history` now **reindexes to `COLUMNS`** so the schema order is always enforced.

### Source-of-truth audit (2026-07-01, CODE TASK #22) ← valuable IP · full note: `docs/source_audit_2026-07.md`

Live SP fetch of all three carriers, compared field-by-field to what the adapters parse. **All three sources confirmed São Paulo:** Claro `__NEXT_DATA__` `SEGMENTATION_DEFAULT.uf="SP"` (name "São Paulo", ddd 11, cityChangedByUser=false); Vivo active-city label **"São Paulo (SP)"**; TIM `/sp/` URL path. **Confirmed correct:** postpaid cheapest **TIM R$119,99 < Claro R$124,90 < Vivo R$150**; Claro Control effective **R$54,90** (regular 59,90, both captured); Claro Prezão 30-day **R$30/12GB**; Vivo control/postpaid/prepaid; TIM control effective + postpaid. **Two MISMATCHES found — both ✅ FIXED in #23 (see the subsection below):**
- **TIM prepaid validity** — true 17d/22d/30d, we had captured all-30d → the Pre column showed TIM R$20 (a 17-day plan) instead of the real 30-day R$30. **Fixed (#23): per-oferta parsing; Pre TIM = R$30.**
- **Vivo Lite loyalty** — Easy Lite has a subscription toggle **"Plano anual" (12-mo loyalty) R$30** vs **"Plano mensal / Sem fidelidade" ≈R$45**. We had captured the **annual (loyalty)** price; the no-commitment is toggle-gated. **Fixed (#23): render clicks "Sem fidelidade"; headline = no-commitment (R$35/45/55), loyalty kept as promo.**

Minor: TIM control shows a list price `field_preco_adicional_original` (R$63,99…) above the captured effective (58,99…, "Desconto Extra R$5") — we capture the effective only.

### Both audit mismatches FIXED (2026-07-01, CODE TASK #23) ← valuable IP

- **TIM prepaid validity — per-oferta now (`tim.py` `_prepaid_validity`):** parse THIS oferta's own `"R$<recarga> … (por | válido[s] por) <N> dias"` (match the pair whose recarga = the oferta's `field_preco_card_oferta`), NOT the max "N dias" (the #18 bug — a shared *"recarga de R$30 válidos por 30 dias"* line inflated all to 30). **Live-verified: R$20/6GB→17d, R$25/8GB→22d, R$30/16GB→30d.** → the **matrix Pre for TIM is now R$30** (the true cheapest 30-day), was R$20. Self-heals going forward (old snapshots keep the wrong 30d; from this run on they're correct).
- **Vivo Lite non-commitment price (`vivo.py`):** Easy Lite has an annual/monthly toggle. `_render` now clicks each card's **"Sem fidelidade"** toggle for the `lite` target (only lite), so `.total-card-price-value` text = the **no-commitment monthly** and `data-original-price` keeps the **12-month loyalty** price. `parse_vivo_html` (lite branch) records `price_brl` = no-commitment, `price_promo_brl` = loyalty, `loyalty_months=12`. Cards without the toggle stay single-price. **Live-verified: R$45/30GB (loyalty 30), R$55/40GB (loyalty 40), R$35/20GB (single-price).**
- **⚠️ Digital column nuance:** the absolute cheapest no-commitment Easy Lite is **R$35** (the 20GB "Plano mensal" card, which has NO annual option). #23 made the Digital column show R$35. ✅ **REFINED in #26 (Bridge's call):** the 20GB is a monthly-ONLY entry tier — the *representative* entry-level is the cheapest plan that actually offers a **"Sem fidelidade"** choice (a toggle card, `loyalty_months` set), i.e. the **30GB at R$45**. So the Digital Vivo pick now requires `loyalty_months > 0` → **R$45** (excludes the 20GB R$35). All three tiers still show in `history`/the Vivo sheet. (Claro Flex cheapest = R$44,90, unaffected.)
- Other categories/carriers untouched (gated on category); the matrix formulas + #21 cached-value bake are unchanged (the bake regenerates over the corrected numbers).

### TIM postpaid: exclude the credit-card-only plan (2026-07-01, CODE TASK #24) ← valuable IP

- **Finding (live SP, 2026-07-01):** TIM postpaid prices each plan **by payment method**. The reliable discriminator is the oferta's **`field_preco_principal_7_1_3`** HTML headline: `R$ <price>/mês **no cartão**` (recurring **credit card**) vs `R$ <price>/mês **na fatura**` (paid on the **invoice/bill**). `field_formas_de_pagamento` is empty (`[]`) — useless. The two phrases are **mutually exclusive within that field** (verified — zero co-occurrence across the 7 SP plans), so classification is reliable. `_payment_method` **anchors to the `/mês <phrase>` price headline** (not a bare "no cartão" match) so stray card/fatura words in the benefits/promo HTML can't flip it — a bill plan must never be misread as credit-card (that would wrongly drop it from the pick). The 3 "**Express**" plans are credit-card, the 4 non-Express are bill (the name marker aligns, but we key off the explicit text, not the name).
  - **credit_card ("no cartão"):** Black A Express 67GB **R$119,99**, B Express 82GB R$144,99, C Express 107GB R$164,99.
  - **bill ("na fatura"):** **Black 70GB R$129,99**, Plus 80GB R$149,99, C Ultra 95GB R$159,99, Premium 110GB R$159,99.
- **JPMorgan rule:** TIM's cheapest postpaid (A Express R$119,99) **requires a recurring credit card** and has low adoption, so the entry-level comparison uses the cheapest **bill-payment** plan = **TIM Black 70GB R$129,99**.
- **Schema:** new **`payment_method`** field (§6) — `"credit_card" | "bill" | None`; populated for **TIM postpaid only** (gated on `category`), `None` elsewhere (other carriers/categories). Added to `COLUMNS` in order; `_merge_history` reindex gives pre-#24 rows a **blank** value (the #18 pattern).
- **Matrix Post exclusion (formula-driven):** the Post column's per-carrier `MINIFS` gains one criterion — `history!<payment_method>,"<>credit_card"` — so it ignores credit-card-only plans. Applied to the **postpaid group only** (Control/Pre/Digital carry no payment criterion). **⚠️ Excel `"<>credit_card"` INCLUDES blank cells** (empty ≠ credit_card — *verified by an actual Excel COM recalc:* hist-all-blank → 119.99, `COUNTIFS` → 2, mixed → 135). So carriers **without** a credit-card tag (Vivo/Claro — blank `payment_method`) are **unaffected**, and pre-#24 history **self-heals** (blank → included → keeps its old cheapest; freshly-scraped rows exclude the credit-card plan). The #21 cached-value bake (`_matrix_value`) mirrors this exactly (drops `payment_method=="credit_card"`, keeps blanks, case-insensitive) so **bake == live formula**.
- **Scope:** **all plans stay in `history`, `latest`, and the per-operator sheets** — only the entry-level/matrix Post pick excludes credit-card-only. Result: matrix **Post row for TIM = R$129,99** (was R$119,99). Self-heals forward like #18/#23 (historical rows keep R$119,99 until re-scraped).
- **Surfaced in-sheet (#25):** the `comparison` sheet now carries a footnote stating this (TIM Post = bill-payment R$129,99, not the R$119,99 credit-card-only plan, JPMorgan low-adoption rule) so a reader understands the entry-level pick without digging into the code (§7).
- ⚠️ **REVERSED in #27 (Bridge, 2026-07-03):** the Post pick is back to the **plain cheapest** postpaid plan — **TIM R$119,99 (credit-card) included** — because the Bridge wants to *track that price and be alerted when it changes* (the `changes` sheet + the #15 alert watch `tim:55121`). Everything ELSE from #24 stands: the `payment_method` field, the tim.py tagging, the "no cartão"/"na fatura" identification — the billing type remains recorded per plan and flagged in the rewritten footnote; only the `"<>credit_card"` matrix criterion (and its bake mirror) was removed.

### TIM Controle Fit — TIM's digital line (2026-07-13, CODE TASK #28) ← valuable IP

- **What it is:** TIM launched **"TIM Controle Fit"** — the Digital peer of Vivo Easy Lite / Claro Flex (the Bridge asked for it by name). Two versions, live SP: **Anual** = 30GB, **12x R$30/mês no cartão de crédito**, **com prazo de permanência (12m)**; **Mensal** = 20GB, **R$35/mês**, **sem prazo de permanência**. (Same shape as Vivo Lite: cheap annual-with-loyalty vs monthly no-commitment.)
- **Where it lives (the recon surprise):** NOT on its own page and **NOT in the drupal-settings `ofertas` JSON** (0 fit entries there). It is a **server-rendered marketing section ON the controle page** (anchor `id="price-fit"`, reachable via `…/planos/controle#price-fit`) — plain text like *"Tenha 30GB por 12x R$30/mês"* in two `tim-tab` blocks. So a plain httpx GET has it; no Playwright needed.
- **plan_id:** each version's benefits **modal** (`id="modal-fit-anual"/"modal-fit-mensal"`) links its **etiqueta PDF** with a **stable offer code** — *"Etiqueta padrão - TIM202600000271"* (anual) / *"TIM202600000270"* (mensal). These are the plan_ids (`tim:TIM2026…`) — carrier-native, non-price-derived, and they **survive nid rotations** (below).
- **Parsing:** `parse_tim_fit_html` (tim.py) — slices from `id="price-fit"`, selectolax text + anchored regex (`Plano anual … Tenha <N>GB por 12x R$<p>/mês`; mensal without `12x`), codes from each modal's slice. Routed from `parse_tim_html` when `target.category == "fit"`; config adds the `fit` category on the SAME controle URL (one extra polite fetch/day; raw saved as `tim_fit_SP.html`). Section absent → `[]` (daily counts flag it), never a crash.
- **Entry-level rule (mirrors #26):** the two versions are SEPARATE plans; the **Anual's own price requires loyalty** → tagged `loyalty_months=12` + `payment_method="credit_card"` and **excluded from the Digital pick**; the **Mensal (loyalty blank) = the entry → Digital TIM = R$35**. Both stay in history/the TIM sheet.

### TIM rotates ALL Drupal nids — the missed-alert root cause (2026-07-06 → fixed 2026-07-13, CODE TASK #29) ← valuable IP

- **Finding:** on **2026-07-06** TIM **republished every Controle plan under a fresh Drupal nid** (e.g. 41GB: `tim:162901` → `tim:167036`) **while cutting prices** (41GB 58,99 → **49,99** −15.3%; Premium 84,99 → **69,99** −17.6%; Plus 64,99 → 59,99 −7.7%). Because `changes`/alerts matched **by plan_id only**, the cuts surfaced as 5 `removed` + 5 `new` rows — **no `price_change`, no e-mail** (the Bridge noticed the silence). nids are **content-management ids, not offer identities** — TIM can rotate them on any republish.
- **Fix (#29), mirrored in BOTH `_compute_changes` (excel_writer.py) and `compute_price_alerts` (alerts.py):** after id-matching, the **id-unmatched** removed/new rows are re-paired by **(carrier, state, category, plan_name)** — names survive rotations — **ONLY when the name maps 1:1 on both unmatched sides** (any ambiguity → keep honest `new`/`removed`, never a guessed alert). A re-paired pair with a **price move → `price_change`** (reported under the NEW id, so the e-mail fires); **same price → silent** (a pure re-key is not a change). Id-first matching is unchanged — an intact id always wins and is never re-paired.
- **History is untouched** by rotations (append-only; both ids exist across days). Only the **diff views** (changes sheet + alert) pair across them. The matrix was never affected (it MINIFSes by category, not id).

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
- **Run quirk — RESOLVED (2026-06-22):** `python -m mobile_tracker.main` used to need `PYTHONPATH=src` (`pyproject.toml` wired `src/` for pytest only). **Fixed by `pip install -e .`** (editable install) — the local venv *and* the CI workflow now run `python -m mobile_tracker.main` with **no `PYTHONPATH`**. (The CI "Run tracker" bug this once warned about is fixed in the live workflow.)
- **Demo data ≠ real prices.** `--demo` seeds hardcoded sample plans (only the Vivo *60GB/R$150* figure came from real recon). Real prices arrive only with the live adapters (CODE TASK #3+).
- **`gh` `workflow` scope — DONE (2026-06-22):** the Bridge authorized it via `gh auth refresh -h github.com -s workflow` (device-code). The workflow file is **pushed and live on GitHub**; token scopes now `gist, read:org, repo, workflow`.

#### Daily Actions job — LIVE (2026-06-22, CODE TASK #8)

- **Scheduler is ON.** `.github/workflows/mobile-price-tracker.yml` runs **daily at 18:00 BRT** (`cron: 0 21 * * *` UTC) + on-demand (`workflow_dispatch`, default `mode: live`). Each run: `pip install -r requirements.txt && pip install -e .`, `playwright install --with-deps chromium`, offline `pytest`, `python -m mobile_tracker.main` (all three), then commits the refreshed `data/mobile_plans.xlsx` back to the repo (`permissions: contents: write`). **The workbook is styled in code (§7 house style, #11), so the committed copy picks up the visual polish automatically from the next daily run.** **GOVERNANCE §6:** `main.py` exits non-zero if any carrier yields zero plans → the job fails → **no commit** (no fake/partial snapshot).
- **Committed history has BEGUN.** Synthetic seed cleared (`25f0da6`); first **real** snapshot landed via the runner on **2026-06-22** (`b5ca0a0`): **52 collected / 51 in latest**, full 8-sheet workbook.
- **CI-IP-block risk did NOT materialize:** all three carriers — including **Vivo via headless Playwright** — scraped cleanly from GitHub's datacenter runner. (Re-check on future runs; if a carrier gets challenged from CI, the job alerts and we'd consider a self-hosted runner — never evade.)
- **Weekly backup wired:** on Mondays (UTC) the daily job copies the workbook to `backups/mobile_plans_<date>.xlsx` and commits it (dated, never overwritten). First: `mobile_plans_2026-06-22.xlsx` (`6bc51f4`).
- **Working-copy note:** `data/mobile_plans.xlsx` is now **owned by the daily job**. Don't hand-commit local review-run changes to it — `git checkout` it (or let the job own it); `git pull` before working to get the latest committed snapshot.
- **The daily job also runs a GUARDED CONVERGENT scrape (#31, §14).** After the mobile pass, `main.run()` scrapes the active `convergent:` sources (TIM Ultracombo today) into the `convergent_history` sheet. It is wrapped so that **any** convergent failure is logged and skipped — it can never block the mobile scrape, the workbook write, or the commit (and `--demo` skips it entirely). A convergent problem is therefore a *silent no-op for the mobile snapshot*, by design.
- **Drive mirror:** still a fast-follow (GOVERNANCE §5) — an `rclone` step is stubbed (commented) in the workflow, pending a Bridge YES + an `RCLONE_CONFIG` secret.

#### Committed workbook DISPLAYS its values in any viewer (2026-06-30, CODE TASK #21) ← valuable IP

- **Problem:** openpyxl writes formula cells as `<f>…</f>` with **NO cached `<v>` value**. So the committed workbook (comparison matrix + summary — all live MINIFS) showed **BLANK in any viewer that doesn't recalc** — GitHub preview, Google Sheets, Numbers, mobile, Excel Protected View. Confirmed on `origin/main`: `data_only=True` → 108 matrix + 12 summary formula cells, **0 cached values**. (Desktop Excel recalcs on open via `fullCalcOnLoad=1`, masking it there.)
- **Fix — cached-value BAKE (in `write_workbook`, so the daily job produces it automatically; NO workflow change):** after openpyxl saves, `_bake_cached_values(path, {...})` sets a `<v>value</v>` on each matrix + summary formula cell (keeping the `<f>`). Values are computed in Python by `_matrix_value` / `_write_summary` with the **same logic as the formulas** (cheapest per carrier/category/date; Pre validity≥28; digital min; summary count/min/avg/max over `latest`). Result: `data_only=True` now shows the values (displays everywhere) **and** the live formulas remain (`data_only=False` shows MINIFS; Excel still recalcs on open, so any drift self-corrects). No-offer cells (Pre pre-#18, TIM Digital) have no value → correctly stay blank.
- **⚠️ openpyxl 3.1.x serialization gotcha (found by adversarial review):** openpyxl **3.1.x writes a formula cell as `<f>…</f>` + an EMPTY value placeholder** — `<v/>` (lxml build) OR `<v></v>` (stdlib etree build) — NOT bare `<f>`. `_inject_cached_values` must therefore **drop the empty placeholder and write one `<v>`** (a naive "skip if `<v>` present" bakes 0 cells / a "just append" makes a duplicate `<v>` → invalid). It handles all shapes (`<v/>`, `<v></v>`, no `<v>`, real value = idempotent) — a **surgical per-cell string edit** (no XML re-serialization → charts/CF/formatting byte-identical). **Fail-loud guard:** `write_workbook` compares baked-count vs expected and **raises** on a 0/partial bake, so a future openpyxl change that defeats the injector fails the run (no blank commit) instead of silently shipping one. (`requirements.txt` pins `openpyxl>=3.1` unbounded — the guard is the safety net; pinning is optional belt-and-suspenders.)
- **Why NOT LibreOffice recalc (the Architect's first suggestion):** LibreOffice isn't installed locally (can't test-first) and its xlsx round-trip re-exports the **5 charts + conditional formatting + merged cells**, risking mangling (the task's STOP condition). The Python bake is **surgical** — a per-cell string insert that rewrites ONLY the `comparison`/`summary` sheet XMLs; every other zip part (charts, drawings, CF, tab colors) passes through **byte-identical**. It's fully testable locally, CI-native (no extra install), and deterministic. This is the task's sanctioned fallback ("compute values in Python and bake them as cached values while keeping the formulas").
- **Verified:** regenerated from committed history → `data_only=True` shows **87/108** matrix values (21 correctly-blank no-offer cells) incl. Control 22-Jun = 58.99/59/59.9, summary KPIs; `data_only=False` still shows the MINIFS formulas; 5 charts + 10 sheets intact; all 79 tests (incl. chart/heatmap/layout) pass on baked output. Values match Excel's recalc (verified via COM on this history in #19/#20).

#### Production-readiness verified (2026-06-22, CODE TASK #14)

Audited (not assumed) that the daily job will fire correctly from **`origin/main`** — **all checks PASS**:
- **Sync:** tree clean; `HEAD == origin/main`; no unpushed commits (the run uses the current code).
- **Workflow on `origin/main`:** cron `0 21 * * *` (18:00 BRT), `workflow_dispatch`, `permissions: contents: write`, `pip install -e .` + `playwright install --with-deps chromium`, `python -m mobile_tracker.main` (no `PYTHONPATH`), commit-back, weekly-Monday backup; the rclone/Drive step is **commented** (can't fail the run). Default branch = **`main`** (cron fires from it).
- **Enabled:** workflow **active** (id `300305398`).
- **Code current:** 52 tests pass; `pyproject` editable-install config present; the matrix/chart/operator/Ranking code is on `origin/main` → the run produces the current styled matrix+charts workbook.
- **End-to-end proof:** a manual `workflow_dispatch` **succeeded** (2m29s) — scraped **all three** carriers (claro 14 / tim 15 / vivo 23 = **52**), **no block/CAPTCHA/zero**; committed **51 in latest, 1 snapshot** (idempotent replace confirmed *on the runner*); pulled workbook has 9 sheets (matrix + 4 charts + Ranking + per-operator), styling applied, history not duplicated.
- **Bottom line:** **the cron will fire at 18:00 BRT (21:00 UTC) today** from `main` — workflow enabled, latest code live, idempotent.
- **Open item:** no live-output *sanity* check yet beyond the zero-guard — a carrier returning *implausible* counts/ranges (but non-zero) wouldn't be flagged. A range/sanity guard is possible future hardening.

#### Price-change email alert — added (2026-06-22, CODE TASK #15)

After each live run, the job emails **rafaelxoliver4@gmail.com** (from **ibotatom@gmail.com**) a **digest of any plan whose headline `price_brl` moved ≥ 3%** (up OR down) vs the previous snapshot — matched by `(carrier, state, plan_id)`, the same identity the `changes` sheet uses (so they agree). New/removed plans are **not** price-move alerts.
- **Credential — secret only:** the SMTP app-password is read ONLY from the **`EMAIL_APP_PASSWORD`** env var (a **GitHub Actions Secret**) — never in code, config, or commits. The workflow passes `EMAIL_APP_PASSWORD: ${{ secrets.EMAIL_APP_PASSWORD }}` to the "Run tracker" step. Addresses + threshold live in `config/sources.yaml` (`alerts:` — non-secret).
- **Send:** `smtplib` over STARTTLS (`smtp.gmail.com:587`); ONE digest if ≥1 alert, nothing if zero. Subject `"… N price change(s) ≥3% — <date>"`; one body line per plan, sorted by |%| desc.
- **Robust — never blocks the job:** missing/empty password → log + skip; any SMTP error → caught + logged; the whole step is wrapped so it can't fail the scrape or the data commit (**collection > notification**).
- **Code:** `mobile_tracker/alerts.py` (`compute_price_alerts` + `format_alert_email` pure; `send_alert_email` + `alerts_from_workbook` guarded), wired into `main.py` after `write_workbook` (live only).
- **First fire = next run:** needs ≥2 snapshots, so the first alert compares the next run to today's.
- **Pre-req (Bridge):** add the `EMAIL_APP_PASSWORD` secret (a Gmail app password for ibotatom@gmail.com) in repo → Settings → Secrets and variables → Actions. Until it's set, the alert step skips gracefully (scrape + commit still run).

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
| `category` | str | `postpaid` / `control` / `prepaid` / `lite` / `flex` / `fit` (TIM Controle Fit, #28). |
| `state` | str | `SP` for now. |
| `plan_name` | str | As shown on site (pt-BR). |
| `plan_id` | str | **Stable per-plan key**, unique within a carrier, **never price-derived**. Native where available (Claro slug, Vivo offer code, TIM `nid`); else a deterministic name slug. Canonical key for latest/history/changes (§4 decision). |
| `price_brl` | float | Headline monthly price, R$. |
| `price_promo_brl` | float? | Promo price if distinct from regular. |
| `price_note` | str? | e.g. "primeiros 3 meses", "com débito automático + conta digital". |
| `payment_method` | str? | **Postpaid** billing type: `credit_card` (recurring card — TIM's cheaper "Express"/"no cartão" line, low adoption) / `bill` ("na fatura") / null. The postpaid entry-level matrix pick **excludes `credit_card`** (JPMorgan rule → the bill-payment plan). TIM postpaid only; null elsewhere. (#24, §3) |
| `data_gb` | float? | Data allowance in GB (null/!= for unlimited — see `data_note`). |
| `data_note` | str? | Bonus/conditions, "internet ilimitada", accumulation, etc. |
| `validity_days` | int? | **Prepaid** plan validity in days (the recarga lasts N days). The Pre matrix column compares the cheapest plan with `validity_days >= 28` (a real 30-day plan). Null/blank for monthly plans. (#18, §3) |
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
- **`changes`** — computed diff vs the previous snapshot date: new plans, removed plans, price ↑/↓. **#29:** id-unmatched removed/new rows are re-paired by plan NAME (1:1 only) so a carrier id-rotation reads as the `price_change` it really is (§3).
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

> **Cross-section ranking — IMPLEMENTED (#9; moved to the `Ranking` sheet in #12):** the **`Ranking`** sheet compares like-for-like WITHIN each category, aligned by **price rank** (today's snapshot). Groups → `category`: **Pure Postpaid**=`postpaid`, **Control / Hybrid**=`control`, **Prepaid**=`prepaid`, **Digital**={`lite`,`flex`,`fit`} (Vivo Lite + Claro Flex + TIM Fit, #28). Each carrier's plans are sorted ascending by `price_brl`, then aligned across carriers by rank (cheapest-vs-cheapest, …); `price_promo_brl` shown alongside when present. Layout per group: `Rank | Vivo R$ | Claro R$ | TIM R$ | Vivo plan | Claro plan | TIM plan`; prepaid + Digital caveats printed in-sheet. `build_comparison_data` + `_write_ranking` in `excel_writer.py`, from the latest snapshot. (The `comparison` sheet itself is now the price-evolution matrix below.)

> **Per-operator sheets — IMPLEMENTED (#10, 2026-06-22):** one sheet per carrier present in the latest snapshot (name = display name **Vivo / Claro / TIM**; scales as carriers are added — absent carriers get no sheet). Within each: plans **grouped by category** in order **Postpaid → Control → Digital ({lite,flex,fit}) → Prepaid** (bold sub-header per block), sorted ascending by `price_brl`. Readable column set: **Plan | Price R$ | Promo R$ | Data | Voice | Unlimited apps | Streaming | Notes** (Data = `data_gb` + `data_note`; Notes = `extra_benefits` + `price_note`; internal `plan_id` omitted; blank where null). `build_operator_sheets` + `_write_operator_sheets` in `excel_writer.py`, wired after the comparison sheet; rebuilt from the latest snapshot every run. First cut — expect iteration.

> **Price-evolution matrix — DAILY, table-only (now #19; was monthly #16, daily #12):** the **`comparison`** sheet is the **Date × (category × carrier) matrix**, a **clean table** at the **TOP of the sheet** (group titles row 1, **TIM | Vivo | Claro** sub-header row 2, day rows from **row 3**; charts on a separate `Charts` sheet — see below). **Rows = day (#19):** col A holds one row per distinct **`snapshot_date`** in `history` (via `evolution_dates`), **earliest first** (2026-06-22 at the top), stored as a real **DATE** and display-formatted **`dd-mmm`** (→ 22-Jun). Columns: `Date` + four groups (**Control / Post / Pre / Digital**, each merged over **TIM | Vivo | Claro**). Each value cell is a **live `_xlfn.MINIFS` over `history`** = the **cheapest R$ that carrier offered in that category ON that exact snapshot_date** — so the workbook stays **self-connected** and the matrix **grows one row per day** automatically as the daily job adds snapshots. **Digital** = `MIN(lite, flex, fit)` via the reciprocal-max trick (#28 added fit); 0 / no-match → blank so the heatmap ignores it. **#28:** the **fit** component requires `loyalty_months` **BLANK** (criterion `"="` — COM-verified) — the opposite gate of lite, because Fit's versions are separate plans and the no-commitment **Mensal (R$35)** is the entry while the **Anual (R$30, 12-mo permanence)** is excluded → **Digital TIM = R$35**. **#26:** the **lite** component requires `loyalty_months > 0` (`history!<loyalty>,">0"`) so only Easy Lite plans that offer a **"Sem fidelidade"** choice count — the monthly-only 20GB "Plano mensal" R$35 is excluded, so **Digital Vivo = the cheapest Sem-fidelidade plan (R$45)**; Flex (Claro) has no toggle → unrestricted. Pre-#23 lite rows (no loyalty) self-heal to blank. **Pre** = cheapest **30-day prepaid plan** (`validity_days >= 28`, monthly R$/mo, #18). **Post** = the plain **cheapest postpaid plan, credit-card-only INCLUDED** (#27 — the Bridge reverted #24's exclusion: TIM's R$119,99 "no cartão" plan IS the tracked entry-level, and a change on it is caught by `changes` + the #15 alert; the `payment_method` tag stays in history for context, an in-sheet footnote flags the billing type). **Heatmap (#20): per-category-BLOCK 2-colour green→yellow scale** (JPMorgan style — green cheaper, yellow pricier, no red): one scale over each group's **3 carrier columns × all date rows** (Control B3:D, Post E3:G, Pre H3:J, Digital K3:M), so a cell's colour reflects its price **vs all carriers in that category** (cross-carrier comparison shows in colour). Subtle while prices are near-flat; differentiates as they move. (Was per-column in #19.) Same-day re-runs stay **idempotent per date**; the rank-aligned cross-section is preserved on the **`Ranking`** sheet. **Layout (#17):** only the **2 header rows + the Date column are frozen** (`freeze_panes="B3"`); `comparison` is the **active sheet on open**; never protected (`protection.sheet=False`). **Prepaid-validity transition (#18→#19, expected, not a bug):** the pre-#18 snapshots (Jun 22–25) have no `validity_days`, so their daily **Pre cells are blank** (filtered by `>=28`) and populate **from Jun-26 on**; the old Claro R$1 rows likewise drop out of Pre. Self-heals as new days accrue. **Cached values baked (#21):** because openpyxl writes formulas without cached values, `write_workbook` bakes a `<v>` alongside each matrix/summary `<f>` after save — so the committed workbook DISPLAYS its values in any viewer while keeping the live formulas (see §5 "Committed workbook DISPLAYS its values").
>
> **⚠️ Formula gotcha — date match is a MINIFS EXACT TEXT DATE, not a date/serial criterion (verified in real Excel, #16; reused #19):** `history.snapshot_date` is stored as **TEXT** (`'2026-06-22'`, not an Excel date serial). Excel **coerces any date/serial comparison criterion** (incl. `">="&$A2` or `EOMONTH` bounds) to a number that **never matches a text column** → blank. So the daily matrix matches history's text date with an **EXACT text date built from the row's DATE cell**: `YEAR($A<row>)&"-"&TEXT(MONTH($A<row>),"00")&"-"&TEXT(DAY($A<row>),"00")` → `"2026-06-22"` (no wildcard; the #16 monthly form was the same construction with a `"-*"` prefix instead of the day). Built from `YEAR()`/`MONTH()`/`DAY()` + a **numeric `"00"`** format — NOT the `"yyyy"/"mm"/"dd"` date codes, which **pt-BR Excel localizes** (`TEXT($A1,"yyyy-mm-dd")` would return literal `"yyyy-06-..."`). So it is locale-independent and computes correctly. `_minifs_day` in `excel_writer.py` carries this rationale. *(Literal date bounds would require storing `history.snapshot_date` as real Excel dates — a `history`-data change excluded by these tasks.)*

> **Evolution charts — own `Charts` sheet (#13 → #17 split → #19 daily → #20 styled + bar chart):** the four per-category **line charts** (Control / Post / Pre / Digital) live on a **dedicated `Charts` sheet** (2×2 layout, tab color `#43A047`), **not overlaying the matrix**. Each references the `comparison` matrix via **cross-sheet refs** (X = `'comparison'!$A$3:$A$<lastday>`, three series = the group's TIM/Vivo/Claro matrix columns), palette-matched lines (TIM `#0033A0`, Vivo `#660099`, Claro `#DA291C`), markers on, **daily X-axis**, **legend at bottom, no vertical gridlines** (clean report styling, #20). Refs are **rebuilt each run** to the days present; charts read the matrix (which reads `history`), so they **grow into trend lines** as daily history accumulates. **JPMorgan Figs 7/8/9 refinement (#25):** title **"<Category> – Monthly Prices"**, **one faint horizontal gridline** only (no vertical), and a **FIXED Y range per category** (`EVOLUTION_YRANGE`: Control 40–70, Post 90–170, Pre 20–40, Digital 25–65) so the axis is **stable as history grows** (the lines are short now with ~10 days; they fill into real trends). Pre uses the **30-day MONTHLY** value (~R$20–40), NOT JPMorgan's R$/day (Bridge's no-avg-daily call). Still fully automated (fixed ranges are chart *axis* config, not data). **TIM footnote (#25; rewritten #27):** the `comparison` sheet carries a note that TIM's tracked Post entry is the cheapest plan, **R$119,99, credit-card-only** ("no cartão"), with the cheapest bill-payment plan (R$129,99) given as context (§3). **Out of scope:** JPMorgan's **vs-2020 / yearly-change** charts (Figs 10, 12–20) need a 2020 baseline + years of history we don't have.
>
> **Current-price bar chart (#20, JPMorgan Figure-11 style; #25 refined):** below the line charts, a **grouped column chart** — X = the four categories (Control / Post / Pre / Digital), 3 bars each = **TIM / Vivo / Claro**, values = the **MOST RECENT day's entry-level price** per carrier/category (Pre = the 30-day monthly value). It's **structure-driven**: a small helper table (off to the right at `P37`) holds **cross-sheet refs to the LAST matrix row** (rebuilt each run → auto-updates as new days land — no hardcoded numbers). Title "Current entry-level price by carrier (R$)", data labels on, carrier-palette bars, **clean gridlines** (#25: no vertical, one faint horizontal — shared `_clean_gridlines` helper). openpyxl native `BarChart` — no images/macros.
>
> **Gridlines OFF on all 10 sheets** (`_gridless` → `sheet_view.showGridLines=False`), and **no heavy chart gridlines** (vertical gridlines removed; light horizontal Y at most). **Charts populate on open in Excel** (which recalcs the matrix formulas); a populated GitHub *preview* would need a headless-recalc step in CI (out of scope — flag if wanted). openpyxl native `LineChart`/`BarChart` — no images/macros.
>
> **The "locked view" fix (#17):** users reported `comparison` opened "locked" — only charts visible, couldn't scroll to the table. **Root cause was NOT sheet protection** (the sheet was never protected): the 4 charts overlaid the top ~35 rows and the matrix started at row 35 with **`freeze_panes` pinning a 36-row block** (`B37`), so the frozen chart region filled the viewport. Fixed by **splitting** — the table moved to the top of `comparison` (frozen at `B3`), the charts moved to the `Charts` sheet — so the workbook opens on a clean, scrollable matrix.

> **House style — IMPLEMENTED (#11, 2026-06-22):** the workbook look is applied **in code** (`excel_writer.py`), so the daily job reproduces it every run. Plain `.xlsx` — **no buttons, macros, or `.xlsm`** (Bridge's call). Design system (constants, applied to all sheets): header navy `#1F3864` white-bold + thin bottom border; **gridlines OFF on every sheet**; alternating row banding `#F2F5FA`; carrier-sheet category sub-headers `#D6E0F0`; cheapest-of-row highlight `#C6EFCE`/`#006100`; promo accent `#FFF2CC`; tab colors — Vivo `#660099`, Claro `#DA291C`, TIM `#0033A0`, comparison `#2E7D32`, summary `#102A43`, engine sheets (history/latest/changes) grey `#8A8A8A`. Conditional formatting: **comparison** color-grades the three R$ columns green→yellow→red and highlights the cheapest carrier per rank; **latest + carrier sheets** color-scale the price column (per block); promo cells get the amber accent. First cut — expect iteration.

## 8. Known challenges / risks

### Price validation (2026-06-22, CODE TASK #11)

Spot-checked the `comparison` sheet against the carriers' official pages + independent sites: the **cheapest-postpaid ranking matched** (TIM ≈R$119,90 < Claro R$124,90 < Vivo R$150) and absolute prices lined up. Open refinements for the comparison work (parked — each can change *which* plan is "cheapest"):
- **(i) Fidelity vs non-fidelity:** we capture the one displayed price; the cheapest can shift with loyalty. **Audited (#22):** the only category with a loyalty toggle is **Vivo Lite** — "Plano anual" (12-mo) R$30 vs "Plano mensal / Sem fidelidade" ≈R$45; we capture the **annual (loyalty)** price, the no-commitment one is toggle-gated + uncaptured. Vivo control/postpaid are single-price. Claro control captures **both** (regular 59,90 + effective 54,90); TIM control captures the **effective** (58,99…, "Desconto Extra R$5"; list 63,99 uncaptured). ✅ **RESOLVED (#23):** the Vivo-Lite render now clicks "Sem fidelidade" → headline = **no-commitment** (R$35/45/55), the 12-mo loyalty kept as `price_promo_brl` (`loyalty_months=12`). (TIM-control list price still uncaptured — minor, LOW.) ✅ **Payment-method dimension CAPTURED (#24; pick reverted #27):** TIM postpaid prices by payment method (credit card "no cartão" vs "na fatura") — recorded per plan in `payment_method` (§3/§6). #24 excluded credit-card-only from the Post pick (bill R$129,99); **#27 reverted that per the Bridge** — the Post entry tracks the plain cheapest (R$119,99, credit-card), flagged by the in-sheet footnote, with changes caught by `changes` + the daily alert. All plans stay in history.
- **(ii) Consistent GB definition:** base vs base+bonus differs by carrier; needed for a fair data-tier view. **Still pending.**
- **(iii) Prepaid normalization:** ✅ **PARTLY IMPLEMENTED (#18):** each prepaid plan now carries `validity_days`, and the Pre column compares the cheapest **30-day** plan (validity_days >= 28) shown as monthly R$/mo (Claro R$1/dia → the real R$30/30d plan). The avg-R$/day form (JPMorgan-style = price ÷ validity) is a one-line switch if preferred. ✅ **#23:** TIM prepaid validity corrected to **per-oferta** (17/22/30) — the #18 max-heuristic bug is fixed, so the Pre column now reads the true 30-day (TIM R$30). Remaining: per-tier value comparison.
- **(iv) R$/GB value lens:** add cost-per-GB so plans can be ranked by *value*, not just absolute price. **Still pending.**

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
5. **NO LOYALTY HEADLINE PRICES — EVER (standing rule, 2026-07-13).** The tracked headline / entry-level price is **always the monthly price WITHOUT a loyalty/fidelity commitment** — for every carrier and category, **including TIM Fit**. Loyalty prices ("fidelidade" / "plano anual" / "prazo de permanência") are recorded only as context (`price_promo_brl` + `loyalty_months`) and are **excluded from every entry-level pick and cross-carrier ranking**. Applications: Vivo Easy Lite headline = the "Sem fidelidade" toggle price (#23/#26); TIM Fit entry = the Mensal, the Anual excluded (#28); any future loyalty-gated plan gets the same treatment. Distinct from payment method (the #27 Post decision — that's about billing rails, not commitment). Enforced fail-loud: the Vivo lite fetch detects a lost toggle capture and retries + warns (#30).

## 11. Changelog
- **0.9.0 — 2026-08-04** — CODE TASK #33 (convergent **phase 3**): the **`convergent_comparison`** sheet — the combo equivalent of the mobile matrix (§14). Rows = one per `snapshot_date` (earliest first, auto-growing); columns = **bundle-type groups × TIM|Vivo|Claro**; each cell = a **live exact-date `_xlfn.MINIFS`** over `convergent_history` with the **cached value baked** beside it (#21), styled like `comparison` (house header, gridlines off, per-block green→yellow scale, freeze B3, R$ format, in-sheet note). New derived column **`bundle_type`** on `convergent_history` — `Fibre + Mobile` / `Fibre + TV` / `Fibre + Mobile + TV`, computed from the existing service flags (**no new scraping**) and **backfilled** for pre-#33 rows so past dates aren't blank (the #18 self-healing pattern); an unseen shape gets its own group instead of being folded into an existing one. **Cheapest WITHIN a type, not overall** (Bridge's call) so columns stay like-for-like. Blank = the carrier sold no combo of that type that day (never a 0). Observed 2026-08-03 spread: **TIM** Fibre+Mobile only (3) · **Vivo** Fibre+Mobile (6) + Fibre+Mobile+TV (5) · **Claro** all three (4/3/3) — no fourth type; first row = Fibre+Mobile **89,99 / 160 / 129,80**, Fibre+TV **Claro 219,80**, Fibre+Mobile+TV **Vivo 190 / Claro 259,80**. `convergent_history.snapshot_date` **confirmed TEXT** (`data_type='s'`), so the locale-safe text-date construction is required and used; an **Excel COM recalc matched all 18 cells to the baked values (0 mismatches)**. The matrix builds inside its own guard nested in the convergent guard — a failure keeps the history sheet, empties `conv_values` (so the fail-loud bake check can't abort over a skipped side sheet) and never touches the mobile write. Mobile untouched (43 snapshots / matrix rows unchanged, Post TIM 119,99, Digital Vivo 45). Tests 132 → **143**.
- **0.8.1 — 2026-08-03** — CODE TASK #32 (convergent **phase 2**): the remaining two carriers, both live. **Vivo Total** (`adapters/vivo_convergent.py`, Playwright — httpx is 403 behind Cloudflare): **11 SP combos R$160 → R$1 200**, 5 with TV, incl. the real V 1 Giga (1 Gbps + 600 GB + 11 lines + TV Completo). Traps handled: the **`VIV` code is NOT unique** (2 collisions across 11 cards) → `offer_id` = code + the card's own **sorted `productsIds`** composition (carrier-native, never price-derived, collision-proof, with a slug/position fallback so no card is dropped); **lazy render** → bounded scroll until the card count stops growing; the **paid apps add-on that hides the price element** → fall back to `data-original-price` and record the base price with a note (never base+add-on, never a dropped offer); struck-through prices become the promo, and **no session variant appeared this run** (all 11 flat, matching 07-17). **Claro Multi** (`adapters/claro_convergent.py`, **no browser**): `__NEXT_DATA__` `tab_select` grid (located **by component name** — a `card_360` of another product line sits on the same page) + **ONE batched** public `GET /api/catalog?state=SP&city=sao_paulo&uuids=…`; **10 live combos R$129,80 → R$459,80**, **5 ghosts** (`catalog.notFound` — listed by the CMS, not sold in SP) excluded; price = Σ(`precoCombo` **if the key is present** else `preco`) in integer centavos — the key is *absent* on `internet` for every Fibra+TV card, so a falsy-default read would under-price those by up to R$179,90; fields from `catalog.nomeAutomatico` (CMS names are stale) and speed from `recursosDescritivos["602"]`; SP is an **explicit request parameter**, not a geolocated guess. Both activated in `convergent:`; the #31 guards re-verified with **three** targets (a test proves one source exploding still lets the other two + the mobile write complete). Live end-to-end: **24 offers** (TIM 3 / Vivo 11 / Claro 10) with the mobile history (2 336 rows / 42 snapshots) untouched. Tests 120 → **132**.
- **0.8.0 — 2026-08-03** — CODE TASK #31 (Bridge numbering "#26"; that number was already used twice in this repo — see the 0.5.8 and 0.7.1 entries — so this ships as **#31**): **CONVERGENT OFFERS become a tracked domain (phase 1)** — new **§14**. Live investigation of all three SP combo pages: **all DISCRETE priced tiers, none a configurator**; two §13 facts corrected — TIM's Ultracombo page now **exists** (httpx 200; it 404'd on 07-17) and Claro Multi's prices are now reachable **without a browser** (`__NEXT_DATA__` grid + one public `/api/catalog` call); Vivo Total still needs Playwright (Cloudflare now, not Akamai). New **separate** schema `ConvergentOffer`/`CONVERGENT_COLUMNS` (`convergent.py`) — `offer_id` carrier-native & never price-derived, derived `services` summary, `is_valid()` demands ≥2 bundled services, `payment_method` for the billing rail. New **`convergent_history`** sheet: append-only, same per-date idempotency as the mobile history, flat (no formulas/bake/charts) — and **always re-read + re-emitted**, because `write_workbook` rebuilds the file and would otherwise DESTROY it on any run that collected nothing. First scraper: **TIM Ultracombo** (`adapters/tim_convergent.py`, plain httpx) — live-verified 3 SP combos **R$ 89,99 / 139,99 / 169,99** (500M+65GB / 1G+70GB / 1G+115GB, one line each, no TV), ids = native nids. Built around three verified traps: the **ghost price fields** (`field_preco_adicional_*`, identical on all tiers — the mobile adapter treats that field as a real struck-through price, so reusing it would fake a promo on every combo), **`langcode` lying "rj"** for SP-only offers (gate on `field_regioes`), and streaming living in **icon media names**. Wired into the daily job **GUARDED at two layers** (per-target in `main.run()` + around the merge/sheet-write inside `write_workbook`) so no convergent failure can block the mobile scrape, write or commit; `--demo` skips it. Config gains a **`convergent:`** section (TIM active; Vivo/Claro staged for phase 2). Mobile pipeline untouched — matrix, formulas, #21 bake, charts, alerts, idempotency all verified unchanged. Tests 106 → **119**.
- **0.7.1 — 2026-07-17** — CODE TASK #26 (Bridge numbering; the repo's earlier "#26" was the 0.5.8 Vivo-Lite metric task): convergent-offers English snapshot — `analysis/convergent_offers/convergent_offers_2026-07.xlsx` (TIM Ultracombo 7 rows from TIM's published table verified vs Teletime, **Vivo Total 11 combos + Claro Multi 5 combos scraped live**, SP; unified 5-column English format incl. "Other Benefits"; every row sourced; prices numeric with TIM's `*` applied via number format). Entry face-off as verified: **TIM R$ 89.99\*** (65GB+500 Mbps, SP-only, débito automático) vs **Claro R$ 129.80** (Controle 41GB+350 Mbps, limited-time — the recon lead's R$ 159.90 is the "Melhor escolha" mid-tier, not the entry) vs **Vivo R$ 160** (Total Pro 60GB+500 Mbps). The `*` footnote CONFIRMED from TIM's table caption via Teletime: "Ofertas disponíveis apenas em São Paulo" + all TIM prices are débito-automático prices. New **§13** with the two pages' parse paths (Vivo Total = same Playwright+`.unique-card` IP as §3; Claro Multi = `tab_select` grid, benefits in `__NEXT_DATA__` but prices client-hydrated → Playwright). Vivo's suspicious R$ 1,200 lead verified REAL (V 1 Giga: 1 Gbps+600GB+10 lines+Vivo TV Completo). raw/ kept local (not committed). Daily pipeline untouched.
- **0.7.0 — 2026-07-17** — CODE TASK #25 (Bridge numbering; distinct from the 0.5.7 in-sheet-footnote task that also carried "#25"): first historical study under a new **`analysis/`** component — the **2023–2026 promo-vs-entry time-series** (flagship campaign price as % of same-category entry-level, SP, annual + event log; **53 sourced data points** — 36 entry-price cells + 17 campaign events — no estimates, every point URL+access-dated; coverage: **controle + pós complete for all 12 carrier-years**, digital complete except TIM 2023–25 [structural — Fit only launched Jul-2026], pré 30-day 2023–25 left blank with a gap note; headline finding: **flagship promos flipped from ~100%-of-entry bonus-GB campaigns (2023–24) to real price aggression (2025–26), and the July-2026 convergence face-off has TIM Ultracombo at 69% and Vivo Total Ultra at 67% of their own entry pós — bundles priced BELOW mobile entry for the first time — while Claro Multi stays above (128% pós-based)**; the Bridge-reported "new mid-July Vivo convergent offer" could NOT be verified as a new launch — the verifiable 2026 Vivo flagship is the May–June R$100 Total Ultra promo). New **§12**; deliverables `analysis/promo_vs_entry/{promo_vs_entry.xlsx, report.md, sources.md, check.py}` (check.py green: ratios recomputed, sanity bands, source-per-point, 2026 anchors == tracker). Daily pipeline untouched. Minor bump for the new component (the task template said "0.6.0" but 0.6.x was already taken by #28–#30 — bumped to 0.7.0).
- **0.6.1 — 2026-07-13** — CODE TASK #30 (Bridge STANDING RULE, stated verbatim: monthly-without-loyalty prices always, "including TIM Fit"): **no-loyalty-headline rule codified as Bridge decision §10.5** — already enforced in every pick (#23/#26/#28); this task closes the last silent hole: a failed Vivo "Sem fidelidade" toggle click writes LOYALTY prices as lite headlines (it happened on the 2026-07-12 snapshot — Easy Lite recorded 30/40 loyalty instead of 45/55, surfacing as spurious ±R$15 changes on 07-13). New `lite_capture_lost_toggle` detector (a lite parse where NO plan carries `loyalty_months`) + fetch now **retries the render once and warns LOUDLY** (`WARNING vivo/lite`) if the toggle capture is still missing — recording proceeds (collection > notification) but never silently. Tests 105 → 106.
- **0.6.0 — 2026-07-13** — CODE TASKs #28 + #29 (Bridge-directed). **#28 TIM Controle Fit** (TIM's new digital line, the Vivo-Lite/Claro-Flex peer): new category **`fit`** (§6) scraped from the **controle page's `#price-fit` TEXT section** (NOT the ofertas JSON — §3 recon) via `parse_tim_fit_html`; two SP plans — **Anual 30GB 12x R$30 no cartão, 12-mo permanence** (`loyalty_months=12`, `payment_method="credit_card"`) and **Mensal 20GB R$35 sem permanência**; plan_ids = the stable etiqueta codes (`tim:TIM202600000271/270`). Digital matrix/Ranking/operator sheets gain `fit`; the Digital MINIFS adds a fit term gated on `loyalty_months` **BLANK** (criterion `"="`, COM-verified; the bake mirrors it with isna) → **Digital TIM = R$35** (the no-commitment Mensal; the loyalty Anual excluded per the #26 rule). **#29 id-rotation-resilient change detection** (root cause of the missed 2026-07-06 alert — TIM republished every Controle plan under a fresh nid while cutting prices −7.7/−15.3/−17.6%, which id-only matching read as 5 removed + 5 new → no e-mail): `_compute_changes` + `compute_price_alerts` now re-pair id-unmatched rows by **(carrier, state, category, plan_name), 1:1 unambiguous only** → real moves become `price_change` (reported under the new id) + the alert fires; same-price re-keys go silent; ambiguity keeps honest new/removed. Excel COM verified (Digital TIM R$35 live formula == bake; rotation day → one price_change row). An adversarial review caught 4 defects pre-commit (dot-decimal price mangling; unbounded modal code-search → id collision; a phantom "daily-count" safety claim → loud fetch WARNING instead; the Ranking sheet ranking the loyalty Anual against no-commitment prices → excluded from that view only). Tests 93 → **105**.
- **0.5.9 — 2026-07-03** — CODE TASK #27 (Bridge REVERSAL of #24's Post pick): the matrix **Post column tracks the plain CHEAPEST postpaid plan again — credit-card-only INCLUDED** — so for TIM it reads the **R$119,99** "A Express" (no cartão) plan; the Bridge wants to *watch that price* and be told when it moves (the `changes` sheet + the #15 daily ≥3% alert track its `plan_id`, tim:55121). `excel_writer` only: the Post `MINIFS` dropped the `"<>credit_card"` criterion and `_matrix_value` its mirror filter (bake == formula re-verified via Excel COM recalc — Post TIM R$119,99 on all rows, Digital Vivo R$45 and everything else unchanged). **The `payment_method` TAG is fully retained** (schema §6 + `tim.py` tagging + history) — billing type stays visible per plan; only the entry-level pick stopped excluding it. Comparison-sheet footnote rewritten: entry-level = the cheapest plan R$119,99, flagged CREDIT-CARD-only, with the R$129,99 bill plan noted as context. Tests 94 → 93 (three exclusion tests → two cheapest-pick tests; note test rewritten). Historical rows are already 119,99 (pre-#24) or become 119,99 on the next regeneration (the matrix recomputes from history each run).
- **0.5.8 — 2026-07-02** — CODE TASK #26 (Bridge-directed metric refinement — Vivo Lite entry-level): the **Digital column's Vivo/lite pick now requires `loyalty_months > 0`** — i.e., only Easy Lite plans that OFFER a "Sem fidelidade" choice (a monthly/annual toggle card, which the #23 parser tags with `loyalty_months=12`) count as the entry-level. This EXCLUDES the monthly-ONLY **20GB "Plano mensal" R$35** (no loyalty option), so the entry-level is the cheapest *Sem-fidelidade* plan = **R$45** (30GB), matching how JPMorgan treats commitment-gated tiers (same spirit as the TIM credit-card exclusion, #24). Live-investigated (SP render): 3 Easy Lite `.unique-card`s (20GB R$35 mensal, 30GB R$45 / anual 30, 40GB R$55 / anual 40) — the R$30/R$40 are the annual/loyalty prices (already the `price_promo_brl`); the screenshot's 4th "OFERTA POR TEMPO LIMITADO" 40GB R$40 card is a transient/personalized promo not served to the headless scraper (its R$40 annual price is already captured as the 40GB loyalty promo). Change is `excel_writer` only — the lite `MINIFS` gains `history!<loyalty_months>,">0"` (Excel numeric `>0` excludes blanks, verified via COM recalc) and `_matrix_value` mirrors it, so **bake == live formula** (Digital Vivo 2026-07-01 = R$45.00 recalculated). Flex (Claro) has no toggle → unrestricted (Digital Claro still R$44,90). All Lite plans stay in `history`/`latest`/the Vivo sheet — only the entry-level Digital pick changes. Pre-#23 lite rows have no `loyalty_months` → those dates (Jun 22–30) **self-heal to blank** (like #18/#23), since none had a captured Sem-fidelidade price. §3/§7 updated. Tests 92 → 94.
- **0.5.7 — 2026-07-02** — CODE TASK #25 (presentation only — no value/metric/adapter/schema/history/formula/bake change): **TIM bill-payment note** added to the `comparison` sheet (next to the existing footnote) — the TIM Post entry-level is the cheapest **bill-payment** plan (R$129,99), not the R$119,99 credit-card-only plan (low adoption, JPMorgan rule); all TIM plans still appear in `history`/the TIM sheet. **Charts refined to JPMorgan style, kept automated** (`_write_charts`/`_line_chart`/`_current_price_bar` still read the matrix via cross-sheet refs, rebuilt each run): the 4 **line** charts (Figs 7/8/9) → title "<Category> – Monthly Prices", bottom legend, carrier palette + markers, **one faint horizontal gridline** (no vertical), and a **FIXED Y range per category** (`EVOLUTION_YRANGE` — Control 40–70, Post 90–170, Pre 20–40, Digital 25–65) so the view is stable as history grows (Pre = the 30-day MONTHLY value, not R$/day — Bridge's call); the **bar** chart (Fig 11) → same clean gridlines, data labels on, carrier bars. Gridlines already off on all sheets (`_gridless`). The JPMorgan **vs-2020 / yearly-change** charts (Figs 10, 12–20) need a 2020 baseline + years of history we don't have — **out of scope**. §3/§7 updated. Tests 89 → 92 (line-chart title/Y-range/gridlines, bar-chart clean, TIM note present).
- **0.5.6 — 2026-07-01** — CODE TASK #24 (TIM postpaid entry-level = bill-payment plan, not credit-card): **payment_method** added (`models.py` COLUMNS + Plan; §6). `tim.py` `_payment_method` classifies postpaid from `field_preco_principal_7_1_3` — "no cartão" → `credit_card`, "na fatura" → `bill` (mutually exclusive in that field, live-verified SP; `field_formas_de_pagamento` is empty/useless). The **matrix Post** `MINIFS` gains `history!<payment_method>,"<>credit_card"` (postpaid group only) and the #21 bake `_matrix_value` mirrors it → **Post TIM = R$129,99** (Black 70GB, bill), excluding the R$119,99 A Express (credit card, JPMorgan low-adoption rule). **Verified via Excel COM recalc that `"<>credit_card"` INCLUDES blank cells**, so Vivo/Claro (untagged) are unaffected and pre-#24 history self-heals; bake == live formula. All plans stay in `history`/`latest`/operator sheets — only the entry-level pick excludes credit-card-only. §3 adds the finding subsection; §6 the field; §7 the Post note; §8(i) resolved. Tests 82 → 89 (adapter tagging + gating + matrix exclusion + `_matrix_value` unit + blank self-heal + anchored-headline regression). Adversarial-review-hardened: the classifier anchors to the `/mês <phrase>` price headline so stray marketing text can't misclassify (a bill plan must never be misread as credit-card).
- **0.5.5 — 2026-07-01** — CODE TASK #23 (adapter fixes — the two #22 mismatches): **TIM prepaid validity → per-oferta** (`tim.py` `_prepaid_validity`: match each oferta's own "R$<recarga> … por <N> dias", not the max — the #18 bug where a shared 30-day marketing line inflated all to 30). Live: R$20→17d, R$25→22d, R$30→30d → **matrix Pre TIM = R$30** (was R$20). **Vivo Lite → no-commitment price** (`vivo.py`): `_render` clicks each Easy Lite card's "Sem fidelidade" toggle for the `lite` target; parser records `price_brl` = no-commitment (visible text), `price_promo_brl` = 12-mo loyalty (`data-original-price`), `loyalty_months=12`. Live: R$45/30GB (loyalty 30), R$55/40GB (loyalty 40), R$35/20GB (single-price) → **Digital = R$35** (cheapest no-commitment Vivo Lite; the 20GB card has no annual option — *not* ~R$45 as the task assumed). Other categories/carriers untouched (category-gated); matrix formulas + #21 cached-value bake unchanged. §3 adds the #23 fix subsection + flips the #18/#22 "pending" markers to resolved; §8(i)/(iii) resolved. Live re-scrape (claro 20 / tim 15 / vivo 22) confirms both. Tests 81 → 82.
- **0.5.4 — 2026-07-01** — CODE TASK #22 (read-only **source-of-truth audit**; docs only, no adapter/schema/matrix change): live SP fetch of all three carriers compared field-by-field to what we parse. Full note: **`docs/source_audit_2026-07.md`**. **SP confirmed** for all (Claro `SEGMENTATION_DEFAULT.uf=SP`, Vivo "São Paulo (SP)" label, TIM `/sp/` path). **Confirmed correct:** postpaid TIM 119,99 < Claro 124,90 < Vivo 150; Claro Control 59,90→54,90; Claro Prezão 30-day R$30; Vivo control/postpaid/prepaid; TIM control-effective + postpaid. **Two mismatches (fixes next):** (1) **TIM prepaid validity** — #18's MAX-"N dias" heuristic was WRONG (a shared "R$30…30 dias" line inflated all to 30d); true = **R$20/17d, R$25/22d, R$30/30d**, so the real cheapest 30-day TIM is **R$30 not R$20** (Pre column wrong since #18); (2) **Vivo Lite** — captures the "Plano anual" (12-mo loyalty) **R$30**; the "Sem fidelidade" no-commitment **≈R$45** is toggle-gated + uncaptured (lite only). §3 gains the audit subsection + a ⚠️ correction to the #18 TIM note; §8(i) updated.
- **0.5.3 — 2026-06-30** — CODE TASK #21: **committed workbook now DISPLAYS its values in any viewer** (was blank in GitHub preview / Google Sheets / mobile / Protected View because openpyxl writes formulas without cached values). Fix = a **cached-value bake** in `write_workbook`: after openpyxl saves, `_bake_cached_values` injects a `<v>` **alongside** each matrix + summary formula's `<f>` (never replacing it), computed in Python by `_matrix_value` / `_write_summary` with the SAME logic as the formulas. So `data_only=True` now shows values AND the live MINIFS formulas remain (Excel still recalcs on open). Chose the Python bake over LibreOffice recalc (untestable locally + risks mangling the 5 charts/CF) — the bake is surgical (rewrites only the 2 sheet XMLs; charts/CF/formatting byte-identical), CI-native (no install, no workflow change — runs in the code the daily job already executes), deterministic. **Adversarial review caught a blocker:** openpyxl 3.1.x writes a formula cell with an EMPTY value placeholder (`<v/>` lxml / `<v></v>` stdlib), so a naive injector bakes 0 (or a duplicate `<v>`) — the injector now drops the placeholder and writes one `<v>`, and `write_workbook` **raises on a 0/partial bake** (fail-loud, never ship blank). Verified on openpyxl **3.1.5**: `data_only=True` → 87/108 matrix values (21 correctly-blank no-offer cells) incl. Control 22-Jun 58.99/59/59.9, single `<v>` per cell; formulas + 5 charts + 10 sheets intact; 78 → 81 tests. §5 documents the mechanism + the 3.1.x gotcha; §7 notes the bake. No value/metric/adapter/schema/history change.
- **0.5.2 — 2026-06-26** — CODE TASK #20 (presentation only — no value/metric/adapter/schema/history change): **match JPMorgan visuals.** Heatmap → **per-category-BLOCK green→yellow** (4 ranges: Control B3:D, Post E3:G, Pre H3:J, Digital K3:M, each one 2-colour scale over its 3 carrier columns × all date rows, no red — colour reflects price vs all carriers in the category) — was per-column in #19. Line charts **styled clean** (bottom legend, **vertical gridlines removed**, carrier palette + markers, Y="R$"). **NEW current-price grouped bar chart** on `Charts` (JPMorgan Fig-11 style): X = Control/Post/Pre/Digital, 3 bars = TIM/Vivo/Claro, values = the **latest matrix row** via a helper table of cross-sheet refs (structure-driven, auto-updates; Pre = 30-day monthly), data labels on, carrier-palette bars. **Gridlines OFF re-verified on all 10 sheets.** Verified in Excel: comparison ChartObjects=0 / Charts=5 (4 line + 1 bar); bar reads the 26-Jun row (Post 119.99/150/124.9, Pre 20/30/30). §7 updated (per-block heatmap + bar chart + styling + gridlines). Tests updated; suite green (78). Patch bump (presentation).
- **0.5.1 — 2026-06-26** — CODE TASK #19 (presentation/formula only): **comparison matrix MONTHLY → DAILY rows.** Rows = one per distinct `snapshot_date` (`evolution_dates`), **earliest first** (2026-06-22 top), as real dates display-formatted `dd-mmm`; header A1 = "Date". Each value cell = a live **exact-date `_xlfn.MINIFS`** over `history` (`_minifs_day`) matching the row's date built locale-safe as `YEAR()&"-"&TEXT(MONTH(),"00")&"-"&TEXT(DAY(),"00")` (reuses the #16 text-date learning, exact-date not month-prefix) — so the matrix **auto-grows one row per day**. **Heatmap → 2-colour green→yellow (JPMorgan style), per carrier column** (each column by its own min/max, no red; `_price_scale_2color`); the 3-colour red scale stays on latest/operator/Ranking. Charts (on the `Charts` sheet, #17) → **daily X-axis**, refs rebuilt to the dates present. Table-only layout, freeze B3, active sheet, idempotency, all other sheets intact. **Verified in Excel:** opens on `comparison`, 5 daily rows (22–26 Jun), exact-date cells populate, Pre blank Jun 22–25 then 20/30/30 from Jun-26 (the #18 validity transition — expected, self-heals). §7 updated (daily matrix + exact-date gotcha + green→yellow + validity transition). Tests updated for daily; suite green (76). Patch bump (presentation).
- **0.5.0 — 2026-06-26** — CODE TASK #18 (schema + first ADAPTER change): **prepaid now captures the real 30-day plan + `validity_days`.** Schema §6 gains a nullable `validity_days` (int, prepaid). **Claro** prepaid no longer reports the "R$1 por dia" headline — `parse_claro_prepaid` regexes the rich-text recarga tiers (`"R$ 30/30 dias – 12GB"`), keyed `claro:prezao-<days>d-<gb>gb` (non-price); **Vivo**/**TIM** prepaid now record validity (Vivo from the card text; TIM = max "N dias" in the oferta, no clean field). The **Pre matrix column** = cheapest prepaid with `validity_days >= 28` (config `prepaid.min_validity_days`), relabeled "Pre (R$/mo, 30-day)", shown monthly. **Live re-scrape (2026-06-26) confirmed:** Claro 30-day = **R$30** (was R$1), Vivo R$30, TIM R$20 (cheapest 30-day; all XIP are 30-day); Pre row recalculated in Excel = 20/30/30. **Bug found+fixed:** merging a pre-#18 history (no `validity_days`) pushed the column to the end via `pd.concat`, mis-aligning the matrix formula → `_merge_history` now reindexes to `COLUMNS`. Postpaid/control/lite parsing untouched (gated on prepaid; verified by re-parsing saved captures). §3 documents per-carrier capture; §8(iii) marked partly implemented. Tests 67 → 73. Minor bump for the schema field.
- **0.4.7 — 2026-06-26** — CODE TASK #17: **split the evolution view into two sheets** (layout/presentation only — matrix formulas, data, schema, scraping untouched). `comparison` is now a **table-only monthly matrix at the TOP of the sheet** (group titles row 1, TIM/Vivo/Claro row 2, months row 3+), frozen at **`B3`** (header + Month col only), the **active sheet on open**, never protected. The 4 line charts moved to a **new `Charts` sheet** (2×2, tab `#43A047`) referencing the matrix via **cross-sheet refs**. **Fixes the "locked" view**: the symptom was the chart overlay + a 36-row frozen block (`B37`) over a matrix that started at row 35 — the sheet was **never protected**; splitting + freezing only `B3` resolves it. Sheet count 9 → 10. `_write_comparison` returns `(ws, last)`; new `_write_charts`; `_line_chart` now takes (chart_ws, data_ws) for cross-sheet refs; `write_workbook` sets the active sheet. Verified in real Excel: opens on `comparison`, comparison ChartObjects=0 / Charts=4, not protected, Jun-26 row populates. §7 documents the split + the locked-view root cause. Tests 64 → 67.
- **0.4.6 — 2026-06-26** — CODE TASK #16: **comparison matrix converted DAILY → MONTHLY** (the Figure-5 form; presentation/formula only — adapters/schema/scraping/`history` untouched). Rows = month: col A = one first-of-month DATE per distinct month in `history` (`evolution_months` dedupes `snapshot_date` to year-month), display-formatted `mmm-yy`. Each value cell = a **live `_xlfn.MINIFS` over `history`** = **cheapest R$ that carrier offered in that category during the month** (`_minifs_month`), keeping the workbook self-connected; matrix grows one row per month while daily raw stays in `history`. Charts rebuilt to a **monthly X-axis**; per-group heatmap + #11 house style preserved; TIM/Vivo/Claro order kept; same-day idempotency + the #15 alert intact. **Key finding (verified by recalc in real Excel):** `history.snapshot_date` is TEXT, and Excel coerces date/`EOMONTH`/`>=`/`<=` criteria to numerics that never match a text column → those bounds return blank; the month scope therefore uses a **locale-independent MINIFS text-prefix** (`YEAR()&"-"&TEXT(MONTH(),"00")&"-*"`, since pt-BR Excel localizes `"yyyy"`→`"aaaa"`). §7 documents the monthly matrix + the EOMONTH-vs-text-date gotcha. Review copy recalculated in Excel: Jun-26 row populates (Post 119.99/150/124.9, etc.). Tests 60 → 64 (incl. same-month roll-up to one row + Dec→Jan year-boundary).
- **0.4.5 — 2026-06-22** — CODE TASK #15: **daily price-change email alert**. New `mobile_tracker/alerts.py`: a plan whose `price_brl` moves **≥3%** (up/down) vs the previous snapshot (matched by `(carrier, state, plan_id)`, agreeing with the `changes` sheet) → ONE digest email to rafaelxoliver4@gmail.com from ibotatom@gmail.com via `smtplib`/STARTTLS. **Credential only from the `EMAIL_APP_PASSWORD` GitHub Secret** (never in code/config/commits); addresses + threshold in `config/sources.yaml` (`alerts:`). Wired into `main.py` (live only) **fully guarded** — missing password → skip, SMTP error → logged, never fails the scrape/commit. Workflow passes `EMAIL_APP_PASSWORD: ${{ secrets.* }}` to the run step. Console logs ASCII-safe. First fire needs ≥2 snapshots (next run vs today). §2 notes the alert; §5 documents it. Tests 52 → 60.
- **0.4.4 — 2026-06-22** — CODE TASK #14: **production-readiness audit (verification only)** — confirmed the daily 18:00 BRT job will fire correctly from `origin/main`. §5 "Production-readiness verified" note: sync clean, workflow on main with correct config + active (id 300305398), 52 tests green, current matrix/chart code live, and a **manual run succeeded** (52 plans: claro 14 / tim 15 / vivo 23, no block, 1 snapshot — idempotent on the runner; committed 9-sheet styled matrix+charts workbook). Open item logged: no live-output range/sanity check beyond the zero-guard. No code changes.
- **0.4.3 — 2026-06-22** — CODE TASK #13: added **four per-category line charts** (Control/Post/Pre/Digital) in a 2×2 block atop the `comparison` sheet — price over time, TIM/Vivo/Claro palette-colored series, reading from the evolution matrix (→ history), so they grow into trend lines as daily history accumulates. openpyxl native `LineChart`; matrix moved below the chart block; everything else (matrix formulas, Ranking, idempotency) intact. Tests 51 → 52.
- **0.4.2 — 2026-06-22** — CODE TASK #12: **comparison sheet restructured into the price-evolution MATRIX** — Date × (category × carrier), every cell a **live `_xlfn.MINIFS` formula over `history`** (cheapest per carrier/category/date), per-group heatmap color-scale; the validated rank-aligned cross-section preserved on a new **`Ranking`** sheet. Also **fixed same-day idempotency** in `_merge_history` (a re-run of a date now *replaces* that date's rows instead of unioning — kills the local re-run inflation Code flagged). Pre = recharge amount (pending validity-days for true R$/day); monthly roll-up is the planned next step. §7 documents the matrix; §8 keeps the prepaid-normalization + value-lens refinements. Tests 45 → 51.
- **0.4.1 — 2026-06-22** — CODE TASK #11: **visual polish pass** (presentation only — no data/adapter/schema changes). House style applied in `excel_writer.py` so the daily job reproduces it: gridlines off on every sheet, navy header + thin border, row banding, branded tab colors, carrier-sheet sub-header accents; conditional formatting — comparison color-grades the R$ columns + highlights the cheapest carrier per rank, latest/carrier sheets color-scale price per block, promo cells amber-accented. **No buttons/macros/.xlsm** (Bridge's call). §7 documents the design system; §8 adds the price-validation note + comparison refinements (fidelity vs boleto, GB definition, prepaid monthly normalization, R$/GB lens). Tests 40 → 45.
- **0.4.0 — 2026-06-22** — CODE TASK #8: **the daily GitHub Actions job is LIVE and committed history has begun.** `gh workflow` scope authorized; workflow pushed (`pip install -e .` fixes the PYTHONPATH/CI bug; `playwright install --with-deps`); **daily cron 18:00 BRT** (`0 21 * * *` UTC) + on-demand. Synthetic seed cleared; first real snapshot committed by the runner on 2026-06-22 (52 collected / 51 latest, 8 sheets) — **all three carriers scraped from CI** (no datacenter-IP block). **Weekly Monday backup** into `backups/` wired (first: `mobile_plans_2026-06-22.xlsx`). §2 cadence corrected to 18:00 BRT; §5 records the live job + auth-done + PYTHONPATH-fixed; §7 parks the monthly price-evolution heatmap design target. Minor-version bump for the scheduler milestone.
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

## 12. Historical analysis — promo vs entry-level (2023–2026) · CODE TASK #25

First study under the **`analysis/`** component (self-contained; the daily pipeline is untouched).
Deliverables: `analysis/promo_vs_entry/{promo_vs_entry.xlsx, report.md, sources.md, check.py}`.

- **Metric:** `ratio_pct = flagship_promo_price ÷ entry_level_price(same category, carrier, year) × 100`.
  Categories: pré (30-day), controle, pós, digital, combo/convergent. **Anchor rule:** a campaign is
  classified from how its source describes it; convergent combos anchor to entry **pós** (mobile
  component is pós-grade) unless explicitly controle-based (Claro's combos are) — `anchor_category`
  recorded per row. **Flagship rule:** per carrier-year, the campaign pushed hardest / most
  press-covered, pick justified in one line in the `annual` sheet. **Coverage rule (Bridge):**
  2023–2026 target; an unsourceable cell stays visibly blank with a gap note — never estimated,
  never interpolated.
- **Source strategy:** every data point carries URL + access date (37 sources, S01–S37). Wayback
  snapshots of carrier pages parse cleanly for **TIM** (server-rendered Drupal `ofertas` JSON — except
  early-2023, priceless JSON → visible-HTML fallback) and **Claro** (`__NEXT_DATA__` priceData /
  card_360 grids — beware a stale static card block that contradicts press-verified portfolios in
  2023/2024; discarded). **Vivo archives are useless** (AEM/JS 403 shells — recon §3 confirmed) →
  Vivo history rests on press tables (Tecnoblog/Minha Operadora annual-reajuste articles are gold:
  full before/after price tables every Feb–Mar) and archived **aggregator** pages (melhorplano.net,
  SP results; also used for the one TIM-pós-2025 hole). Trade press (Teletime, Minha Operadora,
  Tecnoblog) covers campaigns densely enough that every carrier-year 2023–2026 got a flagship.
- **Results (annual ratio of flagship promo to entry, SP):** TIM 101.9 → 103.8 → 71.2 → **69.2%**;
  Vivo 100.0 → 63.6 → 71.4 → **66.7%**; Claro 300.4 → 120.0 → 83.3 → **236.4%** (Claro's flagships
  alternate site flash offers and convergent combos — anchor visible per row). Entry lists only rose
  (pós +23–25% over the window) while promo prices fell — **promos drifted down-market from
  bonus-GB-at-list (≈100%, 2023–24) to real cuts (59–84%, 2025–26)**.
- **2026 convergence face-off:** TIM **Ultracombo** (2026-07-16, R$89.99 entry = **69%** of entry pós
  129.99) vs Vivo **Total Ultra R$100** (May–Jun promo = **67%** of 150; live site 2026-07-17:
  Essencial R$130 "de 160") vs **Claro Multi** (pós-based 159.90 = **128%** of 124.90; its
  limited-time entry combo is controle-based at 129.80 = 236% of 54.90). TIM+Vivo now price
  fibra+mobile bundles BELOW their own mobile-only entry pós — a first in the series; Claro, the
  2023 convergence pioneer (Multi Week), keeps combos above entry ("more-for-more"). The
  Bridge-reported "new mid-July Vivo convergent launch" was NOT found in any reputable source
  (what exists: the live limited-time Vivo Total repricing + a Jul-14 fiber-only 1-Giga cut).
- **Caveats:** point-in-time annual sampling (intra-year swings in notes); TIM 2023–25 fatura
  headlines carry a 12-mo permanência condition (recorded, noted); TIM controle was cut −15% on
  2026-07-06 *after* the audited 2026-07-01 anchor (noted, not re-anchored); pré 30-day 2023–25
  blank (deriving true 30-day validity from dead pages risks repeating the #18 max-"N dias" bug).
- **Verification:** `check.py` (standalone or pytest) re-reads the xlsx and asserts: every ratio
  recomputes from its two inputs; sanity bands (controle R$35–80, pós R$80–200, ratio 40–400%);
  every non-blank point resolves to a `sources` row; **2026 anchors == the tracker's audited values**
  (controle 58.99/59/54.90-eff; pós 129.99-bill/150/124.90). All green 2026-07-17.
- **Going forward:** the live tracker supplies the 2026 anchors natively and can extend this series
  every year (entry prices per category are exactly what the matrix already computes daily); the §7
  promotions-view backlog item is the natural home for keeping the events log current.

## 13. Convergent offers — English snapshot (2026-07) · CODE TASK #26

One-shot snapshot (NOT a schedule change — the daily config is untouched) of the three carriers'
convergent (mobile + fiber) bundles, SP, in **English**, at
`analysis/convergent_offers/convergent_offers_2026-07.xlsx` (+ `build_workbook.py`, reproducible;
raw captures under `analysis/convergent_offers/raw/` — **local only, not committed**, like `data/raw`).
Sheets: TIM / Vivo / Claro (house style §7, carrier tab colors, gridlines off) + Notes & Sources.
Unified columns: `Mobile Plan | Home Internet | Streaming | Other Benefits | Monthly Price (R$)`;
price cells are **numeric** — TIM's `*` marker is applied via the cell **number format** (`"R$" 0.00"*"`).

- **What was captured (2026-07-17):** **TIM 7 rows** (Ultracombo, launched 07-16; entry **R$ 89.99\***
  = TIM Black Light 65GB + Ultrafibra 500 Mbps) — from TIM's published table, verified against the
  Teletime article; **Vivo 11 combos** (entry **R$ 160** Total Pro 500 Mbps+60GB → **R$ 1,200** V 1 Giga,
  which is REAL: 1 Gbps + 600 GB + 10 additional lines + Vivo TV Completo w/ HBO Max+Telecine; 4 of the
  11 are TV-bundle variants); **Claro 5 combos** (entry **R$ 129.80** Fibra 350 Mbps + Controle 41GB,
  limited-time → R$ 389.90 1 Gbps + Pós 200GB; all include Globoplay).
- **`*` footnote CONFIRMED** (caption of TIM's own table as reproduced by Teletime, not guessed):
  *"Ofertas disponíveis apenas em São Paulo"* = SP-state-only offer; separately, **all** TIM Ultracombo
  prices are valid for **débito automático** payment, and offers vary by region/Ultrafibra availability.
  TIM had **no dedicated Ultracombo page** on 07-17 (three URL probes → 404); Teletime is the source.
- **PARSE-PATH IP — Vivo Total** (`vivo.com.br/para-voce/produtos-e-servicos/combos/vivo-total`):
  same AEM/Akamai behavior as the §3 plan pages (httpx → 403; **Playwright renders fine**, no CAPTCHA)
  and — the useful part — the combo grid is the **SAME `.unique-card` component**: name
  `.unique-card__plan`, price `.total-card-price-value`, fiber speed in `.unique-card__header-benefit`,
  full perks in the card text. SP confirmed via the "São Paulo (SP)" location label. Gotchas: two cards
  share the display name "Vivo Família 2" (differ only by TV package — disambiguate by the bundled TV);
  the 6-app streaming pack is an **optional PAID add-on** (R$ 55→65/mo; 80→95 on Pro; 5-app 45→55 on
  V 1 Giga) and Amazon Prime/Apple Music/Gemini are **time-boxed courtesies** — none are in the price;
  install "mediante fidelização". **Vivo serves session-dependent promo variants:** #25's same-day
  capture saw "Total Essencial R$ 130 (de 160)" / "Ultra R$ 170 (de 190)" where this default headless
  render got "Total Pro R$ 160" / "Ultra R$ 170" flat — record what renders, note the variant.
- **PARSE-PATH IP — Claro Multi** (`claro.com.br/multi`): Next.js like §3, **but** the convergent grid
  is a **`tab_select` component** (tabs "Fibra + Móvel" / "Fibra + TV" / "Fibra + Móvel + TV"), NOT the
  `card_360` (this page's `card_360` holds mobile+**TV-Box** combos — a different product). Per-combo
  **benefits/products ARE in `__NEXT_DATA__`** (`…tab_select.data.data[0].content[0].data.data[]` →
  `products_filter.items[].name` + `detail[]` blocks) but **prices are NOT** (template placeholders +
  catalog ids, hydrated client-side) → **Playwright render required for prices**. The full grid is
  **public** — no CEP/address gate for the listing (SP segmentation is the default: `SEGMENTATION_DEFAULT`
  uf=SP, cityChangedByUser=false). Gotcha: the JSON can list combos the region doesn't render (a
  600 Mbps + Pós 50GB "ghost" combo existed in JSON only) — **trust the rendered set**.
- **Caveats recorded in the workbook's Notes sheet:** limited-time tags (Claro's 350 Mbps combo, Vivo
  Ultra); Vivo install/Wi-Fi conditions; courtesy windows and add-on prices; Claro's program-wide perks
  (up to 35% bill discount, single bill, Claro Clube, Passaporte Américas 46+ countries) stated at
  program level, not per combo; the TIM table's "Paramount" normalized to **Paramount+** per the article.

## 14. Convergent offers — the TRACKED domain (2026-08) · CODE TASK #31 (phase 1)

§13 was a one-shot snapshot. **§14 is the pipeline**: convergent (combo) offers are now a *tracked,
daily* data domain living beside the mobile one — same project, same workbook, **separate schema and
separate sheet**, and rigorously walled off so it can never disturb the mobile pipeline.

### What a convergent offer is
A bundle sold at ONE monthly price: mobile + fixed broadband (+ TV / landline). Structurally unlike a
mobile plan (several services, a fiber speed, a line count, a TV tier), so it gets its own dataclass
`ConvergentOffer` (`src/mobile_tracker/convergent.py`) rather than being forced into `Plan`.

### Schema (`CONVERGENT_COLUMNS`, sheet `convergent_history`)
`snapshot_date · snapshot_ts · carrier · state · offer_name · offer_id · price_brl ·
price_promo_brl · loyalty_months · payment_method · price_note · services · has_mobile ·
has_broadband · has_tv · has_landline · broadband_speed_mbps · mobile_gb · mobile_lines · tv_tier ·
streaming · extra_benefits · data_note · source_url · raw_ref`

- **`offer_id`** — carrier-native, **never price-derived** (same rule as the mobile `plan_id`, §4), so
  a price move reads as a change to the SAME offer, not a new one.
- **`services`** — a derived `"mobile+broadband+tv+landline"` summary built from the four flags
  (canonical order), so the sheet is groupable without re-parsing. It is a `@property`, therefore
  injected explicitly in `as_row()` (it is not in `dataclasses.asdict`).
- **`is_valid()` requires ≥ 2 services** — a single-service "combo" is a plain plan and belongs to the
  mobile pipeline.
- **`payment_method`** — the billing rail the headline assumes (`debit_auto` / `bill`), the same
  dimension as the mobile field (#24) and *distinct from loyalty*: it is context, never a reason to
  prefer a commitment price (§10.5 still governs — headline = the no-commitment monthly price).

### The three SP sources — investigated live 2026-08-03 (this task)
**All three publish DISCRETE, individually-priced tiers — none is a "monte seu combo" configurator.**

| Source | Tech | Access path | Status |
|---|---|---|---|
| **TIM Ultracombo** `/sp/internet/tim-ultracombo` | **plain httpx 200** (Drupal, no browser) | `drupal-settings-json` → `settings["ofertas"]` | ✅ **LIVE** (#31) |
| **Vivo Total** `/combos/vivo-total` | httpx **403 (Cloudflare)** → Playwright | the same `.unique-card` grid as the mobile pages | ✅ **LIVE** (#32) |
| **Claro Multi** `/multi` | **httpx now sufficient** (2-step) | `__NEXT_DATA__` `tab_select` for the grid + ONE public `GET /api/catalog?state=SP&city=sao_paulo&uuids=…` for prices | ✅ **LIVE** (#32) |

Two §13 facts are now **stale and corrected**: TIM's Ultracombo page **exists** (it 404'd on 07-17, so
#26 had to source the tiers from a Teletime article), and Claro's prices **no longer require a browser**
(the catalog API returns them as integer centavos; `precoCombo` when present else `preco`, summed over
slots). Vivo's block is **Cloudflare** now, not Akamai.

### TIM Ultracombo — the implemented parser (`adapters/tim_convergent.py`)
3 tiers on 2026-08-03, each = Ultrafibra + **one** TIM Black line, **no TV/landline**:
**R$ 89,99** (500 Mbps + 65 GB) · **R$ 139,99** (1 Gbps + 70 GB, Paramount+/Deezer) ·
**R$ 169,99** (1 Gbps + 115 GB, Paramount+/Deezer). `offer_id` = the native Drupal `nid`
(`tim:167761/167751/167756`).

Traps this parser is built around (all verified against the live capture):
- ⚠️ **GHOST PRICE FIELDS.** `field_preco_adicional_original` ("Por R$ 129,99") and
  `field_preco_adicional_tracejado` ("De R$ 149,99") are **byte-identical on all three tiers** and
  contradict every real price. The **mobile** TIM adapter reads `field_preco_adicional_tracejado` as a
  genuine struck-through price — reusing that logic here would invent a fake promo on every combo.
  The real price is in **`field_description`** ("Por R$89,99/mês"); `field_preco_card_oferta` (the
  mobile price field) is **empty** on this page. A regression test locks this down.
- ⚠️ **`langcode` lies:** every oferta says `"rj"` (and `about="/rj/node/…"`) although the offers are
  SP-only. Region gating uses **`field_regioes`** (`sp` / `sp-interior`), corroborated by the `[SP]`
  title suffix, `settings["selectedState"]=="sp"` and the `/sp/` path.
- **Payment ladder:** the card headline is the **débito-automático** price; the modal also states a
  higher "por fatura" figure (and a much larger gross "Valor do Plano"). We record the headline,
  tag `payment_method="debit_auto"`, and keep the fatura price in `price_note`.
- **Streaming is icon media**, not text: `field_beneficios_destaque[].name` = "Icone Paramount - TIM
  Ultracombo" (the `<img>` alts are empty). An **empty list is a real absence** (the R$89,99 tier
  bundles none) — "Paramount" is normalized to "Paramount+".
- **Volatility:** the tier set went **7 → 3** in three weeks and the page itself appeared from nothing.
  Treat the offer set as unstable; the #29 id-rotation-resilient change detection applies here too.

### `convergent_history` + the write model (the one real hazard)
`write_workbook` **rebuilds the entire file** (`ExcelWriter` mode `w`), so **any sheet not re-emitted is
destroyed**. Therefore `convergent_history` is **always read and re-written**, even on a run that
collected nothing — a failed or skipped convergent scrape must never wipe previously collected
convergent rows. `_merge_convergent` follows the mobile history contract: a re-run of a
`snapshot_date` **replaces** that date's rows (idempotent), other dates accumulate; identity =
(snapshot_date, carrier, state, offer_id or offer_name). The sheet is deliberately **flat** — no
formulas, no cached-value bake, no charts — so nothing in it can perturb the mobile matrix/bake/charts.

### Guarded wiring into the daily job (§5)
The daily run scrapes convergent **after** the mobile pass, and the whole pass is wrapped so that
**any** failure (import, config, network, parse, merge, sheet write) is logged and skipped without
touching the mobile scrape, the workbook write or the commit — *collection of mobile data > convergent*.
Two layers: per-target `try/except` in `main.run()`, plus `try/except` around the convergent merge and
sheet write **inside** `write_workbook` (so a convergent bug degrades to "keep what we had" instead of
failing the mobile write). `--demo` skips the convergent pass entirely (it is the offline path).
Sources live in `config/sources.yaml` under **`convergent:`** (`active:` per carrier + an `adapter:`
name resolved through `CONVERGENT_ADAPTERS`) — only TIM is active in phase 1.

### Vivo Total — the implemented adapter (`adapters/vivo_convergent.py`, #32)
Playwright (httpx is 403 behind **Cloudflare**), same `.unique-card` component as the mobile pages.
**11 combos on 2026-08-03**, R$160 → R$1,200; **5 carry TV**:

| R$/mo | offer | fibre | mobile | lines | TV |
|---|---|---|---|---|---|
| 160 | Total Pro | 500 Mbps | 60 GB | 1 | — |
| 170 | Total Ultra | 700 Mbps | 70 GB | 1 | — |
| 190 | Total Ultra + TV online | 700 Mbps | 70 GB | 1 | 80 canais Estendido |
| 270 / 330 / 420 / 520 | Total Família 2–5 | 700 Mbps | 120/180/240/300 GB | 2/3/4/5 | — |
| 290 | Total Ultra + TV | 700 Mbps | 70 GB | 1 | 120 canais Avançado |
| 290 / 390 | Família 2 (two TV variants) | 700 Mbps | 120 GB | 2 | 80 / 120 canais |
| **1 200** | **Total V 1 Giga** | 1 Gbps | 600 GB | **11** | TV Completo + HBO Max/Telecine |

- ⚠️ **`offer_id` — the `VIV` code is NOT unique.** 11 cards carried only 9 distinct codes: Ultra
  (R$170) / Ultra + TV online (R$190) share `VIV202604028853`, and Total Família 2 (R$270) /
  Família 2 (R$290) share `VIV202604028085`. The id is therefore the **code + the card's own
  `productsIds` composition** (from `data-external-link-url`, **sorted** so a re-ordered but identical
  bundle keeps one id): `vivo:VIV202604028853-305-313-408-…` vs `…-305-313-336-408-…` (token `336` =
  the TV product). Carrier-native, never price-derived, unique across every observed card. A
  defensive pass appends the name slug then the DOM position if a collision ever survives, so **no
  card is silently dropped**. Use `data-external-link-url`, not the visible CTA `href` (some are stale).
- ⚠️ **Lazy render:** cards below the fold are absent until scrolled — `_scroll_all` wheels down until
  the card count stops growing (bounded). A no-scroll capture silently yields a SHORT list.
- ⚠️ **Hidden price:** the optional "6 apps por R$55/mês" toggle `v-show`s the price element away (or
  shows base+add-on). We never click it; if the text is unusable we fall back to `data-original-price`,
  and if the displayed value differs from the base we record the base and say so in `price_note`. The
  add-on is **never** part of the price. Also: `.unique-card__price` holds an unrendered Vue mustache
  (`Valor R$ {{ total }} 170 /mês`) — the price must come from `.total-card-price-value`.
- **Session variants:** a struck-through `.unique-card__price-old` becomes the headline with the
  displayed price as the promo. **On 2026-08-03 no variant appeared** — all 11 cards were flat
  (`price-old` empty, `data-original-price` == displayed), matching the 07-17 set, so the "Essencial
  R$130 (de 160)" variant §14 recorded was NOT served. The adapter never hard-codes the card count.
- SP asserted positively from the page's own bar (`São Paulo (SP)`); a mismatch warns loudly.
- Loyalty: "instalação grátis mediante fidelização" applies to the INSTALL, not the monthly price →
  `loyalty_months` stays None (CONTEXT §10.5) and the condition is kept in the note.

### Claro Multi — the implemented adapter (`adapters/claro_convergent.py`, #32)
**No browser**: two plain public GETs. **10 live combos on 2026-08-03** (R$129,80 → R$459,80) across
three tabs (Fibra + Móvel / Fibra + TV / Fibra + Móvel + TV); entry = 350 Mbps + Controle 40GB.

- **Grid** — `__NEXT_DATA__` → the component whose `component == "tab_select"` (**found by name, never
  by index**: the page also carries a `card_360` of a different product line); each card's `_uid`
  (Storyblok UUID) is the `offer_id` — native, stable across price edits, never price-derived.
- **Prices** — ONE batched `GET /api/catalog?state=SP&city=sao_paulo&environment=public&component=card_360&uuids=<all>`
  (the page itself only asks for the active tab; batching keeps us to a single polite call).
  **price = Σ over slots of (`precoCombo` if the KEY IS PRESENT else `preco`), integer centavos.**
  ⚠️ `precoCombo` is **absent (not null)** on `internet` for every Fibra+TV card — a falsy-default read
  would drop the fibre component and under-price those three combos by R$99,90–179,90.
- ⚠️ **Ghosts excluded:** 5 of the 15 CMS cards come back `catalog: {"notFound": true}` — listed but
  not sold in SP. They have no price at all; the rendered/priced set is the truth.
- **Names/fields from `catalog.<slot>.nomeAutomatico`, not the CMS text** (which is stale: "Controle
  41GB" where the priced product is 40GB). Speed from `recursosDescritivos["602"]` ("350 Mbps").
- **SP is an explicit input** (`state=SP&city=sao_paulo`) — stronger than the geolocated default the
  mobile Claro adapter relies on; the segmentation cannot drift with the egress IP. The city slug is
  config-driven (`convergent.claro.api_city`) with a state→city fallback map.
- `acrescimoNaoDCC` (R$5 on the Controle 40GB entry tier, 0 elsewhere) = a surcharge for NOT paying by
  débito em conta → `payment_method="debit_auto"` + the surcharge in `price_note`. A billing rail, not
  a loyalty commitment.

### Three-target guarded wiring (#32)
All three sources are `active: true` in `convergent:`. The guards from #31 are unchanged and verified
with three targets: **per-target** `try/except` in `main.run()` (a failing carrier is logged and
skipped while the others still collect), **plus** `try/except` around the convergent merge and sheet
write inside `write_workbook`, **plus** the always-read-and-re-emit of `convergent_history`. A test
proves one source exploding still lets the other two and the mobile write complete.

**Live end-to-end 2026-08-03: 24 offers** — TIM 3 (R$89,99–169,99) · Vivo 11 (R$160–1 200) ·
Claro 10 (R$129,80–459,80), with the mobile history (2 336 rows / 42 snapshots) untouched.

### `convergent_comparison` — the combo evolution matrix (#33, phase 3)
The combo equivalent of the mobile `comparison` (§7), and built the same way: **rows = one per
`snapshot_date`** in `convergent_history` (earliest first, auto-growing, `dd-mmm`), **columns =
BUNDLE-TYPE groups**, each split **TIM | Vivo | Claro**; every value cell is a **live exact-date
`_xlfn.MINIFS`** over `convergent_history` with the **cached value baked** beside it (#21), so the
committed file displays everywhere while Excel still recalculates.

**Bundle types (the comparison axis).** A new derived column `bundle_type` on `convergent_history`,
computed from the existing service flags — **no extra scraping**:
`Fibre + Mobile` · `Fibre + TV` · `Fibre + Mobile + TV`. It is a pure function of the flags, so rows
written before the column existed are **backfilled on the next write** (`_backfill_bundle_type`),
exactly as the mobile column additions self-healed in #18 — otherwise the matrix would be blank for
every past date. A shape outside the canonical three (say `Mobile + TV` with no fibre) gets a
descriptive label and **its own column group**, appended by `convergent_bundle_types`, rather than
being folded into an existing one.

**Why cheapest WITHIN a type, not cheapest overall** (the Bridge's call): carriers sell very different
things under one "combo" banner — a fibre+TV bundle is not a competitor to a fibre+mobile one, so a
single "cheapest combo" column would compare unlike with unlike and would flip meaning whenever a
carrier launched a cheaper but thinner bundle. Comparing within a type keeps every column like-for-like.

**A blank cell means the carrier sold no combo of that type that day** — an honest gap, never a 0
(the formula maps a 0/no-match to `""`, and the bake simply omits the coordinate).

**Observed spread (2026-08-03, 24 offers):**

| carrier | Fibre + Mobile | Fibre + TV | Fibre + Mobile + TV |
|---|---|---|---|
| **TIM** | 3 | — | — |
| **Vivo** | 6 | — | 5 |
| **Claro** | 4 | 3 | 3 |

…giving the first matrix row: Fibre + Mobile **TIM 89,99 / Vivo 160 / Claro 129,80** · Fibre + TV
**Claro 219,80** only · Fibre + Mobile + TV **Vivo 190 / Claro 259,80** (TIM blank — it sells no TV
combo). **No fourth bundle type appeared.**

**Verification:** `_conv_matrix_value` mirrors `_conv_minifs_day` exactly (the `_matrix_value`
discipline); an **Excel COM full recalc compared all 18 cells against the baked values — 0
mismatches**, and blanks stayed blank. `convergent_history.snapshot_date` was **confirmed** to be
stored as TEXT (`data_type='s'`), like the mobile history, so the same locale-safe text-date
construction is required and used.

**Graceful degradation:** the matrix is built inside its own `try/except` **nested within** the
convergent guard — a matrix failure keeps the collected `convergent_history` sheet, leaves
`conv_values` empty (so the fail-loud bake check can't abort the run over a skipped side sheet), and
never touches the mobile write. Tested.

**Next (phase 4, optional):** charts for the convergent matrix (the `Charts`-sheet treatment), and/or
a convergent price-change alert.
