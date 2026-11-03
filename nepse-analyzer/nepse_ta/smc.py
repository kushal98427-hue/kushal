"""Market structure and SMC-style price-structure analysis (version ``smc-1``).

Exact rules: ``docs/SMC_SPEC.md`` (pre-registered, not tuned, not proven profitable).

This is an OHLCV-based price-structure interpretation. It does not and cannot see
institutional orders, "smart money", stop orders or order flow.

Causality: :class:`Engine` processes bars strictly in order. Step ``t`` reads only
bars ``0..t`` (indicator arrays are causal: ATR/relative volume at ``t`` use rows
``<= t``). Every element records ``formed_at`` = the bar whose close made it
knowable. :func:`smc_snapshot` / :meth:`Engine.snapshot` describe the state after
the last processed bar only.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from nepse_ta.indicators import atr as atr_fn

SMC_VERSION = "smc-1"
#: Bars after a BOS/CHoCH during which failure is still checked (2 × zone_max_age).
EVENT_WATCH = 240
TREND_NP = {"bullish": "bullish", "bearish": "bearish", "transition": "transition/range", "insufficient": "अपर्याप्त swing"}


@dataclass(frozen=True)
class SMCParams:
    """Pre-registered parameters (docs/SMC_SPEC.md §2). Do not tune without a new version."""

    k: int = 3
    min_swing_atr: float = 1.0
    eq_atr: float = 0.10
    eq_pct: float = 0.003
    disp_body_atr: float = 1.0
    disp_range_atr: float = 1.5
    vol_mult: float = 1.5
    sweep_atr: float = 0.10
    sweep_reaction_bars: int = 3
    bos_fail_atr: float = 0.5
    ob_lookback: int = 10
    ob_back: int = 3
    ob_min_move_atr: float = 2.0
    zone_max_age: int = 120
    eq_lookback: int = 60
    fvg_min_atr: float = 0.25
    pd_min_range_atr: float = 2.0
    circuit_pct: float = 9.5
    long_gap_days: int = 5
    atr_period: int = 14
    prev_week_levels: bool = True


DAILY = SMCParams()
WEEKLY = SMCParams(k=2, prev_week_levels=False)  # each weekly bar is a week: no separate "previous week" level


def _f(x: float | None, nd: int = 2) -> float | None:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return round(float(x), nd)


class Engine:
    """Streaming structure engine over one price series."""

    def __init__(self, df: pd.DataFrame, p: SMCParams = DAILY) -> None:
        self.p = p
        self.dates = df.index
        self.o = df["open"].to_numpy(dtype=float)
        self.h = df["high"].to_numpy(dtype=float)
        self.l = df["low"].to_numpy(dtype=float)
        self.c = df["close"].to_numpy(dtype=float)
        vol = df["volume"] if "volume" in df else pd.Series(np.nan, index=df.index)
        self.v = vol.to_numpy(dtype=float)
        # causal helpers (value at t uses rows <= t only)
        self.atr = atr_fn(df[["open", "high", "low", "close"]], p.atr_period).to_numpy()
        avg = vol.shift(1).rolling(20, min_periods=15).mean()
        self.relvol = (vol / avg).to_numpy(dtype=float)
        self.repaired = df["ohlc_repaired"].to_numpy(dtype=bool) if "ohlc_repaired" in df else np.zeros(len(df), bool)
        prev = np.concatenate([[np.nan], self.c[:-1]])
        with np.errstate(divide="ignore", invalid="ignore"):
            self.move = (self.c / prev - 1) * 100
        gaps = np.concatenate([[0], np.diff(self.dates.values).astype("timedelta64[D]").astype(int)]) if len(df) else np.array([])
        self.gap = gaps
        self.week = df.index.to_period("W-SAT") if len(df) else None
        self.t = -1
        self.swings: list[dict] = []  # every accepted swing incl. later-replaced ones (history)
        self.acc: list[dict] = []  # accepted, not replaced (chronological)
        self.events: list[dict] = []
        self.eq_zones: list[dict] = []
        self.sweeps: list[dict] = []
        self.obs: list[dict] = []
        self.fvgs: list[dict] = []
        self.counts = {"ob_no_opposite_candle": 0, "ob_insufficient_displacement": 0}
        self.prev_week_levels: dict | None = None  # {"week":…, "high":…, "low":…, "high_status":…, "low_status":…}

    # ------------------------------------------------------------------ helpers
    def _d(self, i: int) -> str:
        return self.dates[i].strftime("%Y-%m-%d")

    def _a(self, t: int) -> float:
        a = self.atr[t]
        return float(a) if np.isfinite(a) and a > 0 else float("nan")

    def _tol(self, t: int, price: float) -> float:
        return max(self.p.eq_atr * self._a(t), self.p.eq_pct * price)

    def _flags(self, idxs: list[int]) -> list[str]:
        fl = []
        if any(np.isfinite(self.move[i]) and abs(self.move[i]) >= self.p.circuit_pct for i in idxs):
            fl.append("circuit_bar")
        if any(self.gap[i] > self.p.long_gap_days for i in idxs):
            fl.append("long_gap")
        if any(self.repaired[i] for i in idxs):
            fl.append("repaired_bar")
        return fl

    def _last(self, kind: str) -> dict | None:
        for s in reversed(self.acc):
            if s["type"] == kind:
                return s
        return None

    def _accepted(self) -> list[dict]:
        return self.acc

    def _recent_acc(self, t: int):
        """Accepted swings with bar index within zone_max_age of t (newest first)."""
        for s in reversed(self.acc):
            if t - s["i"] > self.p.zone_max_age:
                break
            yield s

    def state(self) -> str:
        """Structure state from the latest accepted swing high and low labels."""
        hi, lo = self._last("high"), self._last("low")
        if not hi or not lo or hi.get("label") is None or lo.get("label") is None:
            return "insufficient"
        if hi["label"] == "HH" and lo["label"] == "HL":
            return "bullish"
        if hi["label"] == "LH" and lo["label"] == "LL":
            return "bearish"
        return "transition"

    # ------------------------------------------------------------------ main loop
    def run(self, upto: int | None = None) -> "Engine":
        end = len(self.c) - 1 if upto is None else upto
        while self.t < end:
            self.step()
        return self

    def step(self) -> None:
        self.t += 1
        t = self.t
        if not np.isfinite(self._a(t)):
            self._confirm_pivots(t)  # pivots can still be noted; filters need ATR → skipped inside
            return
        self._update_existing(t)
        self._breaks_and_sweeps(t)
        self._new_fvg(t)
        self._confirm_pivots(t)

    # 1. status updates --------------------------------------------------------
    def _update_existing(self, t: int) -> None:
        h, l, c, a = self.h[t], self.l[t], self.c[t], self._a(t)
        # Lists are in formed order, so iterating newest-first we can stop once an element is
        # older than max_age + 1 (everything older was expired on an earlier bar).
        for ob in reversed(self.obs):
            age = t - ob["formed_i"]
            if age > self.p.zone_max_age + 1:
                break
            if ob["status"] in ("invalidated", "expired") or age <= 0:
                continue
            lo, hi = ob["zone"]
            if age > self.p.zone_max_age:
                ob["status"], ob["status_at"] = "expired", self._d(t)
            elif ob["dir"] == "bullish":
                if c < lo:
                    ob["status"], ob["status_at"] = "invalidated", self._d(t)
                elif l <= hi:
                    ob["tests"] += 1
                    ob["status"] = "tested"
                    ob.setdefault("first_test", self._d(t))
            else:
                if c > hi:
                    ob["status"], ob["status_at"] = "invalidated", self._d(t)
                elif h >= lo:
                    ob["tests"] += 1
                    ob["status"] = "tested"
                    ob.setdefault("first_test", self._d(t))
        for g in reversed(self.fvgs):
            age = t - g["formed_i"]
            if age > self.p.zone_max_age + 1:
                break
            if g["status"] in ("filled", "invalidated", "expired") or age <= 0:
                continue
            if age > self.p.zone_max_age:
                g["status"], g["status_at"] = "expired", self._d(t)
                continue
            lo, hi = g["zone"]
            if g["dir"] == "bullish":
                g["extreme"] = min(g["extreme"], l)
                g["fill_pct"] = int(round(100 * min(1.0, max(0.0, (hi - g["extreme"]) / (hi - lo)))))
                if c < lo:
                    g["status"], g["status_at"] = "invalidated", self._d(t)
                elif g["extreme"] <= lo:
                    g["status"], g["status_at"] = "filled", self._d(t)
                elif g["extreme"] < hi:
                    g["status"] = "partially_filled"
            else:
                g["extreme"] = max(g["extreme"], h)
                g["fill_pct"] = int(round(100 * min(1.0, max(0.0, (g["extreme"] - lo) / (hi - lo)))))
                if c > hi:
                    g["status"], g["status_at"] = "invalidated", self._d(t)
                elif g["extreme"] >= hi:
                    g["status"], g["status_at"] = "filled", self._d(t)
                elif g["extreme"] > lo:
                    g["status"] = "partially_filled"
        for s in reversed(self.sweeps):
            if t - s["i"] > self.p.sweep_reaction_bars + 1:
                break
            if s["status"] != "pending":
                continue
            i = s["i"]
            if t - i > self.p.sweep_reaction_bars:
                s["status"] = "unconfirmed"
                continue
            if s["implication"] == "bullish":  # sell-side swept below
                if c > self.h[i]:
                    s["status"], s["resolved_at"] = "reaction_confirmed", self._d(t)
                elif c < s["level"]:
                    s["status"], s["resolved_at"] = "accepted", self._d(t)
            else:
                if c < self.l[i]:
                    s["status"], s["resolved_at"] = "reaction_confirmed", self._d(t)
                elif c > s["level"]:
                    s["status"], s["resolved_at"] = "accepted", self._d(t)
        # A break stays monitored for failure for at most EVENT_WATCH bars (documented in the spec).
        for e in reversed(self.events):
            if t - e["i"] > EVENT_WATCH:
                break
            if e["i"] >= t or e["status"] not in ("intact", "confirmed_close", "structure_confirmed"):
                continue
            if e["type"] == "BOS":
                if e["dir"] == "bullish" and c < e["level"] - self.p.bos_fail_atr * a:
                    e["status"], e["status_at"] = "failed_bos", self._d(t)
                elif e["dir"] == "bearish" and c > e["level"] + self.p.bos_fail_atr * a:
                    e["status"], e["status_at"] = "failed_bos", self._d(t)
            elif e["type"] == "CHoCH" and e.get("origin") is not None:
                if e["dir"] == "bullish" and c < e["origin"]:
                    e["status"], e["status_at"] = "failed_choch", self._d(t)
                elif e["dir"] == "bearish" and c > e["origin"]:
                    e["status"], e["status_at"] = "failed_choch", self._d(t)

    # 2. breaks and sweeps -------------------------------------------------------
    def _breaks_and_sweeps(self, t: int) -> None:
        o, h, l, c, a = self.o[t], self.h[t], self.l[t], self.c[t], self._a(t)
        state = self.state()
        sides: set[str] = set()
        single_price = h == l
        self._roll_week(t)

        for side in ("high", "low"):
            ref = self._last(side)
            if ref is not None and ref["status"] != "broken" and ref["formed_i"] < t:
                lvl = ref["price"]
                if (side == "high" and c > lvl) or (side == "low" and c < lvl):
                    ref["status"], ref["broken_at"] = "broken", self._d(t)
                    self._break_event(t, side, ref, state)
                    sides.add(side)
            # sweeps of intact liquidity levels on this side (wick beyond, close back inside)
            if single_price:
                continue
            levels = []
            for s in self._recent_acc(t):
                if s["type"] != side or s["formed_i"] >= t:
                    continue
                if s["status"] == "broken":
                    continue
                if (side == "high" and c > s["price"]) or (side == "low" and c < s["price"]):
                    s["status"], s["broken_at"] = "broken", self._d(t)
                    continue
                if s["status"] == "intact" and self._beyond(side, h, l, s["price"], a):
                    s["status"], s["swept_at"] = "swept", self._d(t)
                    levels.append(("swing", s["price"], self._d(s["i"])))
            for z in reversed(self.eq_zones):
                if t - z["formed_i"] > self.p.zone_max_age + 1:
                    break
                if z["side"] != side or z["status"] != "intact" or z["formed_i"] >= t:
                    continue
                if t - z["formed_i"] > self.p.zone_max_age:
                    z["status"], z["status_at"] = "expired", self._d(t)
                    continue
                edge = z["zone"][1] if side == "high" else z["zone"][0]
                if (side == "high" and c > edge) or (side == "low" and c < edge):
                    z["status"], z["status_at"] = "broken", self._d(t)
                elif self._beyond(side, h, l, edge, a):
                    z["status"], z["status_at"] = "swept", self._d(t)
                    levels.append(("equal_" + ("highs" if side == "high" else "lows"), edge, z["formed_at"]))
            pw = self.prev_week_levels
            if pw is not None:
                key = f"{side}_status"
                lvl = pw[side]
                if pw[key] == "intact":
                    if (side == "high" and c > lvl) or (side == "low" and c < lvl):
                        pw[key] = "broken"
                    elif self._beyond(side, h, l, lvl, a):
                        pw[key] = "swept"
                        levels.append(("previous_week_" + side, lvl, str(pw["week"])))
            if levels:  # wick beyond an intact level that closed back inside (may co-exist with a lower break)
                best = max(levels, key=lambda x: x[1]) if side == "high" else min(levels, key=lambda x: x[1])
                self.sweeps.append(
                    {
                        "implication": "bearish" if side == "high" else "bullish",
                        "side": "buy_side" if side == "high" else "sell_side",
                        "level": _f(best[1]),
                        "level_type": best[0],
                        "levels": [{"type": x[0], "level": _f(x[1]), "ref": x[2]} for x in levels],
                        "i": t,
                        "date": self._d(t),
                        "wick_beyond_atr": _f((h - best[1]) / a if side == "high" else (best[1] - l) / a),
                        "close": _f(c),
                        "status": "pending",
                        "flags": self._flags([t]),
                    }
                )
                sides.add(side)
        if len(sides) == 2:
            for coll in (self.events[-3:], self.sweeps[-3:]):
                for e in coll:
                    if e["i"] == t and "two_sided" not in e["flags"]:
                        e["flags"].append("two_sided")
        _ = o

    def _beyond(self, side: str, h: float, l: float, lvl: float, a: float) -> bool:
        if side == "high":
            return h >= lvl + self.p.sweep_atr * a
        return l <= lvl - self.p.sweep_atr * a

    def _break_event(self, t: int, side: str, ref: dict, state: str) -> None:
        a = self._a(t)
        direction = "bullish" if side == "high" else "bearish"
        if (direction == "bullish" and state == "bullish") or (direction == "bearish" and state == "bearish"):
            etype = "BOS"
        elif (direction == "bullish" and state == "bearish") or (direction == "bearish" and state == "bullish"):
            etype = "CHoCH"
        else:
            etype = "range_break"
        body = abs(self.c[t] - self.o[t])
        rng = self.h[t] - self.l[t]
        strong = body >= self.p.disp_body_atr * a or rng >= self.p.disp_range_atr * a
        rv = self.relvol[t]
        vol = "volume_unknown" if not np.isfinite(rv) else ("volume_supported" if rv >= self.p.vol_mult else "volume_not_supported")
        origin_sw = self._last("low" if direction == "bullish" else "high")
        ev = {
            "type": etype,
            "dir": direction,
            "level": _f(ref["price"]),
            "level_swing_date": self._d(ref["i"]),
            "level_label": ref.get("label"),
            "i": t,
            "date": self._d(t),
            "close": _f(self.c[t]),
            "displacement": "strong" if strong else "weak",
            "body_atr": _f(body / a),
            "range_atr": _f(rng / a),
            "rel_volume": _f(rv) if np.isfinite(rv) else None,
            "volume": vol,
            "state_before": state,
            "status": "intact" if etype != "CHoCH" else "confirmed_close",
            "flags": self._flags([t]),
        }
        if etype == "CHoCH":
            ev["mss_like"] = strong
            ev["origin"] = _f(origin_sw["price"]) if origin_sw else None
            ev["origin_date"] = self._d(origin_sw["i"]) if origin_sw else None
        self.events.append(ev)
        if etype in ("BOS", "CHoCH"):
            self._order_block(t, direction, ev, ref["i"])

    # 3. order blocks -------------------------------------------------------------
    def _order_block(self, j: int, direction: str, ev: dict, ref_i: int) -> None:
        # leg = bars after the broken reference swing up to the break bar, at most ob_lookback back
        lo_i = max(0, j - self.p.ob_lookback, ref_i + 1)
        win = range(lo_i, j + 1)
        if direction == "bullish":
            ext = min(self.l[i] for i in win)
            L = max(i for i in win if self.l[i] == ext)  # latest index of the minimum
            cand = [i for i in range(L, max(L - self.p.ob_back, 0) - 1, -1) if self.c[i] < self.o[i]]
        else:
            ext = max(self.h[i] for i in win)
            L = max(i for i in win if self.h[i] == ext)
            cand = [i for i in range(L, max(L - self.p.ob_back, 0) - 1, -1) if self.c[i] > self.o[i]]
        if not cand:
            self.counts["ob_no_opposite_candle"] += 1
            return
        k = cand[0]
        move = (self.c[j] - self.l[k]) if direction == "bullish" else (self.h[k] - self.c[j])
        if move < self.p.ob_min_move_atr * self._a(j):
            self.counts["ob_insufficient_displacement"] += 1
            return
        self.obs.append(
            {
                "dir": direction,
                "zone": [_f(self.l[k]), _f(self.h[k])],
                "body": [_f(min(self.o[k], self.c[k])), _f(max(self.o[k], self.c[k]))],
                "candle_date": self._d(k),
                "formed_i": j,
                "formed_at": self._d(j),
                "from_event": ev["type"],
                "displacement_atr": _f(move / self._a(j)),
                "status": "fresh",
                "tests": 0,
                "flags": self._flags([k, j]),
            }
        )

    # 4. fair value gaps -------------------------------------------------------------
    def _new_fvg(self, i: int) -> None:
        if i < 2:
            return
        a = self._a(i)
        if self.l[i] > self.h[i - 2] and self.l[i] - self.h[i - 2] >= self.p.fvg_min_atr * a:
            zone, d, ext = [self.h[i - 2], self.l[i]], "bullish", self.l[i]
        elif self.h[i] < self.l[i - 2] and self.l[i - 2] - self.h[i] >= self.p.fvg_min_atr * a:
            zone, d, ext = [self.h[i], self.l[i - 2]], "bearish", self.h[i]
        else:
            return
        fl = self._flags([i - 1, i])
        if (self.dates[i] - self.dates[i - 2]).days > self.p.long_gap_days and "long_gap" not in fl:
            fl.append("long_gap")
        self.fvgs.append(
            {
                "dir": d,
                "zone": [_f(zone[0]), _f(zone[1])],
                "size_atr": _f((zone[1] - zone[0]) / a),
                "formed_i": i,
                "formed_at": self._d(i),
                "status": "unfilled",
                "fill_pct": 0,
                "extreme": ext,
                "flags": fl,
            }
        )

    # 5. swings ------------------------------------------------------------------------
    def _confirm_pivots(self, t: int) -> None:
        k = self.p.k
        i = t - k
        if i < k:
            return
        hs, ls = self.h, self.l
        if hs[i] > hs[i - k : i].max() and hs[i] >= hs[i + 1 : t + 1].max():
            self._candidate("high", i, t)
        if ls[i] < ls[i - k : i].min() and ls[i] <= ls[i + 1 : t + 1].min():
            self._candidate("low", i, t)

    def _candidate(self, kind: str, i: int, t: int) -> None:
        a = self._a(t)
        if not np.isfinite(a):
            return
        price = self.h[i] if kind == "high" else self.l[i]
        acc = self._accepted()
        last = acc[-1] if acc else None
        if last is not None and last["type"] == kind:
            more_extreme = price > last["price"] if kind == "high" else price < last["price"]
            if not more_extreme:
                return
            # more extreme than the swing it replaces, so it is at least as far from the
            # opposite swing: the size filter cannot fail here
            last["replaced"] = True
            last["replaced_at"] = self._d(t)
            self.acc.pop()
        elif last is not None and abs(price - last["price"]) < self.p.min_swing_atr * a:
            return
        prev_same = self._last(kind)
        label = None
        if prev_same is not None:
            tol = self._tol(t, price)
            if price > prev_same["price"] + tol:
                label = "HH" if kind == "high" else "HL"
            elif price < prev_same["price"] - tol:
                label = "LH" if kind == "high" else "LL"
            else:
                label = "EH" if kind == "high" else "EL"
        sw = {
            "type": kind,
            "i": i,
            "date": self._d(i),
            "price": float(price),
            "label": label,
            "formed_i": t,
            "formed_at": self._d(t),
            "status": "intact",
            "flags": self._flags([i]),
        }
        # mark intact/broken against bars between i and t (already happened before confirmation)
        later = slice(i + 1, t + 1)
        if kind == "high" and (self.c[later] > price).any():
            sw["status"] = "broken"
        if kind == "low" and (self.c[later] < price).any():
            sw["status"] = "broken"
        self.swings.append(sw)
        self.acc.append(sw)
        self._equal_zone(sw, t)
        # CHoCH structure confirmation: first accepted swing of the opposite side beyond origin
        for e in reversed(self.events):
            if e["type"] != "CHoCH" or e["status"] != "confirmed_close" or e["i"] > i:
                continue
            if e["dir"] == "bullish" and kind == "low" and e.get("origin") is not None and price > e["origin"]:
                e["status"], e["status_at"] = "structure_confirmed", self._d(t)
            if e["dir"] == "bearish" and kind == "high" and e.get("origin") is not None and price < e["origin"]:
                e["status"], e["status_at"] = "structure_confirmed", self._d(t)
            break

    def _equal_zone(self, sw: dict, t: int) -> None:
        tol = self._tol(t, sw["price"])
        for other in reversed(self.acc[:-1]):
            if other["type"] != sw["type"]:
                continue
            if sw["i"] - other["i"] > self.p.eq_lookback:
                break
            if other["status"] == "broken":
                continue
            if abs(other["price"] - sw["price"]) <= tol:
                lo, hi = sorted([other["price"], sw["price"]])
                self.eq_zones.append(
                    {
                        "side": sw["type"],
                        "zone": [_f(lo), _f(hi)],
                        "swing_dates": [other["date"], sw["date"]],
                        "formed_i": t,
                        "formed_at": self._d(t),
                        "status": "intact",
                    }
                )
                return

    # previous completed week (for liquidity levels) ------------------------------------
    def _roll_week(self, t: int) -> None:
        if self.week is None or not self.p.prev_week_levels:
            return
        cur = self.week[t]
        if self.prev_week_levels is not None and self.prev_week_levels.get("_cur") == cur:
            return
        idx = [i for i in range(max(0, t - 15), t) if self.week[i] != cur]
        if not idx:
            self.prev_week_levels = {"_cur": cur, "week": None, "high": float("nan"), "low": float("nan"), "high_status": "na", "low_status": "na"}
            return
        last_week = self.week[idx[-1]]
        sel = [i for i in idx if self.week[i] == last_week]
        self.prev_week_levels = {
            "_cur": cur,
            "week": str(last_week),
            "high": float(self.h[sel].max()),
            "low": float(self.l[sel].min()),
            "high_status": "intact",
            "low_status": "intact",
        }

    # ------------------------------------------------------------------ snapshot
    def snapshot(self) -> dict:
        """State after the last processed bar (``self.t``)."""
        t = self.t
        if t < 0:
            return {"status": "insufficient_history"}
        price = float(self.c[t])
        acc = self._accepted()
        swings = [
            {k: (_f(v) if k == "price" else v) for k, v in s.items() if k in ("type", "date", "price", "label", "formed_at", "status", "flags")}
            for s in acc[-4:]
        ]
        hi, lo = self._last("high"), self._last("low")
        last_ev = self.events[-1] if self.events else None
        recent_sweeps = [s for s in self.sweeps if t - s["i"] <= 20][-3:]
        active_ob = [o for o in self.obs if o["status"] in ("fresh", "tested") and t - o["formed_i"] <= self.p.zone_max_age]
        active_fvg = [g for g in self.fvgs if g["status"] in ("unfilled", "partially_filled") and t - g["formed_i"] <= 60]
        eq = [z for z in self.eq_zones if z["status"] == "intact"]

        def strip(d: dict, drop=("i", "formed_i", "extreme")) -> dict:
            return {k: v for k, v in d.items() if k not in drop}

        def nearest(items: list[dict], key, n: int) -> list[dict]:
            return sorted(items, key=key)[:n]

        below = lambda z: z["zone"][1] <= price  # noqa: E731
        above = lambda z: z["zone"][0] >= price  # noqa: E731
        obs_out = nearest([o for o in active_ob if below(o)], lambda z: price - z["zone"][1], 2) + nearest(
            [o for o in active_ob if above(o)], lambda z: z["zone"][0] - price, 2
        )
        fvg_out = nearest([g for g in active_fvg if below(g)], lambda z: price - z["zone"][1], 2) + nearest(
            [g for g in active_fvg if above(g)], lambda z: z["zone"][0] - price, 2
        )
        liq_above = sorted(
            [{"type": "swing_high", "level": _f(s["price"]), "date": s["date"], "status": s["status"]} for s in acc
             if s["type"] == "high" and s["status"] != "broken" and s["price"] > price and t - s["i"] <= self.p.zone_max_age]
            + [{"type": "equal_highs", "level": z["zone"][1], "zone": z["zone"], "date": z["formed_at"], "status": z["status"]} for z in eq
               if z["side"] == "high" and z["zone"][1] > price],
            key=lambda x: x["level"],
        )[:3]
        liq_below = sorted(
            [{"type": "swing_low", "level": _f(s["price"]), "date": s["date"], "status": s["status"]} for s in acc
             if s["type"] == "low" and s["status"] != "broken" and s["price"] < price and t - s["i"] <= self.p.zone_max_age]
            + [{"type": "equal_lows", "level": z["zone"][0], "zone": z["zone"], "date": z["formed_at"], "status": z["status"]} for z in eq
               if z["side"] == "low" and z["zone"][0] < price],
            key=lambda x: -x["level"],
        )[:3]
        # wick-only break of the current reference level against the structure = tentative CHoCH
        choch_watch = None
        st = self.state()
        for sw_ev in reversed(self.sweeps):
            if t - sw_ev["i"] > 5:
                break
            if sw_ev["level_type"] != "swing":
                continue
            if st == "bearish" and hi and hi["status"] != "broken" and sw_ev["side"] == "buy_side" and sw_ev["level"] == _f(hi["price"]):
                choch_watch = {"status": "tentative", "dir": "bullish", "level": _f(hi["price"]), "date": sw_ev["date"],
                               "note": "wick above the last LH, close back below: not a CHoCH until a close above"}
            if st == "bullish" and lo and lo["status"] != "broken" and sw_ev["side"] == "sell_side" and sw_ev["level"] == _f(lo["price"]):
                choch_watch = {"status": "tentative", "dir": "bearish", "level": _f(lo["price"]), "date": sw_ev["date"],
                               "note": "wick below the last HL, close back above: not a CHoCH until a close below"}
            if choch_watch:
                break
        pending = []
        if t >= 1:
            pending.append(f"पछिल्ला {self.p.k} bar का सम्भावित swing अझै confirm भएका छैनन्")
        return {
            "status": "ok",
            "as_of": self._d(t),
            "close": _f(price),
            "atr": _f(self._a(t)),
            "state": self.state(),
            "swings": swings,
            "reference_high": _f(hi["price"]) if hi and hi["status"] != "broken" else None,
            "reference_low": _f(lo["price"]) if lo and lo["status"] != "broken" else None,
            "last_event": strip(last_ev) if last_ev else None,
            "choch_watch": choch_watch,
            "sweeps": [strip(s) for s in recent_sweeps],
            "order_blocks": [strip(o) for o in obs_out],
            "fvgs": [strip(g) for g in fvg_out],
            "liquidity_above": liq_above,
            "liquidity_below": liq_below,
            "premium_discount": self._premium_discount(price),
            "pending": pending,
            "debug_counts": dict(self.counts),
        }

    def _premium_discount(self, price: float) -> dict:
        ev = next((e for e in reversed(self.events) if e["type"] in ("BOS", "CHoCH")), None)
        if ev is None:
            return {"status": "range_unclear", "reason": "no BOS/CHoCH yet"}
        j = ev["i"]
        acc = self._accepted()
        if ev["dir"] == "bullish":
            origin = next((s for s in reversed(acc) if s["type"] == "low" and s["i"] < j), None)
            after = [s for s in acc if s["type"] == "high" and s["i"] > j]
            if origin is None or not after:
                return {"status": "range_open", "reason": "no confirmed swing high after the break"}
            lo_p, hi_p = origin["price"], float(self.h[origin["i"] : self.t + 1].max())
        else:
            origin = next((s for s in reversed(acc) if s["type"] == "high" and s["i"] < j), None)
            after = [s for s in acc if s["type"] == "low" and s["i"] > j]
            if origin is None or not after:
                return {"status": "range_open", "reason": "no confirmed swing low after the break"}
            hi_p, lo_p = origin["price"], float(self.l[origin["i"] : self.t + 1].min())
        a = self._a(self.t)
        if hi_p - lo_p < self.p.pd_min_range_atr * a:
            return {"status": "range_unclear", "reason": "range smaller than 2 ATR"}
        eq = (hi_p + lo_p) / 2
        return {
            "status": "ok",
            "leg": ev["dir"],
            "range": [_f(lo_p), _f(hi_p)],
            "equilibrium": _f(eq),
            "position": "discount" if price < eq else "premium",
            "position_pct": _f((price - lo_p) / (hi_p - lo_p) * 100, 1),
        }


def completed_weeks(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly W-SAT bars from daily rows, excluding the week of the last row (always incomplete)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    empty = pd.DataFrame(columns=[*agg, "ohlc_repaired"], index=pd.DatetimeIndex([]))
    if df.empty:
        return empty
    wk = df.index.to_period("W-SAT")
    cur = wk[-1]
    sel = df[wk != cur]
    if sel.empty:
        return empty  # same shape whatever the input, so empty results compare equal
    out = sel[list(agg)].groupby(sel.index.to_period("W-SAT")).agg(agg)
    out.index = out.index.to_timestamp(how="end").normalize()
    out["ohlc_repaired"] = sel["ohlc_repaired"].groupby(sel.index.to_period("W-SAT")).any().to_numpy() if "ohlc_repaired" in sel else False
    return out


def volume_behaviour(df: pd.DataFrame, n: int = 20) -> dict:
    """Up-day vs down-day volume over the last n bars (no buy/sell split exists in the data)."""
    tail = df.iloc[-(n + 1) :]
    if len(tail) < n + 1 or tail["volume"].isna().mean() > 0.2:
        return {"status": "unavailable", "reason": "insufficient or unreliable volume"}
    chg = tail["close"].diff().iloc[1:]
    vol = tail["volume"].iloc[1:]
    up, dn = float(vol[chg > 0].sum()), float(vol[chg < 0].sum())
    if dn == 0:
        return {"status": "ok", "ratio": None, "label": "no_down_days"}
    r = up / dn
    label = "accumulation_like" if r > 1.5 else "distribution_like" if r < 0.67 else "neutral"
    return {"status": "ok", "up_down_volume_ratio": _f(r), "label": label, "window": n,
            "note": "up-day vs down-day total volume only; not buyer/seller identification"}


def smc_snapshot(df: pd.DataFrame, min_bars: int = 60) -> dict:
    """Full ``smc`` section for the last row of ``df`` (bars ≤ that date only)."""
    if len(df) < min_bars:
        return {"status": "insufficient_history", "version": SMC_VERSION, "bars": len(df)}
    daily = Engine(df, DAILY).run().snapshot()
    wk = completed_weeks(df)
    weekly = Engine(wk, WEEKLY).run().snapshot() if len(wk) >= 30 else {"status": "insufficient_history", "weeks": len(wk)}
    ws = weekly.get("state", "insufficient")
    ds = daily["state"]
    if ds in ("bullish", "bearish") and ws in ("bullish", "bearish"):
        alignment = f"aligned_{ds}" if ds == ws else "countertrend"
    else:
        alignment = "unclear"
    out = {
        "status": "ok",
        "version": SMC_VERSION,
        "kind": "OHLCV-based price-structure interpretation (no order-flow or institutional data)",
        "daily": daily,
        "weekly": {k: weekly.get(k) for k in ("status", "as_of", "state", "swings", "reference_high", "reference_low", "last_event")},
        "alignment": alignment,
        "volume_behaviour": volume_behaviour(df),
        "unavailable": ["lower_timeframe (no intraday data)", "order_flow / real liquidity (no order-book data)"],
    }
    out["explanation"] = explain(out)
    return out


# ---------------------------------------------------------------------- explanation
EVENT_NP = {"BOS": "BOS (structure continuation)", "CHoCH": "CHoCH (structure परिवर्तन)", "range_break": "range break"}
STATUS_NP = {
    "intact": "अझै कायम", "confirmed_close": "close ले पुष्टि, structure पुष्टि बाँकी", "structure_confirmed": "नयाँ swing ले पुष्टि",
    "failed_bos": "असफल (फर्कियो)", "failed_choch": "असफल (origin तल/माथि close)",
}


def _n(x: float | None) -> str:
    return "—" if x is None else f"{x:.2f}"


def explain(s: dict) -> list[dict]:
    """Observation → evidence → interpretation → confirm → invalidate → implication, from computed fields only."""
    d = s["daily"]
    items: list[dict] = []
    sw = d["swings"]
    hi = next((x for x in reversed(sw) if x["type"] == "high"), None)
    lo = next((x for x in reversed(sw) if x["type"] == "low"), None)
    st = d["state"]
    if hi and lo:
        items.append(
            {
                "topic": "structure",
                "observation": f"Daily structure: {TREND_NP[st]}",
                "evidence": f"पछिल्लो swing high {_n(hi['price'])} ({hi['label'] or 'पहिलो'}, {hi['date']}), swing low {_n(lo['price'])} ({lo['label'] or 'पहिलो'}, {lo['date']})",
                "interpretation": {
                    "bullish": "Higher high र higher low — price structure माथि तर्फ",
                    "bearish": "Lower high र lower low — price structure तल तर्फ",
                }.get(st, "स्पष्ट HH/HL वा LH/LL क्रम छैन"),
                "confirm": f"{_n(d['reference_high'])} माथि daily close" if d["reference_high"] else "नयाँ swing high confirm हुनुपर्छ",
                "invalidate": f"{_n(d['reference_low'])} तल daily close" if d["reference_low"] else "नयाँ swing low confirm हुनुपर्छ",
                "implication": "Structure अनुसार मात्र दिशा; entry को निर्णय Phase 6 को नियमले गर्छ",
            }
        )
    ev = d.get("last_event")
    if ev:
        items.append(
            {
                "topic": "last_break",
                "observation": f"{ev['date']} मा {ev['dir']} {EVENT_NP[ev['type']]}",
                "evidence": f"close {_n(ev['close'])} ले level {_n(ev['level'])} ({ev['level_swing_date']}) पार गर्यो; displacement {ev['displacement']}, {ev['volume']}",
                "interpretation": "Close-confirmed break" + (" (MSS-like)" if ev.get("mss_like") else ""),
                "confirm": (f"Retest मा {_n(ev['level'])} {'माथि' if ev['dir'] == 'bullish' else 'तल'} टिक्नु"
                            if ev["status"] in ("intact", "confirmed_close") else "—"),
                "invalidate": (f"origin {_n(ev.get('origin'))} {'तल' if ev['dir'] == 'bullish' else 'माथि'} close" if ev["type"] == "CHoCH"
                               else f"{_n(ev['level'])} भन्दा 0.5 ATR {'तल' if ev['dir'] == 'bullish' else 'माथि'} close"),
                "implication": f"हालको अवस्था: {STATUS_NP.get(ev['status'], ev['status'])}",
            }
        )
    for ob in d["order_blocks"][:2]:
        items.append(
            {
                "topic": "order_block",
                "observation": f"Potential {ob['dir']} order block (price-based) {_n(ob['zone'][0])}–{_n(ob['zone'][1])}",
                "evidence": f"{ob['candle_date']} को opposite candle, {ob['formed_at']} को {ob['from_event']} पछि; status {ob['status']}",
                "interpretation": "Displacement अघिको अन्तिम उल्टो candle — सम्भावित reaction zone, गारन्टी होइन",
                "confirm": "Zone मा price आएर rejection candle",
                "invalidate": f"{_n(ob['zone'][0] if ob['dir'] == 'bullish' else ob['zone'][1])} पार close",
                "implication": "Flags: " + (", ".join(ob["flags"]) or "छैन"),
            }
        )
    for g in d["fvgs"][:2]:
        items.append(
            {
                "topic": "fvg",
                "observation": f"{g['dir']} FVG {_n(g['zone'][0])}–{_n(g['zone'][1])} ({g['formed_at']})",
                "evidence": f"status {g['status']}, fill {g['fill_pct']}%",
                "interpretation": "तीन candle बीचको price gap — price फर्केर भर्न सक्छ, गारन्टी होइन",
                "confirm": "Gap भित्र reaction",
                "invalidate": "Gap को टाढाको छेउ पार close",
                "implication": "Flags: " + (", ".join(g["flags"]) or "छैन"),
            }
        )
    if d["liquidity_above"] or d["liquidity_below"]:
        up = d["liquidity_above"][0] if d["liquidity_above"] else None
        dn = d["liquidity_below"][0] if d["liquidity_below"] else None
        items.append(
            {
                "topic": "liquidity",
                "observation": "Potential liquidity levels (swing/equal highs-lows)",
                "evidence": (f"माथि {up['type']} {_n(up['level'])}" if up else "माथि छैन") + "; " + (f"तल {dn['type']} {_n(dn['level'])}" if dn else "तल छैन"),
                "interpretation": "यी level माथि/तल stop order हुन सक्ने ठाउँ मानिन्छ — data ले वास्तविक order देखाउँदैन",
                "confirm": "Wick ले पार गरेर close भित्र फर्के sweep-like behaviour",
                "invalidate": "Level पार close (accepted)",
                "implication": "Target/risk योजना Phase 6 मा",
            }
        )
    pd_ = d["premium_discount"]
    if pd_.get("status") == "ok":
        items.append(
            {
                "topic": "premium_discount",
                "observation": f"Price {pd_['position']} मा ({_n(pd_['position_pct'])}% of range)",
                "evidence": f"Range {_n(pd_['range'][0])}–{_n(pd_['range'][1])}, equilibrium {_n(pd_['equilibrium'])}",
                "interpretation": "Discount = range को तल्लो आधा, premium = माथिल्लो आधा",
                "confirm": "—",
                "invalidate": "Range को छेउ पार भए नयाँ range",
                "implication": "Long को लागि discount तुलनात्मक रूपमा राम्रो स्थान मानिन्छ",
            }
        )
    items.append(
        {
            "topic": "alignment",
            "observation": f"Weekly {s['weekly'].get('state')} / daily {st} → {s['alignment']}",
            "evidence": "Weekly मा पूरा भएका हप्ता मात्र",
            "interpretation": "Countertrend भए थप प्रमाण चाहिन्छ" if s["alignment"] == "countertrend" else "—",
            "confirm": "—",
            "invalidate": "—",
            "implication": "—",
        }
    )
    return items


def as_params(p: SMCParams) -> dict:
    return asdict(p)
