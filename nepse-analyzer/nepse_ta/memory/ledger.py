"""Recommendation ledger: system recommendations and their paper-trading outcomes.

A *recommendation* is what the system suggested. It is NOT a user trade: the
system never assumes you executed it. Outcomes are hypothetical, computed with
the documented execution model ``exec-1``:

Entry (pending phase)
    The plan is created at the close of its trading date T. For up to
    ``entry_valid_sessions`` following bars of that stock:

    * open inside [entry_low, entry_high × (1 + max_entry_gap_pct)] → filled at the open + slippage;
    * open above that → a limit order at entry_high fills if the bar's low reaches it;
    * open below entry_low (setup weakened) → filled at entry_low only if the bar trades back
      up into the zone without touching the stop (no buying below the zone);
    * open at/below the stop, or low reaching the stop before a fill → ``invalidated_before_entry``;
    * high reaching Target 1 without a fill → ``missed_without_entry`` (not counted as a win);
    * the stock's next bar more than ``max_entry_delay_days`` calendar days later → ``expired_stale``;
    * otherwise after the window → ``expired_not_triggered``.

Holding
    No sale for ``min_hold_sessions`` bars (NEPSE T+2 settlement); stop before
    target when both are inside one bar; gaps fill at the open; full exit at
    Target 1; time exit at the close after ``max_hold_sessions`` bars.

Costs
    Same model as the backtest (commission, SEBON, DP, slippage, CGT on gains).

Corporate actions
    Stored prices are as of the creation date. If a bonus/right adjustment
    happens later, the validated series back-adjusts history; stored levels are
    multiplied by the same factor so a mechanical price drop is never counted
    as a loss (economic return is preserved).

Events are append-only. Re-evaluating with the same data produces the same
events (idempotent). If the source data for past bars changes so that a stored
event no longer matches, a ``correction`` event is appended; nothing is edited.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from nepse_ta.backtest import net_return
from nepse_ta.config import EXECUTION_MODEL_VERSION, CostConfig

TERMINAL = {
    "closed",
    "invalidated_before_entry",
    "missed_without_entry",
    "expired_not_triggered",
    "expired_stale",
    "withdrawn",
    "data_missing",
}


@dataclass(frozen=True)
class ExecConfig:
    """Paper-trading execution model ``exec-1``."""

    version: str = EXECUTION_MODEL_VERSION
    entry_valid_sessions: int = 3
    max_entry_gap_pct: float = 1.0
    max_entry_delay_days: int = 5
    min_hold_sessions: int = 3
    max_hold_sessions: int = 20
    costs: CostConfig = field(default_factory=CostConfig)


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None else round(float(x), nd)


def evaluate(rec: dict, bars: pd.DataFrame, cfg: ExecConfig = ExecConfig()) -> list[dict]:
    """Deterministically compute the outcome events of one recommendation.

    ``rec`` is the ``created`` event (latest plan applied); ``bars`` is the validated,
    adjusted daily frame of that stock (index = dates, includes ``adj_factor``).
    Returns events after ``created`` (possibly empty while waiting for new bars).
    """
    created = pd.Timestamp(rec["trading_date"])
    if created not in bars.index:
        return [{"type": "data_missing", "date": rec["trading_date"], "reason": "signal date not in current data"}]
    adj = float(bars["adj_factor"].loc[created]) if "adj_factor" in bars else 1.0
    plan = rec["plan"]
    lo, hi = plan["entry_low"] * adj, plan["entry_high"] * adj
    stop, t1 = plan["stop"] * adj, plan["target1"] * adj
    adj_note = None if abs(adj - 1) < 1e-9 else round(adj, 6)
    after = bars.loc[bars.index > created]
    o, h, low, c = (after[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    dates = after.index
    slip = cfg.costs.slippage_pct / 100
    events: list[dict] = []

    # ---- pending phase ---------------------------------------------------
    fill_idx, entry_px, fill_kind = None, None, None
    prev_date = created
    for i in range(min(cfg.entry_valid_sessions, len(after))):
        d = dates[i].strftime("%Y-%m-%d")
        if (dates[i] - prev_date).days > cfg.max_entry_delay_days:
            return [{"type": "expired_stale", "date": d, "reason": f"no trade for {(dates[i] - prev_date).days} days"}]
        prev_date = dates[i]
        cap = hi * (1 + cfg.max_entry_gap_pct / 100)
        if lo <= o[i] <= cap:
            fill_idx, entry_px, fill_kind = i, o[i] * (1 + slip), "open"
        elif o[i] > cap and low[i] <= hi:
            fill_idx, entry_px, fill_kind = i, hi * (1 + slip), "limit"
        elif stop < o[i] < lo and h[i] >= lo and low[i] > stop:
            # opened below the zone (setup weakened) but traded back up into it, without
            # touching the stop: buy-stop at entry_low. If the stop was also touched on
            # this bar the order of events is unknown -> treated as invalidated below.
            fill_idx, entry_px, fill_kind = i, lo * (1 + slip), "back_into_zone"
        if fill_idx is not None:
            events.append(
                {
                    "type": "triggered",
                    "date": d,
                    "fill": fill_kind,
                    "entry_price": _r(entry_px, 2),
                    "price_adjustment_factor": adj_note,
                }
            )
            break
        if o[i] <= stop or low[i] <= stop:
            return [{"type": "invalidated_before_entry", "date": d, "low": _r(low[i], 2), "stop": _r(stop, 2)}]
        if h[i] >= t1:
            return [{"type": "missed_without_entry", "date": d, "high": _r(h[i], 2), "target1": _r(t1, 2)}]
    if fill_idx is None:
        if len(after) >= cfg.entry_valid_sessions:
            d = dates[cfg.entry_valid_sessions - 1].strftime("%Y-%m-%d")
            return [{"type": "expired_not_triggered", "date": d}]
        return []  # still pending, waiting for more bars

    # ---- holding phase -----------------------------------------------------
    e = fill_idx
    last = min(e + cfg.max_hold_sessions, len(after) - 1)
    exit_raw, reason, j_exit = None, None, None
    for j in range(e + cfg.min_hold_sessions, last + 1):
        if o[j] <= stop:
            exit_raw, reason = o[j], "stop"
        elif o[j] >= t1:
            exit_raw, reason = o[j], "target1"
        elif low[j] <= stop:
            exit_raw, reason = stop, "stop"
        elif h[j] >= t1:
            exit_raw, reason = t1, "target1"
        if exit_raw is not None:
            j_exit = j
            break
    if exit_raw is None and e + cfg.max_hold_sessions <= len(after) - 1:
        j_exit, exit_raw, reason = last, c[last], "time"
    if exit_raw is None:
        return events  # trade open; status() reports running MFE/MAE

    exit_px = exit_raw * (1 - slip)
    risk_pct = (entry_px - stop) / entry_px * 100
    net = net_return(entry_px, exit_px, cfg.costs)
    seg_h, seg_l = h[e : j_exit + 1], low[e : j_exit + 1]
    events.append(
        {
            "type": "closed",
            "date": dates[j_exit].strftime("%Y-%m-%d"),
            "exit_reason": reason,
            "exit_price": _r(exit_px, 2),
            "sessions_held": int(j_exit - e),
            "risk_pct": _r(risk_pct),
            "raw_return_pct": _r((exit_raw / (entry_px / (1 + slip)) - 1) * 100),
            "net_return_pct": _r(net),
            "realized_r": _r(net / risk_pct) if risk_pct > 0 else None,
            "mfe_pct": _r((seg_h.max() / entry_px - 1) * 100),
            "mae_pct": _r((seg_l.min() / entry_px - 1) * 100),
            "mfe_r": _r((seg_h.max() - entry_px) / (entry_px - stop)),
            "mae_r": _r((seg_l.min() - entry_px) / (entry_px - stop)),
            "price_adjustment_factor": adj_note,
        }
    )
    return events


def _strip(ev: dict) -> dict:
    return {k: v for k, v in ev.items() if not k.startswith("_") and k not in ("rec_id", "recorded_at_utc", "run_id")}


@dataclass
class RecState:
    """Replayed state of one recommendation."""

    rec_id: str
    created: dict
    events: list[dict] = field(default_factory=list)

    @property
    def plan_event(self) -> dict:
        """The created event with the latest plan revision applied (before trigger)."""
        rev = [e for e in self.events if e["type"] == "plan_revised"]
        return {**self.created, "plan": rev[-1]["new_plan"]} if rev else self.created

    @property
    def outcome_events(self) -> list[dict]:
        corr = [e for e in self.events if e["type"] == "correction"]
        if corr:
            return corr[-1]["recomputed_events"]
        return [e for e in self.events if e["type"] not in ("plan_revised", "withdrawn", "correction")]

    @property
    def status(self) -> str:
        if any(e["type"] == "withdrawn" for e in self.events):
            return "withdrawn"
        ev = self.outcome_events
        if not ev:
            return "pending"
        t = ev[-1]["type"]
        return "open" if t == "triggered" else t

    @property
    def active(self) -> bool:
        return self.status in ("pending", "open")

    @property
    def triggered(self) -> bool:
        return any(e["type"] == "triggered" for e in self.outcome_events)


def replay(rows: list[dict]) -> dict[str, RecState]:
    """Rebuild every recommendation's state from the event log."""
    out: dict[str, RecState] = {}
    for r in rows:
        if r["type"] == "created":
            out[r["rec_id"]] = RecState(r["rec_id"], _strip(r))
        elif r["rec_id"] in out:
            out[r["rec_id"]].events.append(_strip(r))
    return out


