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
KEY = ["carrier", "category", "state", "plan_name"]
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(name=FONT, bold=True, color="FFFFFF")
CURRENCY_FMT = 'R$ #,##0.00;[RED]-R$ #,##0.00;"-"'


def _df(plans) -> pd.DataFrame:
    rows = [p.as_row() for p in plans]
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df


def _merge_history(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    df = pd.concat([existing, fresh], ignore_index=True)
    df = df.drop_duplicates(subset=["snapshot_date"] + KEY, keep="last")
    return df.sort_values(["snapshot_date", "carrier", "category", "plan_name"]).reset_index(drop=True)


def _compute_changes(history: pd.DataFrame) -> pd.DataFrame:
    cols = ["change_type", "carrier", "category", "state", "plan_name",
            "old_price_brl", "new_price_brl", "delta_brl"]
    dates = sorted(history["snapshot_date"].dropna().unique())
    if len(dates) < 2:
        return pd.DataFrame(columns=cols)
    latest, prev = dates[-1], dates[-2]
    cur = history[history.snapshot_date == latest].set_index(KEY)
    old = history[history.snapshot_date == prev].set_index(KEY)
    out = []
    for k in cur.index.difference(old.index):
        r = cur.loc[k]
        out.append(["new", *k, None, r.price_brl, None])
    for k in old.index.difference(cur.index):
        r = old.loc[k]
        out.append(["removed", *k, r.price_brl, None, None])
    for k in cur.index.intersection(old.index):
        np_, op = cur.loc[k].price_brl, old.loc[k].price_brl
        if pd.notna(np_) and pd.notna(op) and float(np_) != float(op):
            out.append(["price_change", *k, op, np_, float(np_) - float(op)])
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
        _format_sheet(xl.sheets["changes"], (6, 7, 8))
        _write_summary(xl, run_ts, latest_date, len(latest), history["snapshot_date"].nunique())

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
