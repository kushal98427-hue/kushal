"""Support / resistance zones from confirmed swing pivots (no look-ahead)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Zone:
    """A price zone built from one or more swing pivots."""

    low: float
    high: float
    touches: int
    last_touch: str

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2

    def as_dict(self) -> dict:
        return {
            "low": round(self.low, 2),
            "high": round(self.high, 2),
            "touches": self.touches,
            "last_touch": self.last_touch,
        }


def build_zones(
    df: pd.DataFrame,
    pivots: pd.DataFrame,
    t: int,
    atr_value: float,
    lookback: int,
    merge_atr: float,
) -> list[Zone]:
    """Cluster pivots that were *confirmed* by bar ``t`` and lie within ``lookback`` bars."""
    if pivots.empty or not atr_value or atr_value <= 0:
        return []
    usable = pivots[(pivots["confirm_pos"] <= t) & (pivots["pos"] >= t - lookback)]
    if usable.empty:
        return []
    usable = usable.sort_values("price")
    tol = merge_atr * atr_value
    zones: list[Zone] = []
    members: list[tuple[float, int]] = []

    def flush() -> None:
        prices = [p for p, _ in members]
        last_pos = max(pos for _, pos in members)
        zones.append(
            Zone(
                low=min(prices),
                high=max(prices),
                touches=len(prices),
                last_touch=df.index[last_pos].strftime("%Y-%m-%d"),
            )
        )

    for price, pos in zip(usable["price"].to_numpy(), usable["pos"].to_numpy(), strict=False):
        if members and price - (sum(p for p, _ in members) / len(members)) > tol:
            flush()
            members = []
        members.append((float(price), int(pos)))
    if members:
        flush()
    return zones


def split_levels(zones: list[Zone], price: float) -> tuple[list[Zone], list[Zone]]:
    """Return (supports below price nearest-first, resistances above price nearest-first).

    A zone the price is currently inside counts as neither; it is "being tested".
    """
    supports = sorted([z for z in zones if z.high < price], key=lambda z: -z.high)
    resistances = sorted([z for z in zones if z.low > price], key=lambda z: z.low)
    return supports, resistances
