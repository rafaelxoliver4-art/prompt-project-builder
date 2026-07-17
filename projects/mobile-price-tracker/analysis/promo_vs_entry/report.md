# Promo-vs-entry study, 2023–2026 (São Paulo) — CODE TASK #25

> Flagship promotional campaigns of Vivo / Claro / TIM as a % of the same-category
> entry-level plan price, one annual point per carrier, 2023→2026. Every number is sourced
> (URL + access date in [sources.md](sources.md) and the workbook's `sources` sheet); gaps
> stay blank. Built 2026-07-17. Deliverables: `promo_vs_entry.xlsx` (annual / events /
> entry_prices / sources / Chart), this report, `sources.md`, `check.py`.

## Method

- **Metric:** `ratio_pct = flagship_promo_price ÷ entry_level_price(same category, same carrier, same year) × 100`.
- **Categories:** pré (30-day), controle, pós, digital (lite/flex/fit), combo/convergent.
- **Anchor rule:** each campaign is classified from how the source describes it; the divisor is
  that category's entry-level (cheapest) plan price for that carrier-year. Convergent combos
  anchor to entry **pós** (their mobile component is pós-grade) unless the campaign is
  explicitly controle-based (Claro's combos are); `anchor_category` is recorded per row.
- **Flagship rule:** per carrier-year, the campaign the carrier pushed hardest / the press
  covered most; the pick is justified in one line in the `annual` sheet.
- **Entry-price conventions** (consistent with the live tracker's capture rules): advertised
  effective price (débito-automático price for Claro, recorded with the regular pair);
  bill-payment ("na fatura") over credit-card-only tiers for TIM (the task's JPMorgan rule);
  no loyalty-priced headline (a 12-mo-fidelização offer on Claro's 2023 page was excluded per
  Bridge rule §10.5). TIM's 2023–2025 fatura headlines carry a 12-mo permanência *discount*
  condition — recorded as advertised, condition in notes.
- **Coverage rule (Bridge):** target 2023–2026; a year that can't be sourced is a documented
  gap, never an estimate. Achieved: **controle and pós complete for all 12 carrier-years**;
  digital complete except TIM 2023–2025 (structural — the Fit line only launched Jul-2026);
  pré 30-day only for 2026 (gap note in `entry_prices`).
- **One representative point per year** (mid-year where sources allow; exact snapshot/article
  date recorded per data point). 2026 anchors = the tracker's audited 2026-07-01 values
  (CODE TASKs #22–#24), cross-checked against `data/mobile_plans.xlsx` history.

## Annual series

| Year | Carrier | Entry controle | Entry pós | Flagship campaign | Promo R$ | Anchor | Ratio |
|---|---|---|---|---|---|---|---|
| 2023 | TIM | 51.99 | 104.99 | Black Friday — Controle 33GB | 52.99 | controle 51.99 | **101.9%** |
| 2023 | Vivo | 52.00 | 122.00 | Dia do Consumidor (bonus up to +20GB) | 52.00 | controle 52.00 | **100.0%** |
| 2023 | Claro | 49.90 | 99.90 | Multi Week (entry combo, 500M+Controle 20GB) | 149.90 | controle 49.90 | **300.4%** |
| 2024 | TIM | 52.99 | 119.99 | Dia das Mães (+20GB bonus) | 54.99 | controle 52.99 | **103.8%** |
| 2024 | Vivo | 55.00 | 130.00 | Flash sale — Controle 20GB R$35 | 35.00 | controle 55.00 | **63.6%** |
| 2024 | Claro | 49.90 | 109.90 | Site Oferta Relâmpago — Controle 22GB | 59.90 | controle 49.90 | **120.0%** |
| 2025 | TIM | 58.99 | 105.99 | App-only Controle 33.5GB R$41.99 | 41.99 | controle 58.99 | **71.2%** |
| 2025 | Vivo | 59.00 | 140.00 | Vivo Total Essencial R$100 (500M+20GB) | 100.00 | pós 140.00 | **71.4%** |
| 2025 | Claro | 59.90 | 119.90 | Site Oferta Relâmpago — Controle 25GB | 49.90 | controle 59.90 | **83.3%** |
| 2026 | TIM | 58.99 | 129.99 | **Ultracombo** (65GB+500M, entry tier) | 89.99 | pós 129.99 | **69.2%** |
| 2026 | Vivo | 59.00 | 150.00 | **Vivo Total Ultra R$100** (700M+70GB) | 100.00 | pós 150.00 | **66.7%** |
| 2026 | Claro | 54.90 | 124.90 | Claro Multi entry combo (350M+Controle 41GB) | 129.80 | controle 54.90 | **236.4%** |

Digital entry (context): Vivo 29.90 → 33 → 33 → 35; Claro Flex 29.99 → 34.99 → 44.99 → 44.90
(+50% over the period — the fastest-rising category); TIM Fit launched Jul-2026 at 35.

## Per-carrier narrative, 2023 → 2026

**TIM — from data-bonus promos to buying share with price.** In 2023–2024 TIM's promo lever
was almost purely *data inflation*: Black Friday 2023 and Dia das Mães 2024 sold more GB at
(or slightly above) the entry price — ratios ~100–104%. The posture flipped in late 2025: the
app-only Controle at R$41.99 (71% of entry) was TIM's deepest mobile discount of the period,
and 2026 escalated on both fronts — a −15% across-the-board Controle repricing on Jul-06
(58.99→49.99, caught by our tracker as the #29 id-rotation event) followed ten days later by
the **Ultracombo**: a fibra+mobile+streaming bundle whose entry tier (R$89.99) undercuts TIM's
own entry pós by 31%.

**Vivo — earliest to discount, always via commitment-free levers.** Vivo ran the highest
entry prices all four years (pós 122→150, +23%) and was the first to break the ~100% promo
pattern: the Sep-2024 flash Controle at R$35 (64% of entry) was the sharpest mobile promo of
2024 across all carriers. From late 2025 Vivo's flagship lever became the convergent
**Vivo Total Essencial/Ultra at R$100** (71% → 67% of entry pós as the pós anchor rose), plus
a Feb-2026 "cheapest controle ever" (45GB, R$35 = 59% of entry). Vivo discounts hard on
promos while ratcheting list prices up every February–March.

**Claro — stable list prices, convergence as the standing pitch.** Claro's entry pós rose in
clean R$10 steps (99.90→109.90→119.90→124.90) and controle stayed in a narrow band —
the Jan-2024 "On" relaunch actually *cut* the advertised entry back to 49.90. Claro's
flagship promos alternate between site-exclusive "Oferta Relâmpago" flash offers (120% →
83% of entry as list prices rose past the flash price) and convergent bundles: it was the
*first* of the three to make convergence its flagship (Multi Week, Jul-2023) and its combos
have always priced *above* mobile entry (300% in 2023, 236% in 2026) — bundle value framed
as "more for more", unlike the 2026 TIM/Vivo bundles that price *below* entry pós.

## 2026 convergence face-off (as of 2026-07-17)

| | TIM Ultracombo | Vivo Total | Claro Multi |
|---|---|---|---|
| Launched | 2026-07-16 (Teletime) | standing line; R$100 Ultra promo May–Jun 2026 | standing program; limited-time entry combo live |
| Entry tier | R$89.99 — 65GB + 500Mbps (déb. automático) | R$100 (promo, closed) — 70GB + 700Mbps; live today: Essencial R$130 (60GB+500M, "de 160"), Ultra R$170 (70GB+700M, "de 190") | R$129.80 — Controle 41GB + 350Mbps + Globoplay (limited-time); cheapest pós-based: R$159.90 (60GB+600M) |
| Streaming | Globoplay/Paramount+ on select tiers; TIM Play platform launched Jul-07 (R$9.90+) | apps add-on (6 apps R$55/mês offer); Netflix variant on Essencial | Globoplay included |
| Savings claim | "up to 40% vs separate" | "up to 40%" (site) | "up to 35% on the bill" |
| Ratio vs own entry pós | **69.2%** (89.99 / 129.99) | **66.7%** (100 / 150, May promo); live Essencial = 86.7% (130/150) | **128.0%** (159.90 / 124.90, pós-based); entry combo is controle-anchored: 236.4% of entry controle |
| Region | partly SP-exclusive; varies with Ultrafibra footprint | fibra footprint | fibra footprint |

The striking 2026 fact: **TIM and Vivo now price a fibra+mobile(+streaming) bundle *below*
their own mobile-only entry pós** — convergence used as an acquisition discount, not an
upsell. Claro, the convergence pioneer of 2023, is the only one whose combos still price
above mobile entry. The Bridge-reported "new Vivo convergent offer days before Ultracombo"
could **not** be verified as a new launch in any reputable source — what exists mid-July is
the live limited-time repricing of the standing Vivo Total tiers (Essencial R$130 "de 160")
plus a fiber-only 1 Giga cut (2026-07-14, to R$200); the verifiable Vivo convergence
flagship of 2026 remains the May–June R$100 Ultra promo. Reported as found, per the
no-guessing rule.

## Findings

1. **Promos drifted decisively down-market.** Median flagship ratio: ~102% (2023) → ~104/64/120%
   (2024, split) → ~71–83% (2025) → ~67–69% mobile-anchored (2026). In 2023–2024 a "flagship
   promo" meant more GB at list price; by 2025–2026 it means 17–41% off a real price.
2. **The July-2026 combo wave is a genuine break.** 2023's convergence (Claro Multi Week 300%,
   Vivo Total Essencial 139% of pós) priced bundles *above* mobile entry. In 2026 TIM (69%)
   and Vivo (67%) price bundles *below* entry pós — within days of each other — while Claro
   held the "more-for-more" model (128%).
3. **Entry list prices only went up — promo prices went down.** Entry pós rose ~24% (TIM
   105→130), ~23% (Vivo 122→150), ~25% (Claro 100→125) over the window, while each carrier's
   deepest advertised promo fell (TIM 52.99→41.99-equivalent; Vivo 52→35; Claro's flash held
   ~49.90 as lists rose past it). The spread between list and promo is where the competition
   moved.
4. **Digital is the quiet price-riser:** Claro Flex +50% (29.99→44.90) and Vivo Easy +17%
   (29.90→35) with no promo activity — the entry-tier categories absorb the increases the
   headline promos hide. TIM finally entered the class in Jul-2026 (Fit, R$35).
5. **TIM's 2026 pivot is the sharpest single-carrier shift** in the series: −15% controle
   repricing (Jul-06) + Ultracombo at 69% of entry pós (Jul-16) + the TIM Play streaming
   platform (Jul-07) — three aggressive moves in ten days, after three years of ~100%-ratio
   bonus-GB campaigns.

## Caveats

- **Coverage gaps (visible, not filled):** pré 30-day 2023–2025 (deriving true 30-day
  validity from archived pages risks repeating the #18 max-"N dias" error the audit fixed);
  TIM digital 2023–2025 (line didn't exist). See `entry_prices` gap rows.
- **Wayback + JS:** Vivo's own pages are useless in the archive (AEM/JS, 403 to crawlers —
  confirmed by a 2024 probe); Vivo history rests on press tables (Tecnoblog/Minha Operadora)
  and archived aggregator pages (melhorplano.net, flagged in notes). TIM-pós-2025 likewise
  rests on an archived aggregator page — lower confidence than carrier pages.
- **Two-regime years:** point-in-time annual sampling hides intra-year swings. Claro's 2023
  page carried both a 49.90 grid and a stale-looking 69.90–94.90 card block (discarded as
  stale — it contradicts the press-verified Jan-2024 portfolio in the 2024 snapshot too);
  TIM cut controle −15% *after* our 2026-07-01 anchor date (noted, not re-anchored).
- **Promo-vs-effective nuances:** Claro's entry prices are débito-automático effective prices
  (regular pair recorded where shown); TIM 2023–2025 fatura headlines carry a 12-mo
  permanência discount condition (no-permanência price R$20–50 higher, in notes); bonus-GB
  campaigns (TIM 2023/2024, Vivo 2023) have ratio ≈100% by construction — the discount is
  in-kind (data), not in price.
- **Geography:** SP throughout (TIM `/sp/` URLs; Claro geo-defaults to SP; Multi Week prices
  SP-city; tracker is SP). Aggregator pages state SP results. National press tables may not
  be SP-specific — treated as SP-applicable (carriers price these portfolios nationally).
- **Ratios compare advertised prices,** not effective unit economics (a 33GB promo at 101.9%
  of a 19GB entry plan is *better value per GB* — the study measures price positioning, not
  value).

## Sources

Full list with URLs and access dates: [sources.md](sources.md) and the workbook `sources`
sheet (S01–S37). Verification: `check.py` re-reads the workbook, recomputes every ratio,
enforces sanity bands (controle R$35–80, pós R$80–200, ratio 40–400%), asserts every data
point has a source row, and asserts the 2026 anchors equal the tracker's audited values.
