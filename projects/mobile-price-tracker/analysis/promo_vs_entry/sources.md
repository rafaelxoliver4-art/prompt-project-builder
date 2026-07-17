# Source inventory — promo-vs-entry study 2023–2026 (CODE TASK #25)

All sources accessed **2026-07-17**. Every data point in `promo_vs_entry.xlsx` carries a
`source_id` resolving to this list (mirrored in the workbook's `sources` sheet).
Rule: no estimates — an unsourceable cell stays blank with a gap note.

## Coverage map (what came from where)

| Carrier × year | Entry prices | Flagship campaign |
|---|---|---|
| TIM 2023 | Wayback carrier pages (S02 controle 2023-03-01 visible-HTML; S03 pós 2023-07-26 ofertas JSON) | Black Friday roundup, Minha Operadora (S31) |
| TIM 2024 | Wayback carrier pages (S10 controle 2024-03-24; S11 pós 2024-07-05) + Tecnoblog floor corroboration (S35) | Dia das Mães, Minha Operadora (S33) |
| TIM 2025 | Wayback: carrier controle page 2025-09-05 (S19, nearest to mid-year); pós via archived **aggregator** melhorplano.net 2025-05-19 (S17 — no carrier-page snapshot exists for 2025) | App-only R$41.99, Minha Operadora (S34) |
| TIM 2026 | Own tracker, audited 2026-07-01 anchors (S23) | Ultracombo, Teletime (S24) |
| Vivo 2023 | Press tables: Tecnoblog 2023-02-10 (S01) — Wayback useless for Vivo (JS-rendered AEM, 403 to crawlers; confirmed by a 2024 probe: no plan cards in archived HTML) | Dia do Consumidor, Minha Operadora (S32) |
| Vivo 2024 | Press tables: Tecnoblog 2024-03-20 (S07) + Minha Operadora 2024-03-21 (S08) | Flash Controle 20GB R$35, Minha Operadora (S29) |
| Vivo 2025 | Wayback archived aggregator melhorplano.net (S15 controle 2025-05-13; S16 pós 2025-04-28; S18 Easy 2025-05-19) | Vivo Total Essencial R$100, Minha Operadora (S30) |
| Vivo 2026 | Own tracker (S23) | Vivo Total Ultra R$100, Minha Operadora (S25, S26) |
| Claro 2023 | Wayback carrier pages, `__NEXT_DATA__` priceData grids (S04 controle + S05 pós 2023-07-14; S06 flex 2023-07-29), cross-corroborated by S01 (Feb-2023) and S09 (Jan-2024 retrospective) | Multi Week, Minha Operadora (S28) |
| Claro 2024 | Press tables: Tecnoblog 2024-01-29 "On" portfolio (S09) + Wayback grids agree (S12, S13, S14) | Site-exclusive Oferta Relâmpago (S12, archived page) |
| Claro 2025 | Wayback carrier pages, card_360 grids (S20, S21, S22 — 2025-07-02) | Site-exclusive Oferta Relâmpago (S20, archived page) |
| Claro 2026 | Own tracker (S23) | Claro Multi entry combo, live claro.com.br/multi (S27) |

## Gaps (kept blank, not filled)

- **Pré 30-day, 2023–2025 (all carriers):** not extracted. Deriving a true 30-day-validity
  price from archived pages needs the per-oferta validity parsing that took the live tracker
  three iterations to get right (#18 → #23); repeating the known max-"N dias" error against
  dead pages, with no live check, is exactly the failure mode the audit fixed. Blank + noted.
- **TIM digital 2023–2025:** structural n/a, not a sourcing gap — TIM had no Fit-class
  digital line before Jul-2026 (#28).
- **Vivo mid-July 2026 "new convergent offer" (Bridge-reported):** no reputable source found
  for a *new* mid-July Vivo convergent launch. What is verifiable: the May/June R$100 Vivo
  Total Ultra promo (S25/S26, closed by mid-July), the 2026-07-14 Vivo Fibra 1 Giga cut to
  R$200 (fiber-only, Tecnoblog — not convergent), and today's live limited-time site promos
  (Essencial R$130 "de 160", Ultra R$170 "de 190" — S36). The study uses only the verifiable ones.

## Source list

| id | URL / location | Note |
|---|---|---|
| S01 | https://tecnoblog.net/noticias/2023/02/10/vivo-aumenta-precos-de-pos-pago-controle-e-internet-via-fibra-em-ate-169/ | Vivo Feb-2023 tables (controle 52 / Selfie 122 / Easy 29.90 / Total Essencial 170) + cross-points (Claro controle 49.90; TIM controle 46.99) |
| S02 | https://web.archive.org/web/20230301070212/https://www.tim.com.br/sp/para-voce/planos/controle | TIM controle SP 2023-03-01 (Smart 19GB 51.99 fatura; GIGA A Promo Express 26GB 50.99 cartão) |
| S03 | https://web.archive.org/web/20230726050306/https://www.tim.com.br/sp/para-voce/planos/pos-pago/tim-black | TIM Black SP 2023-07-26 (Nacional 70GB 104.99 fatura) |
| S04 | https://web.archive.org/web/20230714074110/https://www.claro.com.br/celular/controle | Claro controle 2023-07-14 (grid 49.90/59.90/69.90; site-exclusive 18GB 49.90) |
| S05 | https://web.archive.org/web/20230714074104/https://www.claro.com.br/celular/pos | Claro pós 2023-07-14 (grid 99.90–299.90) |
| S06 | https://web.archive.org/web/20230729065638/https://www.claro.com.br/celular/flex | Claro Flex 2023-07-29 (29.99–59.99) |
| S07 | https://tecnoblog.net/noticias/vivo-muda-planos-de-celular-e-precos-aumentam-ate-13/ | Vivo 2024-03-20 portfolio (controle 55 / Selfie 130 / Easy Prime Light 33) |
| S08 | https://www.minhaoperadora.com.br/2024/03/planos-da-vivo-sofrem-aumento-reajustes-ja-estao-valendo.html | Vivo 2024-03-21 reajuste (corroborates S07) |
| S09 | https://tecnoblog.net/noticias/claro-revela-os-precos-dos-planos-controle-e-pos-para-2024-veja-tabela/ | Claro 2024-01-29 "On" tables (Controle On 49.90 déb+digital, +R$5 without; Pós On 109.90) |
| S10 | https://web.archive.org/web/20240324130135/https://www.tim.com.br/sp/para-voce/planos/controle | TIM controle SP 2024-03-24 (Smart 25GB 52.99; B Express 21GB 49.99 cartão) |
| S11 | https://web.archive.org/web/20240705142758/https://www.tim.com.br/sp/para-voce/planos/pos-pago/tim-black | TIM Black SP 2024-07-05 (A 70GB 119.99 fatura) |
| S12 | https://web.archive.org/web/20240708001528/https://www.claro.com.br/celular/controle | Claro controle 2024-07-08 (grid 49.90–74.90; Relâmpago 22GB 59.90) |
| S13 | https://web.archive.org/web/20240708001223/https://www.claro.com.br/celular/pos | Claro pós 2024-07-08 (On grid 109.90+) |
| S14 | https://web.archive.org/web/20240610203153/https://www.claro.com.br/celular/flex | Claro Flex 2024-06-10 (34.99–59.99) |
| S15 | https://web.archive.org/web/20250513012448/https://melhorplano.net/vivo/planos-vivo/vivo-controle | Vivo Controle 2025-05-13, SP results (23GB R$59) — aggregator |
| S16 | https://web.archive.org/web/20250428035235/https://melhorplano.net/vivo/planos-vivo/vivo-pos-pago | Vivo Pós 2025-04-28, SP results (entry R$140) — aggregator |
| S17 | https://web.archive.org/web/20250519055619/https://melhorplano.net/tim/planos-tim/tim-pos-pago | TIM Black 2025-05-19, SP results (70GB 105.99 fatura c/ permanência; 130.99 sem) — aggregator |
| S18 | https://web.archive.org/web/20250519053551/https://melhorplano.net/vivo/planos-vivo/vivo-easy | Vivo Easy 2025-05-19 (Prime Light 16GB R$33) — aggregator |
| S19 | https://web.archive.org/web/20250905153930/https://www.tim.com.br/sp/para-voce/planos/controle | TIM controle SP 2025-09-05 (27GB 58.99) — nearest available to mid-2025 |
| S20 | https://web.archive.org/web/20250702233357/https://www.claro.com.br/celular/controle | Claro controle 2025-07-02 (card_360: 59.90/69.90/99.90; Relâmpago 25GB 49.90) |
| S21 | https://web.archive.org/web/20250702233313/https://www.claro.com.br/celular/pos | Claro pós 2025-07-02 (card_360: 119.90+) |
| S22 | https://web.archive.org/web/20250702234013/https://www.claro.com.br/celular/flex | Claro Flex 2025-07-02 (44.99/54.99/69.99) |
| S23 | `data/mobile_plans.xlsx` — tracker history, snapshot 2026-07-01 (audited #22–#24) | 2026 anchors: controle TIM 58.99 / Vivo 59 / Claro 54.90 eff (59.90 reg); pós TIM 129.99 bill / Vivo 150 / Claro 124.90; digital + pré 30d; TIM controle cut to 49.99 on 2026-07-06 (#29) |
| S24 | https://teletime.com.br/16/07/2026/tim-ultracombo-40/ | TIM Ultracombo 2026-07-16 (R$89.99–314.99 déb. automático; partly SP-exclusive; "up to 40%" claim) |
| S25 | https://www.minhaoperadora.com.br/2026/05/vivo-tem-promocao-que-une-fibra-700-mega-e-pos-70-gb-por-r-100-ao-mes.html | Vivo Total Ultra R$100 (2026-05-23; new customers; later closed) |
| S26 | https://www.minhaoperadora.com.br/2026/06/vivo-traz-de-volta-promocao-do-700-mega-70-gb-por-r-100.html | R$100 promo re-run (June-2026; CazéTV partnership, app-only) |
| S27 | https://www.claro.com.br/multi | Claro Multi live 2026-07-17 (entry combo 350M+Controle 41GB+Globoplay R$129.80 limited-time; 600M+Pós 60GB R$159.90; "up to 35% off" claim) |
| S28 | https://www.minhaoperadora.com.br/2023/07/claro-oferta-planos-com-descontos-combinados-com-internet-fixa-movel-e-streaming.html | Claro Multi Week 2023-07-06..12 (entry combo 149.90, SP-city prices) |
| S29 | https://www.minhaoperadora.com.br/2024/09/promocao-relampago-do-vivo-controle-20gb-de-internet-por-r-35.html | Vivo flash Controle 20GB R$35 (2024-09-03) |
| S30 | https://www.minhaoperadora.com.br/2025/11/vivo-lanca-promocao-de-fibra-e-pos-por-r-100.html | Vivo Total Essencial R$100 (2025-11-22) |
| S31 | https://www.minhaoperadora.com.br/2023/11/ofertas-black-friday-no-mundo-telecom-veja-as-melhores.html | Black Friday 2023 roundup (TIM Controle 33GB 52.99 boleto 12m; Claro BF bonuses; Vivo fiber-only) |
| S32 | https://www.minhaoperadora.com.br/2023/03/vivo-faz-promocoes-do-dia-do-consumidor-com-internet-extra-de-ate-20gb.html | Vivo Dia do Consumidor 2023 (bonus campaign; controle +6GB; no fidelity) |
| S33 | https://www.minhaoperadora.com.br/2024/04/tim-incrementa-bonus-de-internet-em-planos-controle-para-o-dia-das-maes.html | TIM Dia das Mães 2024 (+20GB/12m; cheapest tier J Express 29GB R$54.99) |
| S34 | https://www.minhaoperadora.com.br/2025/12/tim-lanca-plano-controle-com-33-gb-por-apenas-r-4199.html | TIM app-only Controle 33.5GB R$41.99 (2025-12-21; R$44.99 other channels; 12m) |
| S35 | https://tecnoblog.net/noticias/exclusivo-tim-confirma-novos-planos-controle-mais-caros-para-2024/ | TIM Controle 2024 range R$49.99–101.99 (Anatel filings) |
| S36 | https://internet.vivo.com.br/ofertas/fibra-e-pos/ | Vivo Total promo landing, live 2026-07-17 (Essencial R$130 "de 160"; Ultra R$170 "de 190") |
| S37 | https://www.minhaoperadora.com.br/2026/02/vivo-lanca-novo-plano-controle-de-45-gb-por-apenas-r-35.html | Vivo Controle 45GB R$35 (Feb-2026; R$40 from April) |

## Method notes on source quality

- **Carrier pages beat aggregators beat roundups.** Where an archived carrier page exists it is
  the primary source; melhorplano.net archived pages (S15–S18) fill Vivo-2025 and TIM-pós-2025
  where no carrier snapshot exists — flagged `aggregator` in the workbook notes.
- **Claro archived pages carry two price components.** The `priceData`/`card_360` grid is the
  live portfolio; a separate static five-card block (69.90–94.90 in both 2023 *and* 2024) contradicts
  the press-verified Jan-2024 "On" portfolio and was discarded as stale in both years. The grid
  values are corroborated at both ends (Feb-2023 press, Jan-2024 press).
- **TIM 2023–2025 headline prices carry conditions**: "na fatura" prices with a 12-month
  permanência discount (the no-permanência price is R$20–50 higher). Recorded as the advertised
  headline, condition in notes — consistent with how the tracker captures TIM's effective card
  price today. Credit-card-only ("no cartão"/Express) tiers are excluded from entry picks per
  the JPMorgan bill-payment rule the task fixes for the 2026 pós anchor.
