"""Write the tracker workbook: history (append-only), latest, changes, summary.

Design (CONTEXT §7):
- We rebuild the whole file each run from a merged dataframe, so `history` is the
  union of all past snapshots + today's, de-duplicated on (date, carrier, category,
  state, plan_name) keeping the latest write. This makes re-running the same day idempotent.
- `latest` = the most recent snapshot only.
- `changes` = diff of latest vs the previous snapshot date (new / removed / price moves).
- `summary` = run metadata + per-carrier KPIs as Excel formulas (computed on open).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.chart import LineChart, Reference
from openpyxl.chart.marker import Marker
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.formatting.rule import ColorScaleRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .models import COLUMNS

FONT = "Arial"
# Canonical identity = (carrier, state, plan_id). plan_id is the stable per-plan key (CONTEXT §4);
# if a row ever lacks plan_id we fall back to plan_name so nothing crashes.
def _with_key(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "plan_id" not in df.columns:
        df["plan_id"] = pd.NA
    pid = df["plan_id"].astype("string")
    df["_key"] = pid.where(pid.notna() & (pid.str.strip() != ""), df["plan_name"].astype("string"))
    return df


HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(name=FONT, bold=True, color="FFFFFF")
CURRENCY_FMT = 'R$ #,##0.00;[RED]-R$ #,##0.00;"-"'

# ---- House style (design system, CONTEXT §7) — defined once, applied everywhere ------------
BAND_FILL = PatternFill("solid", fgColor="F2F5FA")           # alternate data rows
SUBHEADER_FILL = PatternFill("solid", fgColor="D6E0F0")      # carrier-sheet category sub-headers
SUBHEADER_FONT = Font(name=FONT, bold=True, color="1F3864")
PROMO_FILL = PatternFill("solid", fgColor="FFF2CC")          # cells with a promo price
CHEAP_FILL = PatternFill("solid", fgColor="C6EFCE")          # cheapest-of-the-row highlight
CHEAP_FONT = Font(name=FONT, bold=True, color="006100")
HEADER_BORDER = Border(bottom=Side(style="thin", color="FFFFFF"))
RIGHT = Alignment(horizontal="right")
# tab colors per sheet (engine/flat sheets neutral grey; views + carriers branded)
TAB_COLORS = {
    "Vivo": "660099", "Claro": "DA291C", "TIM": "0033A0",
    "comparison": "2E7D32", "Ranking": "1565C0", "summary": "102A43",
    "history": "8A8A8A", "latest": "8A8A8A", "changes": "8A8A8A",
}


def _price_scale() -> ColorScaleRule:
    """3-colour scale: green = cheap (low) → yellow → red = expensive (high)."""
    return ColorScaleRule(start_type="min", start_color="63BE7B",
                          mid_type="percentile", mid_value=50, mid_color="FFEB84",
                          end_type="max", end_color="F8696B")


def _gridless(ws, tab_color: str | None = None):
    ws.sheet_view.showGridLines = False          # clean modern look — no gridlines anywhere
    if tab_color:
        ws.sheet_properties.tabColor = tab_color


def _house_header(ws, row: int, n_cols: int):
    for col in range(1, n_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.border = HEADER_BORDER
        cell.alignment = Alignment(vertical="center", horizontal="left")


def _band(ws, first_row: int, last_row: int, n_cols: int):
    """Shade every other data row (first row plain, second shaded, …)."""
    for i, row in enumerate(range(first_row, last_row + 1)):
        if i % 2 == 1:
            for col in range(1, n_cols + 1):
                ws.cell(row=row, column=col).fill = BAND_FILL


def _color_scale(ws, col_idx: int, first_row: int, last_row: int):
    if last_row >= first_row:
        L = get_column_letter(col_idx)
        ws.conditional_formatting.add(f"{L}{first_row}:{L}{last_row}", _price_scale())


def _df(plans) -> pd.DataFrame:
    rows = [p.as_row() for p in plans]
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df


def _merge_history(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    # A re-run of a snapshot_date REPLACES that date's rows (idempotent per date): `fresh` fully owns
    # the date(s) it carries, so a same-day re-run / double-fire can't union-inflate a date. Other
    # dates accumulate untouched (append-only across days; CONTEXT §4).
    if not fresh.empty and "snapshot_date" in existing.columns and not existing.empty:
        fresh_dates = set(fresh["snapshot_date"].dropna().unique())
        existing = existing[~existing["snapshot_date"].isin(fresh_dates)]
    df = pd.concat([existing, fresh], ignore_index=True)
    df = _with_key(df)
    df = df.drop_duplicates(subset=["snapshot_date", "carrier", "state", "_key"], keep="last")
    df = df.sort_values(["snapshot_date", "carrier", "category", "plan_name"]).reset_index(drop=True)
    return df.drop(columns=["_key"])


def _compute_changes(history: pd.DataFrame) -> pd.DataFrame:
    cols = ["change_type", "carrier", "category", "state", "plan_id", "plan_name",
            "old_price_brl", "new_price_brl", "delta_brl"]
    dates = sorted(history["snapshot_date"].dropna().unique())
    if len(dates) < 2:
        return pd.DataFrame(columns=cols)
    latest, prev = dates[-1], dates[-2]
    h = _with_key(history)
    h["_ck"] = h["carrier"].astype(str) + "|" + h["state"].astype(str) + "|" + h["_key"].astype(str)
    cur = h[h.snapshot_date == latest].drop_duplicates("_ck").set_index("_ck")
    old = h[h.snapshot_date == prev].drop_duplicates("_ck").set_index("_ck")

    def base(r):  # carrier, category, state, plan_id, plan_name — matched by (carrier, state, plan_id)
        return [r["carrier"], r["category"], r["state"], r["plan_id"], r["plan_name"]]

    out = []
    for k in cur.index.difference(old.index):
        r = cur.loc[k]
        out.append(["new", *base(r), None, r["price_brl"], None])
    for k in old.index.difference(cur.index):
        r = old.loc[k]
        out.append(["removed", *base(r), r["price_brl"], None, None])
    for k in cur.index.intersection(old.index):
        r, o = cur.loc[k], old.loc[k]
        np_, op = r["price_brl"], o["price_brl"]
        if pd.notna(np_) and pd.notna(op) and float(np_) != float(op):
            out.append(["price_change", *base(r), op, np_, float(np_) - float(op)])
    return pd.DataFrame(out, columns=cols)


def _format_sheet(ws, currency_cols=(), number_cols=(), tab_color=None, autofilter=False):
    _gridless(ws, tab_color)
    ws.freeze_panes = "A2"
    last_col = ws.max_column
    last_row = ws.max_row
    if last_col == 0:
        return
    if autofilter:
        ws.auto_filter.ref = f"A1:{get_column_letter(last_col)}{max(last_row, 1)}"
    _house_header(ws, 1, last_col)
    for col in range(1, last_col + 1):
        letter = get_column_letter(col)
        width = max(10, min(40, len(str(ws.cell(row=1, column=col).value)) + 2))
        ws.column_dimensions[letter].width = width
        for row in range(2, last_row + 1):
            c = ws.cell(row=row, column=col)
            c.font = Font(name=FONT)
            if col in currency_cols:
                c.number_format = CURRENCY_FMT
                c.alignment = RIGHT
            elif col in number_cols:
                c.number_format = "#,##0.##"
                c.alignment = RIGHT
    if last_row >= 2:
        _band(ws, 2, last_row, last_col)


COMPARE_CARRIERS = ["vivo", "claro", "tim"]
# (group title, category values it spans, optional caveat note) — CONTEXT §7 methodology
COMPARE_GROUPS = [
    ("Pure Postpaid", ["postpaid"], None),
    ("Control / Hybrid", ["control"], None),
    ("Prepaid", ["prepaid"],
     "Note: prepaid is not a clean unit — Claro Prezão is a daily fee (R$1/dia) vs Vivo/TIM recharge amounts."),
    ("Digital", ["lite", "flex"],
     "Digital = Vivo Lite + Claro Flex (TIM has no digital line)."),
]


def _ranked(latest: pd.DataFrame, cats, carrier: str):
    df = latest[(latest["carrier"] == carrier) & (latest["category"].isin(cats))]
    df = df.dropna(subset=["price_brl"]).sort_values("price_brl", kind="stable")
    return list(df[["price_brl", "plan_name", "data_gb", "price_promo_brl"]]
                .itertuples(index=False, name=None))


def build_comparison_data(latest: pd.DataFrame) -> list[dict]:
    """Pure: latest snapshot → per-group, per-carrier price-ranked plan lists (CONTEXT §7).
    Each carrier's plans in a category are sorted ascending by price_brl, then aligned across
    carriers by rank (cheapest-vs-cheapest, 2nd-vs-2nd, …). Offline-testable."""
    out = []
    for title, cats, note in COMPARE_GROUPS:
        per = {c: _ranked(latest, cats, c) for c in COMPARE_CARRIERS}
        out.append({
            "title": title,
            "note": note,
            "per_carrier": per,
            "max_rank": max((len(v) for v in per.values()), default=0),
        })
    return out


def _write_ranking(xl, latest: pd.DataFrame):
    """Render the `Ranking` sheet: the validated cross-section — four groups, each rank-aligned
    across Vivo/Claro/TIM by ascending price (today's snapshot)."""
    ws = xl.book.create_sheet("Ranking")
    _gridless(ws, TAB_COLORS["Ranking"])
    ws.freeze_panes = "A1"
    ws.cell(row=1, column=1,
            value="Ranking (today) — within category, aligned by price rank") \
        .font = Font(name=FONT, bold=True, size=14)
    headers = ["Rank", "Vivo R$", "Claro R$", "TIM R$", "Vivo plan", "Claro plan", "TIM plan"]
    r = 3
    for grp in build_comparison_data(latest):
        ws.cell(row=r, column=1, value=grp["title"]).font = Font(name=FONT, bold=True, size=12)
        r += 1
        if grp["note"]:
            cell = ws.cell(row=r, column=1, value=grp["note"])
            cell.font = Font(name=FONT, italic=True, size=9, color="808080")
            r += 1
        for j, h in enumerate(headers, start=1):
            ws.cell(row=r, column=j, value=h)
        _house_header(ws, r, len(headers))
        r += 1
        per = grp["per_carrier"]
        rank_top = r
        for rank in range(grp["max_rank"]):
            ws.cell(row=r, column=1, value=rank + 1).font = Font(name=FONT)
            for ci, carrier in enumerate(COMPARE_CARRIERS):
                rows = per[carrier]
                if rank < len(rows):
                    price, name, gb, promo = rows[rank]
                    pcell = ws.cell(row=r, column=2 + ci, value=float(price))
                    pcell.number_format = CURRENCY_FMT
                    pcell.font = Font(name=FONT)
                    pcell.alignment = RIGHT
                    label = f"{name} ({int(gb)}GB)" if pd.notna(gb) else str(name)
                    if pd.notna(promo):
                        label += f" · promo R${float(promo):g}"
                    ws.cell(row=r, column=5 + ci, value=label).font = Font(name=FONT)
            r += 1
        rank_bottom = r - 1
        if rank_bottom >= rank_top:
            _band(ws, rank_top, rank_bottom, len(headers))
            rng = f"B{rank_top}:D{rank_bottom}"        # the three R$ columns over this group's rank rows
            # 1) cheapest-of-the-row highlight (higher priority + stopIfTrue so it wins over the scale)
            ws.conditional_formatting.add(rng, FormulaRule(
                formula=[f'AND(B{rank_top}<>"",B{rank_top}=MIN($B{rank_top}:$D{rank_top}))'],
                fill=CHEAP_FILL, font=CHEAP_FONT, stopIfTrue=True))
            # 2) colour-grade the R$ columns green (cheap) → yellow → red (expensive)
            ws.conditional_formatting.add(rng, _price_scale())
        r += 1  # blank separator between groups
    for col, w in {1: 6, 2: 11, 3: 11, 4: 11, 5: 32, 6: 32, 7: 32}.items():
        ws.column_dimensions[get_column_letter(col)].width = w


OPERATOR_DISPLAY = {"vivo": "Vivo", "claro": "Claro", "tim": "TIM"}
# category blocks within each operator sheet, in display order
OPERATOR_CATEGORY_ORDER = [
    ("Postpaid", ["postpaid"]),
    ("Control", ["control"]),
    ("Digital", ["lite", "flex"]),
    ("Prepaid", ["prepaid"]),
]
OPERATOR_COLUMNS = ["Plan", "Price R$", "Promo R$", "Data", "Voice",
                    "Unlimited apps", "Streaming", "Notes"]


def _s(v) -> str | None:
    """A non-empty string, else None (so blank cells stay blank)."""
    return v if isinstance(v, str) and v.strip() else None


def _operator_plan_row(p) -> list:
    """One readable catalog row from a latest-snapshot record (itertuples)."""
    data = f"{p.data_gb:g} GB" if pd.notna(p.data_gb) else ""
    dnote = _s(p.data_note)
    if dnote:
        data = f"{data} ({dnote})" if data else dnote
    notes = " · ".join(x for x in (_s(p.extra_benefits), _s(p.price_note)) if x) or None
    return [
        p.plan_name,
        float(p.price_brl) if pd.notna(p.price_brl) else None,
        float(p.price_promo_brl) if pd.notna(p.price_promo_brl) else None,
        data or None,
        _s(p.voice),
        _s(p.unlimited_apps),
        _s(p.streaming),
        notes,
    ]


def build_operator_sheets(latest: pd.DataFrame) -> list[dict]:
    """Pure: latest snapshot → one structure per carrier present (category blocks, price-sorted).
    Carriers not in the snapshot get no sheet. Offline-testable."""
    present = set(latest["carrier"].dropna())
    ordered = [c for c in COMPARE_CARRIERS if c in present]
    ordered += [c for c in latest["carrier"].dropna().unique() if c not in ordered]  # future carriers
    out = []
    for carrier in ordered:
        blocks = []
        for label, cats in OPERATOR_CATEGORY_ORDER:
            df = latest[(latest["carrier"] == carrier) & (latest["category"].isin(cats))]
            df = df.dropna(subset=["price_brl"]).sort_values("price_brl", kind="stable")
            rows = [_operator_plan_row(p) for p in df.itertuples(index=False)]
            if rows:
                blocks.append({"label": label, "rows": rows})
        if blocks:
            out.append({"carrier": carrier,
                        "display": OPERATOR_DISPLAY.get(carrier, str(carrier).title()),
                        "blocks": blocks})
    return out


def _write_operator_sheets(xl, latest: pd.DataFrame):
    """One sheet per carrier: plans grouped by category (accented sub-header), price-sorted."""
    ncol = len(OPERATOR_COLUMNS)
    for op in build_operator_sheets(latest):
        display = op["display"]
        ws = xl.book.create_sheet(display)
        _gridless(ws, TAB_COLORS.get(display))
        ws.freeze_panes = "A2"
        for j, h in enumerate(OPERATOR_COLUMNS, start=1):
            ws.cell(row=1, column=j, value=h)
        _house_header(ws, 1, ncol)
        r = 2
        for block in op["blocks"]:
            for col in range(1, ncol + 1):                # category sub-header band
                ws.cell(row=r, column=col).fill = SUBHEADER_FILL
            ws.cell(row=r, column=1, value=block["label"]).font = SUBHEADER_FONT
            r += 1
            block_top = r
            for i, row in enumerate(block["rows"]):
                for j, val in enumerate(row, start=1):
                    cell = ws.cell(row=r, column=j, value=val)
                    cell.font = Font(name=FONT)
                    if j in (2, 3):                        # Price R$, Promo R$
                        cell.number_format = CURRENCY_FMT
                        cell.alignment = RIGHT
                if i % 2 == 1:                             # banding within the block
                    for col in range(1, ncol + 1):
                        ws.cell(row=r, column=col).fill = BAND_FILL
                if row[2] is not None:                     # promo present → accent the Promo cell
                    ws.cell(row=r, column=3).fill = PROMO_FILL
                r += 1
            _color_scale(ws, 2, block_top, r - 1)          # grade Price R$ within this category block
        for col, w in {1: 32, 2: 11, 3: 11, 4: 22, 5: 20, 6: 18, 7: 18, 8: 40}.items():
            ws.column_dimensions[get_column_letter(col)].width = w


# ---- price-evolution matrix (the `comparison` sheet) — CONTEXT §7 ----------------------------
# (group title, category, kind). "single" = one category; "digital" = min over lite OR flex.
EVOLUTION_GROUPS = [
    ("Control (R$/mo)", "control", "single"),
    ("Post (R$/mo)", "postpaid", "single"),
    ("Pre (R$, recarga)", "prepaid", "single"),
    ("Digital (R$/mo)", None, "digital"),
]
EVOLUTION_CARRIERS = ["tim", "vivo", "claro"]
EVOLUTION_DISP = {"tim": "TIM", "vivo": "Vivo", "claro": "Claro"}
CARRIER_LINE = {"tim": "0033A0", "vivo": "660099", "claro": "DA291C"}  # series colors = tab palette


def _line_chart(ws, title, c0, head_row, first, last, anchor):
    """One per-category line chart: X = Date column, 3 series = TIM/Vivo/Claro matrix columns.
    Data references the live matrix (which reads history), so charts grow as history accumulates."""
    chart = LineChart()
    chart.title = title
    chart.y_axis.title = "R$"
    chart.x_axis.title = "Date"
    chart.height, chart.width = 7.2, 11.5
    chart.legend.position = "b"
    data = Reference(ws, min_col=c0, max_col=c0 + 2, min_row=head_row, max_row=last)  # incl. names row
    cats = Reference(ws, min_col=1, min_row=first, max_row=last)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    for s, carrier in zip(chart.series, EVOLUTION_CARRIERS):
        s.graphicalProperties = GraphicalProperties()
        s.graphicalProperties.line = LineProperties(solidFill=CARRIER_LINE[carrier], w=20000)
        s.marker = Marker(symbol="circle", size=6)
        s.smooth = False
    ws.add_chart(chart, anchor)
    return chart


def evolution_dates(history: pd.DataFrame) -> list[str]:
    """Distinct snapshot_dates in history, chronological (oldest first). Offline-testable."""
    if "snapshot_date" not in history.columns:
        return []
    return sorted({str(d) for d in history["snapshot_date"].dropna()})


def _hist_cols():
    return (get_column_letter(COLUMNS.index("price_brl") + 1),
            get_column_letter(COLUMNS.index("carrier") + 1),
            get_column_letter(COLUMNS.index("category") + 1),
            get_column_letter(COLUMNS.index("snapshot_date") + 1))


def _minifs(pc, cc, dc, sc, carrier, category, row):
    """Cheapest price `carrier` offered in `category` on the date in $A{row}, over the history sheet."""
    return (f'_xlfn.MINIFS(history!${pc}:${pc},'
            f'history!${cc}:${cc},"{carrier}",'
            f'history!${dc}:${dc},"{category}",'
            f'history!${sc}:${sc},$A{row})')


def _write_comparison(xl, history: pd.DataFrame):
    """`comparison` = the price-evolution MATRIX: Date (rows) × category-group × carrier (cols).
    Every value cell is a LIVE MINIFS formula over the `history` sheet, so the matrix fills in as
    daily history accumulates (self-connected workbook). 0 (no match) → "" so the heatmap ignores it."""
    ws = xl.book.create_sheet("comparison")
    _gridless(ws, TAB_COLORS["comparison"])
    pc, cc, dc, sc = _hist_cols()
    ncol = 1 + 3 * len(EVOLUTION_GROUPS)
    ws.cell(row=1, column=1, value="Price evolution — cheapest R$ per carrier × category, by date") \
        .font = Font(name=FONT, bold=True, size=14)

    HEAD1, HEAD2, FIRST = 35, 36, 37   # matrix sits BELOW the 2×2 line-chart block at the top
    ws.cell(row=HEAD1, column=1, value="Date")
    ws.merge_cells(start_row=HEAD1, start_column=1, end_row=HEAD2, end_column=1)
    for g, (title, _cat, _kind) in enumerate(EVOLUTION_GROUPS):
        c0 = 2 + g * 3
        ws.merge_cells(start_row=HEAD1, start_column=c0, end_row=HEAD1, end_column=c0 + 2)
        ws.cell(row=HEAD1, column=c0, value=title)
        for k, carrier in enumerate(EVOLUTION_CARRIERS):
            ws.cell(row=HEAD2, column=c0 + k, value=EVOLUTION_DISP[carrier])
    _house_header(ws, HEAD1, ncol)
    _house_header(ws, HEAD2, ncol)
    ws.cell(row=HEAD1, column=1).alignment = Alignment(vertical="center", horizontal="left")
    for c in range(2, ncol + 1):
        ws.cell(row=HEAD1, column=c).alignment = Alignment(vertical="center", horizontal="center")
        ws.cell(row=HEAD2, column=c).alignment = Alignment(vertical="center", horizontal="center")

    r = FIRST
    for d in evolution_dates(history):
        ws.cell(row=r, column=1, value=d).font = Font(name=FONT)
        for g, (title, category, kind) in enumerate(EVOLUTION_GROUPS):
            c0 = 2 + g * 3
            for k, carrier in enumerate(EVOLUTION_CARRIERS):
                if kind == "single":
                    m = _minifs(pc, cc, dc, sc, carrier, category, r)
                    formula = f'=IF({m}=0,"",{m})'
                else:  # digital = min over lite OR flex; "" if the carrier has neither
                    lite = _minifs(pc, cc, dc, sc, carrier, "lite", r)
                    flex = _minifs(pc, cc, dc, sc, carrier, "flex", r)
                    formula = f'=IFERROR(1/MAX(IFERROR(1/{lite},0),IFERROR(1/{flex},0)),"")'
                cell = ws.cell(row=r, column=c0 + k, value=formula)
                cell.number_format = CURRENCY_FMT
                cell.font = Font(name=FONT)
                cell.alignment = RIGHT
        r += 1
    last = r - 1

    if last >= FIRST:                                  # per-group heatmap (green cheap → red dear)
        for g in range(len(EVOLUTION_GROUPS)):
            c0 = 2 + g * 3
            rng = f"{get_column_letter(c0)}{FIRST}:{get_column_letter(c0 + 2)}{last}"
            ws.conditional_formatting.add(rng, _price_scale())
        # 4 per-category line charts in a 2×2 block at the top (price over time; matrix grows below)
        anchors = ["A2", "J2", "A19", "J19"]
        for g, (title, _c, _k) in enumerate(EVOLUTION_GROUPS):
            _line_chart(ws, f"{title.split(' (')[0]} — cheapest R$ over time",
                        2 + g * 3, HEAD2, FIRST, last, anchors[g])

    note = ws.cell(row=last + 2, column=1,
                   value="Pre = cheapest recharge amount captured (true R$/day needs validity-days we "
                         "don't yet capture — CONTEXT §8). Digital = min of Vivo Lite / Claro Flex. "
                         "Daily rows now; monthly roll-up is the planned next step.")
    note.font = Font(name=FONT, italic=True, size=9, color="808080")
    ws.freeze_panes = f"B{FIRST}"
    ws.column_dimensions["A"].width = 13
    for c in range(2, ncol + 1):
        ws.column_dimensions[get_column_letter(c)].width = 10


def write_workbook(plans, path: str | Path, run_ts: datetime) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = _df(plans)

    existing = pd.DataFrame(columns=COLUMNS)
    if path.exists():
        try:
            existing = pd.read_excel(path, sheet_name="history", dtype={"snapshot_date": str})
        except Exception:
            existing = pd.DataFrame(columns=COLUMNS)

    history = _merge_history(existing, fresh)
    latest_date = history["snapshot_date"].max()
    latest = history[history.snapshot_date == latest_date].reset_index(drop=True)
    changes = _compute_changes(history)

    # price columns -> currency; data_gb -> number. (1-based indices from COLUMNS)
    cur_cols = (COLUMNS.index("price_brl") + 1, COLUMNS.index("price_promo_brl") + 1)
    num_cols = (COLUMNS.index("data_gb") + 1,)

    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        history.to_excel(xl, sheet_name="history", index=False)
        latest.to_excel(xl, sheet_name="latest", index=False)
        changes.to_excel(xl, sheet_name="changes", index=False)
        _format_sheet(xl.sheets["history"], cur_cols, num_cols,
                      tab_color=TAB_COLORS["history"], autofilter=True)
        latest_ws = xl.sheets["latest"]
        _format_sheet(latest_ws, cur_cols, num_cols, tab_color=TAB_COLORS["latest"], autofilter=True)
        if len(latest) >= 1:
            last = len(latest) + 1
            _color_scale(latest_ws, COLUMNS.index("price_brl") + 1, 2, last)        # price green→red
            L = get_column_letter(COLUMNS.index("price_promo_brl") + 1)
            latest_ws.conditional_formatting.add(                                    # promo accent
                f"{L}2:{L}{last}", FormulaRule(formula=[f"NOT(ISBLANK({L}2))"], fill=PROMO_FILL))
        _format_sheet(xl.sheets["changes"], (7, 8, 9), tab_color=TAB_COLORS["changes"])
        _write_summary(xl, run_ts, latest_date, len(latest), history["snapshot_date"].nunique())
        _write_comparison(xl, history)       # price-evolution matrix (live MINIFS over history)
        _write_ranking(xl, latest)           # validated cross-section (rank-aligned, today)
        _write_operator_sheets(xl, latest)   # one tab per carrier (by-operator catalog view)

    return {
        "path": str(path),
        "snapshot_date": str(latest_date),
        "plans_in_latest": int(len(latest)),
        "snapshots_in_history": int(history["snapshot_date"].nunique()),
        "changes": int(len(changes)),
    }


def _write_summary(xl, run_ts, latest_date, n_latest, n_snapshots):
    wb = xl.book
    ws = wb.create_sheet("summary")
    _gridless(ws, TAB_COLORS["summary"])
    ws["A1"] = "Mobile Price Tracker — Summary"
    ws["A1"].font = Font(name=FONT, bold=True, size=14)
    meta = [
        ("Run timestamp", run_ts.isoformat(timespec="seconds")),
        ("Latest snapshot", str(latest_date)),
        ("Plans in latest", n_latest),
        ("Snapshots in history", n_snapshots),
    ]
    for i, (k, v) in enumerate(meta, start=3):
        ws.cell(row=i, column=1, value=k).font = Font(name=FONT, bold=True)
        ws.cell(row=i, column=2, value=v).font = Font(name=FONT)

    # Per-carrier KPI table driven by formulas over the `latest` sheet.
    g = get_column_letter(COLUMNS.index("price_brl") + 1)   # price col in latest
    c = get_column_letter(COLUMNS.index("carrier") + 1)     # carrier col in latest
    rng_p = f"latest!${g}$2:${g}$2000"
    rng_c = f"latest!${c}$2:${c}$2000"

    head_row = 8
    headers = ["carrier", "# plans", "min price", "avg price", "max price"]
    for j, h in enumerate(headers, start=1):
        ws.cell(row=head_row, column=j, value=h)
    _house_header(ws, head_row, len(headers))
    for idx, carrier in enumerate(["vivo", "claro", "tim"], start=head_row + 1):
        a = f"$A${idx}"
        ws.cell(row=idx, column=1, value=carrier).font = Font(name=FONT)
        ws.cell(row=idx, column=2, value=f'=COUNTIF({rng_c},{a})').font = Font(name=FONT)
        ws.cell(row=idx, column=3, value=f'=IFERROR(_xlfn.MINIFS({rng_p},{rng_c},{a}),"-")').font = Font(name=FONT)
        ws.cell(row=idx, column=4, value=f'=IFERROR(AVERAGEIFS({rng_p},{rng_c},{a}),"-")').font = Font(name=FONT)
        ws.cell(row=idx, column=5, value=f'=IFERROR(_xlfn.MAXIFS({rng_p},{rng_c},{a}),"-")').font = Font(name=FONT)
        for col in (3, 4, 5):
            ws.cell(row=idx, column=col).number_format = CURRENCY_FMT
    for col, w in {1: 22, 2: 12, 3: 14, 4: 14, 5: 14}.items():
        ws.column_dimensions[get_column_letter(col)].width = w
