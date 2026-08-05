# Full verification audit — scraped data, comparison tables, alerts (CODE TASK #35, 2026-08-04/05)

**Method (read-only, GOVERNANCE-polite):** ONE live pass over every São Paulo source
(`python -m mobile_tracker.main`, 2026-08-04 — claro 20 / tim 17 / vivo 26 mobile plans + TIM 3 /
Vivo 11 / Claro 10 convergent offers), raw captures saved to `data/raw/`. Every capture was then
**re-parsed independently** (selectolax / raw JSON — *not* through the adapters) and compared to what
the workbook stores. No parser, matrix or alert code was changed in this task. No number here is
guessed: anything unparseable is reported as such.

Supersedes `source_audit_2026-07.md` (#22), which predates #23, #24 and the whole convergent domain.

---

## 0. Headline

| Area | Verdict |
|---|---|
| Mobile capture (11 targets) | Mostly MATCH — **3 material defects**, one of them a **BLOCKER** |
| Convergent capture (3 pages) | **No drift**: TIM 3 / Vivo 11 / Claro 10 live + 5 ghosts — prices all MATCH |
| Comparison matrices | ✅ **history == formula == bake, every cell, both matrices** |
| Price alerts | Work, and **have fired in production** — but **mobile-only**, and the one email ever sent was **FALSE** |
| Daily CI job | ✅ 12/12 recent runs green |

**The single most important finding: the only price alert this project has ever sent (2026-08-03,
"TIM Controle Fit −42.9% / −33.3%") was a FALSE ALERT caused by our own parser, not a TIM price cut.**

---

## 1. Confirmed CORRECT (the #23/#24 fixes hold)

| Item | Verified against the capture |
|---|---|
| **TIM prepaid per-plan validity** (#23) | Capture literally reads *"6GB R$20, válidos por **17 dias**"*, *"8GB R$25, válido por **22 dias**"*, *"16GB R$30, válido por **30 dias**"*; workbook holds 17 / 22 / 30. The shared 30-day marketing line is still present in every oferta but no longer wins. **MATCH** |
| **Vivo Lite no-commitment headline** (#23/#26/#30) | The toggle click **succeeded** — this is NOT the #30 failure mode. 30GB: displayed 45, `data-original-price` 30, `loyalty_months`=12. 40GB: 55/40/12. The 20GB (R$35) card genuinely has **no toggle** (no radio fieldset, no "Sem fidelidade" text), so its blank loyalty is correct. **All 3 MATCH** |
| **TIM postpaid `payment_method`** (#24) | All **7** plans agree with `field_preco_principal_7_1_3`: "/mês no cartão" → `credit_card` (55121, 52146, 52151); "/mês na fatura" → `bill` (54206, 54256, 54261, 100581). **MATCH** |
| **Convergent prices** | TIM 89,99 / 139,99 / 169,99 · Vivo 160 → 1 200 (11 combos, 5 with TV) · Claro 129,80 → 459,80 (10 live, 5 `catalog.notFound` ghosts correctly excluded). Ghost price fields did **not** leak into TIM's price/promo. **No drift vs #32.** |
| **Both comparison matrices** | See §4 — perfect three-way agreement. |
| **Alert plumbing** | ≥3 % rule, digest format, secret handling and graceful degradation all verified — see §5. |

### São Paulo confirmation (all 12 sources)
- **Claro** (strong): `__NEXT_DATA__ SEGMENTATION_DEFAULT = {"name":"São Paulo","uf":"SP","ddd":"11","cityChangedByUser":false}`; `SP` is the only UF anywhere in the capture. Convergent additionally pins SP **as an explicit API input** (`state=SP&city=sao_paulo`).
- **Vivo** (strong): the rendered active-city label "São Paulo (SP)"; the only `(UF)` token present.
- **TIM** (weaker than #22 claimed): the `/sp/` path appears only in nav/form actions and **`rel=canonical` is state-less**; the page ships every region's Fit content in one document. Plan-level proof is `field_regioes` containing `sp`/`sp-interior` on every captured oferta — which is what the ofertas parser gates on, so mobile TIM is SP-correct. **But the Fit parser does not gate on it** (see 2.1).

---

## 2. MISMATCHES — mobile

### 2.1 🔴 BLOCKER — TIM Fit "price drop to R$20" is a parser tier-substitution, and it produced the only alert ever sent
On ~2026-08-03 TIM restructured the `#price-fit` section into **two regional blocks × two tiers**:
```
modal-fit-anual-1.0-sp-sc-rn-ce    modal-fit-anual-2.0-sp-sc-rn-ce
modal-fit-anual-1.0-demais-ufs     modal-fit-anual-2.0-demais-ufs      (+ the 4 mensal equivalents)
```
Two independent breakages followed, both confirmed:

1. **Wrong tier captured.** The page now carries **8** price phrases; the parser's first-match regex
   latched onto a newly inserted **"1.0"** card — a *different* offer — instead of the tracked tier:
   `Tenha 25GB por 12x R$20/mês` (taken) vs `Tenha 30GB por 12x R$30/mês` (the tracked 2.0 Anual);
   `Tenha 20GB por R$20/mês` (taken) vs **`Tenha 20GB por R$35/mês` — still present on the page**.
2. **Stable id lost.** `_fit_code` looks for exactly `modal-fit-anual` / `modal-fit-mensal`, which
   **no longer exist**, so `plan_id` fell back from the carrier-native etiqueta to a name slug:
   `tim:TIM202600000271 → tim:fit-anual`, `tim:TIM202600000270 → tim:fit-mensal` — on 2026-08-03, the
   exact date the alert fired. The #29 name-rotation fallback then paired old↔new and manufactured a
   price move.

The Mensal R$20 is contradicted **by the source's own benefits modal** ("R$35,00/mês … Preço mensal
R$35 por mês no cartão de crédito") and by the same offer code's *demais-UFs* card. Per GOVERNANCE
the value is **reported, not adjusted**: `tim/fit` R$20 rows for 2026-08-03/04 are **not trustworthy**.

Also: the Fit parser has **no region gating** (it gets SP only by DOM order) and silently records
**1 of the 2 SP tiers** per plan type; and `loyalty_months=12` on Fit Anual is contradicted by every
Fit etiqueta in today's capture, which reads *"sem prazo de permanência"*.

### 2.2 🟠 HIGH — Vivo Controle: 7 of 8 headline prices include a **pre-checked R$5 add-on**
The Vivo Controle cards ship a *"+ 10 GB para suas redes sociais … R$ 5"* checkbox **already checked**,
so `.total-card-price-value` shows base+add-on while the true base sits in `data-original-price`:

| card | captured | real base |
|---|---|---|
| Vivo Controle 46GB | 59 | 59 ✓ |
| Vivo Controle 61GB | **80** | 75 |
| Saúde / Educação / YouTube Lite / Música | **90** | 85 |
| Netflix | **95** | 90 |
| Entretenimento | **110** | 105 |

This is also the root cause of the **alert noise** in §5: because `plan_id` embeds the parsed GB, the
same offer flips between `…-61gb` (R$95) and `…-51gb` (R$90) depending on whether the add-on rendered
checked — producing −5.26 % / +5.56 % alert lines that reverse the next day, forever.

### 2.3 🟠 HIGH — a Claro Controle card is **silently dropped** by a cross-category id collision
`_merge_history` dedupes on `(snapshot_date, carrier, state, _key)` — **`category` is not in the key**.
The Claro *Controle* page legitimately yields 4 plans, but `claro:plano-flex-20gb` ("Controle 20GB",
**R$ 44,90**) shares an id with the Flex-page row, so the control row is dropped:

```
parsed from the control capture : 4   (…-25gb 59,90 · …-30gb 69,90 · …-30gb-gaming 99,90 · plano-flex-20gb 44,90)
stored in `latest`              : 3   → DROPPED: claro:plano-flex-20gb
```
A real observed price vanishes with no error. (Also noted: TIM Controle's list/regular price is still
uncaptured — the promo gap from #22 remains, now widened by today's lineup refresh.)

### 2.4 Lower severity
- `plan_name` carries a marketing artifact: *"TIM Controle Premium 55GB **fs/ro**"* (raw title `… - fs/ro - [PROD]`; `_clean_title` strips `[PROD]` but not `fs/ro`).
- TIM Black Premium 110GB: card price 159,99 contradicts its own headline 169,99 *in the same JSON*.
- Claro postpaid GeForce card: title says 50GB, native slug says `60gb`.

---

## 3. Adversarial review — the two never-reviewed phase-2 adapters

### `vivo_convergent.py` (17 findings)
- 🔴 **BLOCKER — `_price_from()` treats every `.` as a thousands separator.** A dot-decimal in
  `data-original-price` yields a **100× price**. Reachable through the add-on fallback path.
- 🟠 **`_scroll_all` can silently return a SHORT list** — one stalled 600 ms window ends the loop and
  nothing asserts the card count; 4 offers instead of 11 would be recorded as fact.
- 🟠 **`offer_id` is not stable**: it changes if the carrier edits the CTA deep-link/`productsIds` or
  the code element — fabricating remove+add; and a DOM re-order can hand one id to a *different*
  offer. The VIV code is also taken by an **untargeted regex over the whole card**.
- 🟠 Losing the fibre selector **reclassifies** half the grid instead of failing (6 offers vanish).
- 🟡 `elif` in the benefit loop can drop TV, moving a TV bundle into the Fiber+Mobile group — the one
  group the comparison matrix shows. Wrong-city render is a `print()` only. Two bare `continue`s
  swallow a card silently. `_save_raw` overwrites one fixed path, so every historical `raw_ref`
  points at today's bytes.

### `claro_convergent.py` (14 findings)
- 🟠 **The ghost rule absorbs every catalog-side failure**: a live offer whose catalog entry is
  missing/erroring is deleted and logged as a "ghost".
- 🟠 **`_PRICED_SLOTS` is a closed list** — a new/renamed priced slot is silently omitted from the
  total (under-pricing the combo).
- 🟡 `precoCombo: null` discards a component that has a valid `preco`; no unit guard (a
  reais-denominated float would under-price ~100×); `tab_select` located by `next(...)` so a second
  one silently replaces the grid; `convergent.claro.api_city` overrides the state map **for every
  state**; loyalty/promo dimensions never read.
- 🟡 `_get` retries HTTP 4xx/403, contradicting the project's own no-retry-on-block policy.

---

## 4. Comparison matrices — ✅ PERFECT AGREEMENT

Every cell of **both** matrices was recomputed independently in pandas from `history` /
`convergent_history` (a fresh implementation of the §7/§14 rules), then compared against the **baked**
value and against the **live formula recalculated in real Excel via COM**:

> **history == formula == bake for every cell, both matrices. Zero disagreements.**

TV-bearing offers correctly do **not** leak into the Fiber+Mobile column; the mobile picks are what a
human would call entry-level.

Caveats found while checking (not disagreements — semantics):
- 🟠 The two blank `convergent_comparison` cells on 2026-08-03 are a **collection gap** (Vivo/Claro
  convergent were not yet active) presented as a market absence. The sheet's footnote asserts "sold no
  such combo that day", which the data cannot support.
- 🟡 Four post-#23 days exist where Vivo's toggle silently failed and the **loyalty** price was stored
  as the headline — the #30 guard was added after them.
- 🟡 Claro Control reports the **regular** price while the site headlines the discounted one.

---

## 5. Price alerts — what they do and do NOT cover

**Verified working:** the ≥3 % rule reproduces exactly (independent pandas recompute == 
`compute_price_alerts` == the `changes` sheet); digest subject/body/sorting correct; the SMTP password
is read **only** from `EMAIL_APP_PASSWORD` (no literal anywhere; `.gitignore` blocks `.env`/`*.key`);
missing password, SMTP failure, bad config and an unreadable workbook **all degrade gracefully** and
`main.py` still returns 0 — an alert failure can never fail the job or block the daily commit.

**Has it ever fired?** **Yes, once** — 2026-08-03, "2 change(s) ≥3% - email sent". **And it was a false
alert** (§2.1). Today's run produced 3 more (the genuine TIM Controle cuts).

**Coverage — definitive answer: MOBILE ONLY.**
`alerts_from_workbook` hardcodes `sheet_name="history"`. `convergent_history` is **never read**, and
`compute_price_alerts` reads `plan_id`/`plan_name`/`price_brl`, which convergent rows don't have
(`offer_id`/`offer_name`). **A Vivo Total combo going R$160 → R$200 sends no email.** The 21 convergent
offers that first appeared on 2026-08-04 generated zero notification. Also uncovered: **new/removed
plans** (4 new Vivo postpaid plans today — not mentioned), and any move on a sanity-fail day.

**Noise (the bigger practical problem).** Replaying all 43 day-pairs: **19 of 43 days (44 %) would have
emailed, 109 lines total — 86 of them (79 %) the Vivo Controle add-on/GB render flip** that reverses
the next day. Two structural risks in the #29 fallback: it can **pair two genuinely different plans**
(176 non-unique name groups exist; demonstrated "Vivo Lite R$35 → R$75 +114 %"), and it **silently
skips** a synchronised rotation across a duplicated-name family.

---

## 6. Daily job + committed workbook

- **12/12 recent scheduled runs green** (2026-07-23 → 2026-08-03), 2m41s–3m23s.
- `origin/main` workbook is current for **mobile** (2 394 rows / 43 snapshots, latest 2026-08-03) with
  baked values displaying.
- ⚠️ **The convergent domain is barely in production**: the committed `convergent_history` holds
  **3 rows (TIM only, 2026-08-03)** — Vivo/Claro were activated (#32) *after* that day's run — and
  **`convergent_comparison` does not exist in the committed workbook at all** (#33/#34 landed after).
  The first CI run to include all three carriers + the matrix is the next scheduled one.

---

## 7. Prioritized fix list

| # | Pri | Fix |
|---|---|---|
| 1 | 🔴 **P0** | **TIM Fit parser**: match the region-scoped modal ids (`…-sp-…`), gate on `field_regioes`, capture **both** SP tiers, restore the etiqueta `plan_id`, and re-derive `loyalty_months` from "sem prazo de permanência". Quarantine/annotate the false 2026-08-03/04 R$20 rows. |
| 2 | 🔴 **P0** | **`vivo_convergent._price_from` 100× bug** — dot-decimal parsing. |
| 3 | 🟠 P1 | **Vivo Controle add-on**: use `data-original-price` as the headline (never the pre-checked add-on), which also removes ~79 % of alert noise. |
| 4 | 🟠 P1 | **Add `category` to the `_merge_history` dedupe key** — stops silent cross-category row loss. |
| 5 | 🟠 P1 | **Stabilise Vivo mobile `plan_id`** (stop embedding volatile `data_gb`). |
| 6 | 🟠 P1 | **Extend alerts to convergent** + add new/removed lines; tighten the #29 fallback (global name-uniqueness + a corroborating attribute; print the re-keyed ids). |
| 7 | 🟡 P2 | Vivo convergent: assert the card count / fail loud on a short scroll; scope the VIV regex; stop overwriting `raw_ref` captures. |
| 8 | 🟡 P2 | Claro convergent: separate "ghost" from "catalog failure"; open `_PRICED_SLOTS`; honour `precoCombo: null`; don't retry 4xx. |
| 9 | 🟡 P2 | Strip the `fs/ro` title artifact; capture TIM Controle's list price; align the convergent blank-cell footnote with what the data can support. |
