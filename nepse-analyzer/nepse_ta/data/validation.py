"""Clean and validate one company's OHLC CSV.

Problems found in the real source data (verified 2026-11) and how they are handled:

* **Duplicate dates** (122 files): identical rows are collapsed; when OHLCV is the
  same but ``per_change`` differs, the row with a usable ``per_change`` is kept;
  conflicting OHLCV keeps the last row and raises a warning.
* **Unsorted rows** (104 files): sorted by date.
* **Malformed numbers / non-positive prices**: row dropped and counted. Never
  replaced with zero.
* **High/low not containing open/close** (~40k rows, mostly 2011-2018): high/low
  are widened to include open/close, the row is flagged ``ohlc_repaired`` and
  the count is reported.
* **Zero or missing volume** on a traded day: stored as NaN (unknown), never 0.
* **Prices are NOT adjusted for bonus/right shares.** The source's ``per_change``
  is computed against NEPSE's *adjusted* previous close, so a large
  disagreement between the raw move and ``per_change`` reveals the adjustment
  factor. History is back-adjusted with that factor. Jumps beyond the +/-10%
  circuit that cannot be explained are treated as breaks: only data after the
  last break is used for live analysis.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from nepse_ta.config import EXPECTED_COLUMNS, DataConfig

PRICE_COLS = ("open", "high", "low", "close")


@dataclass
class AdjustmentEvent:
    """A detected bonus/right (price-adjustment) event."""

    date: str
    factor: float
    raw_move_pct: float
    source_per_change: float


@dataclass
class PriceBreak:
    """An unexplained jump beyond the circuit limit."""

    date: str
    raw_move_pct: float


@dataclass
class CleanSeries:
    """Validated, adjusted price history for one symbol."""

    symbol: str
    df: pd.DataFrame  # full adjusted history, DatetimeIndex
    quality: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    adjustments: list[AdjustmentEvent] = field(default_factory=list)
    breaks: list[PriceBreak] = field(default_factory=list)

    @property
    def live(self) -> pd.DataFrame:
        """History after the last unexplained break (what live analysis uses)."""
        if not self.breaks:
            return self.df
        return self.df.loc[pd.Timestamp(self.breaks[-1].date) :]

    def segments(self) -> list[pd.DataFrame]:
        """Contiguous pieces separated by unexplained breaks (for backtesting)."""
        bounds: list[pd.Timestamp | None] = [None, *(pd.Timestamp(b.date) for b in self.breaks), None]
        pieces = []
        for lo, hi in zip(bounds[:-1], bounds[1:], strict=False):
            sel = self.df
            if lo is not None:
                sel = sel[sel.index >= lo]
            if hi is not None:
                sel = sel[sel.index < hi]
            if len(sel):
                pieces.append(sel)
        return pieces

    @property
    def last_date(self) -> pd.Timestamp | None:
        return self.df.index[-1] if len(self.df) else None


def read_raw_csv(path: Path) -> tuple[pd.DataFrame, int, list[str]]:
    """Read the CSV as strings. Returns (frame, malformed_row_count, header_warnings)."""
    warnings: list[str] = []
    malformed = 0
    rows: list[list[str]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            return pd.DataFrame(columns=list(EXPECTED_COLUMNS)), 0, ["खाली फाइल"]
        header = [h.strip().lstrip("﻿") for h in header]
        if header[: len(EXPECTED_COLUMNS)] != list(EXPECTED_COLUMNS):
            warnings.append(f"अपेक्षित नभएको हेडर: {header}")
        width = len(header)
        for row in reader:
            if not row or all(not c.strip() for c in row):
                continue
            if len(row) != width:
                malformed += 1
                continue
            rows.append(row)
    return pd.DataFrame(rows, columns=header), malformed, warnings


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace({"": np.nan, "nan": np.nan, "NaN": np.nan}), errors="coerce")


def clean_frame(raw: pd.DataFrame, cfg: DataConfig) -> tuple[pd.DataFrame, dict[str, int], list[str]]:
    """Type-convert, de-duplicate, sort, and sanity-check raw rows."""
    q: dict[str, int] = {"raw_rows": len(raw)}
    warns: list[str] = []
    missing_cols = [c for c in ("published_date", *PRICE_COLS) if c not in raw.columns]
    if missing_cols:
        raise ValueError(f"missing required columns: {missing_cols}")

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["published_date"], format="%Y-%m-%d", errors="coerce"),
            **{c: _to_num(raw[c]) for c in PRICE_COLS},
            "per_change": _to_num(raw["per_change"]) if "per_change" in raw else np.nan,
            "volume": _to_num(raw["traded_quantity"]) if "traded_quantity" in raw else np.nan,
            "turnover": _to_num(raw["traded_amount"]) if "traded_amount" in raw else np.nan,
        }
    )
    bad_date = df["date"].isna()
    bad_price = df[list(PRICE_COLS)].isna().any(axis=1)
    non_pos = (df[list(PRICE_COLS)] <= 0).any(axis=1) & ~bad_price
    q["bad_date_rows"] = int(bad_date.sum())
    q["non_numeric_price_rows"] = int((bad_price & ~bad_date).sum())
    q["non_positive_price_rows"] = int(non_pos.sum())
    df = df[~(bad_date | bad_price | non_pos)].copy()

    q["unsorted"] = int(not df["date"].is_monotonic_increasing)
    df = df.sort_values("date", kind="stable")

    # --- duplicates ---------------------------------------------------------
    dup_mask = df.duplicated("date", keep=False)
    q["duplicate_date_rows"] = int(dup_mask.sum())
    conflicts = 0
    if dup_mask.any():
        keep_idx = []
        for _, grp in df[dup_mask].groupby("date", sort=False):
            core = grp[list(PRICE_COLS) + ["volume"]]
            if len(core.drop_duplicates()) > 1:
                conflicts += 1
                keep_idx.append(grp.index[-1])
            else:
                usable = grp[grp["per_change"].notna() & (grp["per_change"] != 0)]
                keep_idx.append((usable if len(usable) else grp).index[-1])
        df = pd.concat([df[~dup_mask], df.loc[keep_idx]]).sort_values("date", kind="stable")
    q["conflicting_duplicates"] = conflicts
    if conflicts:
        warns.append(f"{conflicts} मितिमा फरक-फरक दोहोरिएका पङ्क्ति (अन्तिम राखियो)")

    # --- OHLC consistency ---------------------------------------------------
    hi_ok = df["high"] >= df[["open", "close", "low"]].max(axis=1)
    lo_ok = df["low"] <= df[["open", "close", "high"]].min(axis=1)
    repaired = ~(hi_ok & lo_ok)
    df["ohlc_repaired"] = repaired
    df["high"] = df[list(PRICE_COLS)].max(axis=1)
    df["low"] = df[list(PRICE_COLS)].min(axis=1)
    q["ohlc_repaired_rows"] = int(repaired.sum())

    # --- volume: zero/negative on a traded day is unknown, not zero ----------
    bad_vol = df["volume"].notna() & (df["volume"] <= 0)
    q["zero_or_negative_volume_rows"] = int(bad_vol.sum())
    df.loc[bad_vol, "volume"] = np.nan
    df.loc[df["turnover"] <= 0, "turnover"] = np.nan
    q["missing_volume_rows"] = int(df["volume"].isna().sum())

    df = df.set_index("date")
    df.index.name = "date"
    q["clean_rows"] = len(df)
    return df, q, warns


def detect_adjustments(
    df: pd.DataFrame, cfg: DataConfig
) -> tuple[list[tuple[int, AdjustmentEvent]], list[tuple[int, PriceBreak]]]:
    """Find bonus/right adjustment events and unexplained breaks (see module docstring)."""
    events: list[tuple[int, AdjustmentEvent]] = []
    breaks: list[tuple[int, PriceBreak]] = []
    closes = df["close"].to_numpy(dtype=float)
    pcs = df["per_change"].to_numpy(dtype=float)
    dates = df.index
    for i in range(1, len(df)):
        prev, cur, pc = closes[i - 1], closes[i], pcs[i]
        raw_move = (cur / prev - 1.0) * 100.0
        gap_days = (dates[i] - dates[i - 1]).days
        pc_usable = (
            math.isfinite(pc) and pc != 0.0 and abs(pc) <= cfg.circuit_limit_pct and pc > -100.0
        )
        consistent = math.isfinite(pc) and abs(raw_move - pc) <= cfg.adjustment_discrepancy_pp
        date_s = dates[i].strftime("%Y-%m-%d")
        if pc_usable and gap_days <= cfg.adjustment_max_gap_days and not consistent:
            factor = (cur / (1.0 + pc / 100.0)) / prev
            if cfg.adjustment_factor_min <= factor <= cfg.adjustment_factor_max:
                events.append((i, AdjustmentEvent(date_s, round(factor, 6), round(raw_move, 2), float(pc))))
                continue
        if abs(raw_move) > cfg.circuit_limit_pct and not consistent:
            breaks.append((i, PriceBreak(date_s, round(raw_move, 2))))
    return events, breaks


def apply_adjustments(df: pd.DataFrame, events: list[tuple[int, AdjustmentEvent]]) -> pd.DataFrame:
    """Back-adjust prices (and inversely volumes) before each event by its factor."""
    out = df.copy()
    mult = np.ones(len(out))
    for idx, ev in events:
        mult[:idx] *= ev.factor
    for c in PRICE_COLS:
        out[c] = out[c].to_numpy() * mult
    out["volume"] = out["volume"].to_numpy() / mult
    out["adj_factor"] = mult
    return out


def prepare_series(symbol: str, path: Path, cfg: DataConfig) -> CleanSeries:
    """Full pipeline for one CSV: read -> clean -> detect/apply adjustments."""
    raw, malformed, header_warn = read_raw_csv(path)
    df, q, warns = clean_frame(raw, cfg)
    q["malformed_rows"] = malformed
    warns = header_warn + warns
    if malformed:
        warns.append(f"{malformed} बिग्रिएका पङ्क्ति छोडियो")
    dropped = q["bad_date_rows"] + q["non_numeric_price_rows"] + q["non_positive_price_rows"]
    if dropped:
        warns.append(f"{dropped} अमान्य मिति/मूल्य भएका पङ्क्ति हटाइयो")
    events, breaks = detect_adjustments(df, cfg) if len(df) > 1 else ([], [])
    df = apply_adjustments(df, events)
    series = CleanSeries(
        symbol=symbol,
        df=df,
        quality=q,
        warnings=warns,
        adjustments=[e for _, e in events],
        breaks=[b for _, b in breaks],
    )
    q["adjustment_events"] = len(events)
    q["unexplained_breaks"] = len(breaks)
    return series
