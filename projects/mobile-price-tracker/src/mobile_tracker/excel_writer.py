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
from openpyxl.styles import Alignment, Font, PatternFill
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


def _df(plans) -> pd.DataFrame:
    rows = [p.as_row() for p in plans]
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df


def _merge_history(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
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


def _format_sheet(ws, currency_cols=(), number_cols=()):
    ws.freeze_panes = "A2"
    last_col = ws.max_column
    last_row = ws.max_row
    if last_col == 0:
        return
    ws.auto_filter.ref = f"A1:{get_column_letter(last_col)}{max(last_row,1)}"
    for col in range(1, last_col + 1):
        letter = get_column_letter(col)
        header = ws.cell(row=1, column=col)
        header.font = HEADER_FONT
        header.fill = HEADER_FILL
        header.alignment = Alignment(vertical="center", horizontal="left")
        width = max(10, min(40, len(str(header.value)) + 2))
        ws.column_dimensions[letter].width = width
        for row in range(2, last_row + 1):
            c = ws.cell(row=row, column=col)
            c.font = Font(name=FONT)
            if col in currency_cols:
                c.number_format = CURRENCY_FMT
            elif col in number_cols:
                c.number_format = "#,##0.##"


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


def _write_comparison(xl, latest: pd.DataFrame):
    """Render the `comparison` sheet: four groups, each rank-aligned across Vivo/Claro/TIM."""
    ws = xl.book.create_sheet("comparison")
    ws.freeze_panes = "A1"
    ws.cell(row=1, column=1,
            value="Cross-operator comparison — within category, aligned by price rank") \
        .font = Font(name=FONT, bold=True, size=14)
    r = 3
    for grp in build_comparison_data(latest):
        ws.cell(row=r, column=1, value=grp["title"]).font = Font(name=FONT, bold=True, size=12)
        r += 1
        if grp["note"]:
            cell = ws.cell(row=r, column=1, value=grp["note"])
            cell.font = Font(name=FONT, italic=True, size=9, color="808080")
            r += 1
        headers = ["Rank", "Vivo R$", "Claro R$", "TIM R$", "Vivo plan", "Claro plan", "TIM plan"]
        for j, h in enumerate(headers, start=1):
            cell = ws.cell(row=r, column=j, value=h)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
        r += 1
        per = grp["per_carrier"]
        for rank in range(grp["max_rank"]):
            ws.cell(row=r, column=1, value=rank + 1).font = Font(name=FONT)
            for ci, carrier in enumerate(COMPARE_CARRIERS):
                rows = per[carrier]
                if rank < len(rows):
                    price, name, gb, promo = rows[rank]
                    pcell = ws.cell(row=r, column=2 + ci, value=float(price))
                    pcell.number_format = CURRENCY_FMT
                    pcell.font = Font(name=FONT)
                    label = f"{name} ({int(gb)}GB)" if pd.notna(gb) else str(name)
                    if pd.notna(promo):
                        label += f" · promo R${float(promo):g}"
                    ws.cell(row=r, column=5 + ci, value=label).font = Font(name=FONT)
            r += 1
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
    """One sheet per carrier: plans grouped by category (bold sub-header), price-sorted."""
    for op in build_operator_sheets(latest):
        ws = xl.book.create_sheet(op["display"])
        ws.freeze_panes = "A2"
        for j, h in enumerate(OPERATOR_COLUMNS, start=1):
            cell = ws.cell(row=1, column=j, value=h)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
        r = 2
        for block in op["blocks"]:
            ws.cell(row=r, column=1, value=block["label"]).font = Font(name=FONT, bold=True, color="1F3864")
            r += 1
            for row in block["rows"]:
                for j, val in enumerate(row, start=1):
                    cell = ws.cell(row=r, column=j, value=val)
                    cell.font = Font(name=FONT)
                    if j in (2, 3):  # Price R$, Promo R$
                        cell.number_format = CURRENCY_FMT
                r += 1
        for col, w in {1: 32, 2: 11, 3: 11, 4: 22, 5: 20, 6: 18, 7: 18, 8: 40}.items():
            ws.column_dimensions[get_column_letter(col)].width = w


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
        _format_sheet(xl.sheets["history"], cur_cols, num_cols)
        _format_sheet(xl.sheets["latest"], cur_cols, num_cols)
        _format_sheet(xl.sheets["changes"], (7, 8, 9))
        _write_summary(xl, run_ts, latest_date, len(latest), history["snapshot_date"].nunique())
        _write_comparison(xl, latest)        # cross-operator comparison, from the latest snapshot
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
        cell = ws.cell(row=head_row, column=j, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
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
