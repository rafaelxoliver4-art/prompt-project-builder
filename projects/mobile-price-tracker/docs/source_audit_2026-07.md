# Source-of-truth audit — scraped SP data vs live carrier sites (CODE TASK #22, 2026-07-01)

**Method (read-only, GOVERNANCE-polite):** one live fetch of all three carriers' São Paulo pages
(`python -m mobile_tracker.main`, 2026-07-01 — claro 20 / tim 15 / vivo 21 plans), raw captures saved to
`data/raw/`, then each raw page compared **field-by-field** to what the current adapters parse into
`history`/`latest`. No adapter/schema/matrix change in this task — findings drive the fixes next.

## 1. Region — every source is São Paulo ✅ (and how verified)

| Carrier | How SP is selected | SP confirmation (from the raw capture) |
|---|---|---|
| **TIM** | state in the URL path (`/sp/…`, config-templated) | `/sp/` in the fetched URL; plan `ofertas` come from that path. (Other states appear only in the state-picker nav — not in the plan data.) |
| **Claro** | geolocation, default SP | `__NEXT_DATA__` → **`SEGMENTATION_DEFAULT: {name:"São Paulo", uf:"SP", ddd:"11", slug:"sao-paulo-SP", cityChangedByUser:false}`**. ("Salvador"/"El Salvador" hits are only nav links — *"Internet em Salvador"*, a GTM label — not the active city or prices.) |
| **Vivo** | geolocation, default SP | active-city label **`São Paulo (SP)`** rendered: *"Verificamos que você está em São Paulo (SP)"* + a "Trocar localização" control. |

Claro/Vivo mobile plan prices are effectively national, but the pages are confirmed **segmented/geolocated to SP** regardless. No page defaulted to another city.

## 2. MATCH / MISMATCH table (live SP site vs what we capture)

| Carrier | Category | On the site (cheapest / key) | What we captured | Verdict |
|---|---|---|---|---|
| Claro | postpaid | Pós 60GB **R$124,90** (…→R$339,90) | 124,90 … 339,90 | ✅ MATCH |
| Claro | control | Controle 25GB **R$59,90 → R$54,90** (fatura+conta digital); 30GB 69,90 / 99,90 | regular 59,90 + promo 54,90 | ✅ MATCH (both captured) |
| Claro | flex | Flex 15GB 44,90 / 20GB 59,90 / 30GB 69,90 / 40GB 119,90 | same | ✅ MATCH |
| Claro | prepaid | Prezão 4GB/12d, 5GB/15d (R$15); 6–8GB/20d (R$20); 9–10GB/25d (R$25); **12GB/30d (R$30)** | same prices + validity | ✅ MATCH (30-day = R$30 confirmed) |
| Vivo | postpaid | Pós com Amazon **R$150** (…→R$215) — single price, no loyalty toggle | 150 … 215 | ✅ MATCH |
| Vivo | control | Vivo Controle **R$59** (…→R$110) — single price, no loyalty toggle | 59 … 110 | ✅ MATCH |
| Vivo | **lite** | Easy Lite 30GB: **"Plano anual" (12-mo loyalty) R$30** vs **"Plano mensal / Sem fidelidade" ≈R$45** | **R$30/35/40 = the ANNUAL (loyalty) price** | ❌ **MISMATCH** |
| Vivo | prepaid | Vivo Pré R$17/15d, R$20/17d, R$25/22d, **R$30/30d** | same prices + validity | ✅ MATCH (validity correct) |
| TIM | postpaid | TIM Black A Express 67GB **R$119,99** (…→R$164,99) | 119,99 … 164,99 | ✅ MATCH |
| TIM | control | 41GB **R$58,99** (effective; list R$63,99), Plus 45GB 64,99 (list 69,99), Premium 84,99 (list 89,99) | effective 58,99/64,99/84,99 | ✅ MATCH (effective; list price not captured — minor) |
| TIM | **prepaid** | XIP: **6GB R$20 = 17 dias**, **8GB R$25 = 22 dias**, **16GB R$30 = 30 dias** | R$20/25/30 all captured as **validity=30d** | ❌ **MISMATCH (validity)** |

## 3. The two suspects — answered against the live site