def new_outcome_events(state: RecState, computed: list[dict]) -> list[dict]:
    """Events to append so the log matches ``computed`` without editing history."""
    stored = state.outcome_events
    if computed[: len(stored)] == stored:
        return computed[len(stored) :]
    return [{"type": "correction", "reason": "source data for past bars changed", "recomputed_events": computed}]


def created_event(analysis_record: dict, run_id: str) -> dict:
    c = analysis_record["content"]
    p = c["plan"]
    rec_id = f"{c['symbol']}-{c['trading_date']}-{c['strategy_version']}"
    return {
        "rec_id": rec_id,
        "type": "created",
        "kind": "system_recommendation_hypothetical",  # never a user trade
        "symbol": c["symbol"],
        "trading_date": c["trading_date"],
        "strategy_version": c["strategy_version"],
        "execution_model": EXECUTION_MODEL_VERSION,
        "analysis_record_id": analysis_record["record_id"],
        "plan": {k: p[k] for k in ("plan_type", "entry_low", "entry_high", "stop", "target1", "target2", "rr1", "rr2")},
        "target_is_projection": p["target_is_projection"],
        "score": c["score"]["value"],
        "classification": c["classification"],
        "freshness": analysis_record["freshness"],
        "run_id": run_id,
    }


def summarize_ledger(states: dict[str, RecState], mode: str = "live", strategy_version: str | None = None) -> dict:
    """Paper-trading performance (separate from backtest and from user trades).

    Only recommendations of ``mode`` are counted; events written before the ``mode``
    field existed are treated as live (they were produced by the live workflow).
    """
    states = {k: v for k, v in states.items() if v.created.get("mode", "live") == mode}
    if strategy_version is not None:  # v1.0 and v2.0 paper-tracking are never mixed
        states = {k: v for k, v in states.items() if v.created.get("strategy_version") == strategy_version}
    closed = [s for s in states.values() if s.status == "closed"]
    rs = [s.outcome_events[-1]["realized_r"] for s in closed if s.outcome_events[-1].get("realized_r") is not None]
    wins = [r for r in rs if r > 0]
    by_status: dict[str, int] = {}
    for s in states.values():
        by_status[s.status] = by_status.get(s.status, 0) + 1
    return {
        "label": f"paper-trading [{mode}] [{strategy_version or 'all versions'}] (system recommendations, hypothetical fills)",
        "strategy_version": strategy_version,
        "recommendations": len(states),
        "triggered": sum(s.triggered for s in states.values()),
        "by_status": by_status,
        "closed_trades": len(rs),
        "win_rate_pct": round(100 * len(wins) / len(rs), 1) if rs else None,
        "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
    }


def as_dict(cfg: ExecConfig) -> dict:
    return asdict(cfg)