### VIVO LITE — CONFIRMED (we capture the loyalty price, not the no-commitment)
The Easy Lite card has a subscription **toggle**: *"Selecionar assinatura: **Plano anual** (12x no cartão) | **Plano mensal / Sem fidelidade**"*. The rendered price (`.total-card-price-value`) is the **default "Plano anual" = R$30** (12-month loyalty). The **"Sem fidelidade" (no-commitment, ≈R$45)** price is **behind the toggle and NOT in our static Playwright capture** — there is **no R$45/R$44 *price* token** (the only price elements are `.total-card-price-value` = 30/35/40; the stray `44`/`45` digit strings in the raw are CSS `rem` values, SVG path coords, and a `plans=40` URL param, not prices). The ≈R$45 figure is the *expected* no-commitment price (not directly observed in this capture — it needs a toggle-click to render). So we currently capture the **12-month-loyalty** price (R$30/35/40 for the three Easy Lite tiers), not the no-commitment one. **Only the `lite` category has this toggle** — Vivo control/postpaid are single-price (correctly captured).

### TIM PREPAID — CONFIRMED (our validity is wrong; #18's heuristic failed)
The per-oferta text is explicit: *"6GB R$20, válidos por **17 dias**"* · *"8GB R$25, válido por **22 dias**"* · *"16GB R$30, válido por **30 dias**"*. **#18 captured all three as 30 days** because it took the **max "N dias"** in the oferta, and a shared marketing line (*"…recarga de R$30 válidos por 30 dias"*) appears in **every** oferta → max(30, 17)=30. **True validities: R$20→17d, R$25→22d, R$30→30d.** Only the **R$30/16GB** plan is a real 30-day plan.

**Impact:** the daily-matrix **Pre column** (cheapest prepaid with `validity_days ≥ 28`) currently picks **TIM R$20** — but that's a **17-day** plan. The correct cheapest 30-day TIM prepaid is **R$30**. So the Pre value for TIM has been wrong since #18.

## 4. Fidelity / promo capture (where the site shows both a loyalty/promo and a full price)

| Carrier / cat | Full/list price | Effective/loyalty price | What our adapter reads |
|---|---|---|---|
| Claro control | `~De R$ 59,90~` (regular) | **R$54,90** (fatura + conta digital) | **both** — `price_brl`=59,90, `price_promo_brl`=54,90 ✅ |
| TIM control | `field_preco_adicional_original` = R$63,99/69,99/89,99 (list) | `field_preco_card_oferta` = R$58,99/64,99/84,99 (after "Desconto Extra R$5") | **effective only** (list not captured) — minor |
| Vivo lite | "Sem fidelidade" (no-commitment) ≈R$45 — **toggle-gated, not captured** | "Plano anual" (12-mo) = R$30 | **loyalty only** ❌ |

JPMorgan uses the **effective** price for postpaid/control and a **no-commitment** view where relevant. We already capture the effective for Claro/TIM control; the gap is the Vivo-Lite no-commitment price.

## 5. What needs a parser fix (next task)

1. **TIM prepaid validity (HIGH — data correctness):** parse each oferta's own *"…R$&lt;price&gt;, válido[s] por &lt;N&gt; dias"* (matching that oferta's `field_preco_card_oferta`), not the max "N dias". → 17 / 22 / 30 days. This corrects the Pre column: true cheapest 30-day TIM = **R$30**, not R$20. (Expect a self-healing transition, like #18 — old snapshots keep the wrong validity, new ones are correct.)
2. **Vivo Lite no-commitment price (MEDIUM — comparability):** decide whether to capture the "Sem fidelidade" (no-commitment) price (requires a Playwright toggle-click before scraping the card) or to keep the "Plano anual" price and label it as loyalty. Only `lite` is affected. Drives the "effective vs no-commitment" policy.
3. **TIM control list price (LOW):** optionally capture `field_preco_adicional_original` (R$63,99…) as the regular and the card price as the effective, for promo tracking. The effective (what we show) is already correct.
4. **No change needed / confirmed correct:** Claro (all categories, incl. Prezão 30-day = R$30), Vivo control + postpaid + prepaid, TIM postpaid + control-effective. Postpaid cheapest ranking confirmed: **TIM R$119,99 &lt; Claro R$124,90 &lt; Vivo R$150**.
