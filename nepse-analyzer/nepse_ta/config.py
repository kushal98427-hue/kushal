"""Central, documented configuration. Every threshold used in analysis lives here."""

from __future__ import annotations

from dataclasses import dataclass, field

SOURCE_REPO = "Aabishkar2/nepse-data"
SOURCE_BRANCH = "main"
SOURCE_CSV_DIR = "data/company-wise"
EXPECTED_COLUMNS: tuple[str, ...] = (
    "published_date",
    "open",
    "high",
    "low",
    "close",
    "per_change",
    "traded_quantity",
    "traded_amount",
    "status",
)
NEPAL_TZ = "Asia/Kathmandu"
#: Version of the analysis/trading rules. Bump whenever a rule that can change a
#: plan, score or recommendation changes; every stored record carries it.
STRATEGY_VERSION = "v1.0"
#: Version of the paper-trading execution model used for recommendation outcomes.
EXECUTION_MODEL_VERSION = "exec-1"
SEOUL_TZ = "Asia/Seoul"


@dataclass(frozen=True)
class DataConfig:
    """Data validation and freshness rules."""

    #: NEPSE daily circuit breaker is +/-10%; anything beyond this between two
    #: consecutive rows is a corporate action (bonus/right) or a data error.
    circuit_limit_pct: float = 10.5
    #: Minimum discrepancy (percentage points) between the raw close-to-close move
    #: and the source's ``per_change`` before we treat a row as an adjustment event.
    adjustment_discrepancy_pp: float = 2.0
    #: Plausible price-adjustment factor range for bonus/right events.
    adjustment_factor_min: float = 0.30
    adjustment_factor_max: float = 0.985
    #: Max calendar days between two rows for ``per_change`` to be trusted as
    #: referring to the previous row (14 covers Dashain/Tihar market closures).
    adjustment_max_gap_days: int = 14
    #: Sessions needed before any analysis is produced.
    min_history: int = 60
    #: Market-level freshness (see nepse_ta/freshness.py). Data missing >= this many
    #: expected trading sessions, or older than ``market_stale_block_days`` calendar
    #: days, blocks the setup list. 1-3 missing sessions = "stale" (shown, clearly marked).
    stale_block_sessions: int = 4
    market_stale_block_days: int = 10
    #: A stock whose last row is this many market sessions behind the market's
    #: latest session is "stale" and excluded from setup ranking.
    stock_stale_sessions: int = 3
    #: Fraction of missing volume in the last 60 sessions above which volume
    #: analysis is disabled for the stock.
    max_missing_volume_frac: float = 0.2
    #: Median daily turnover (NPR) over 20 sessions below which a liquidity warning is raised.
    min_median_turnover_npr: float = 2_000_000.0


@dataclass(frozen=True)
class AnalysisConfig:
    """Indicator, level and setup parameters."""

    ma_periods: tuple[int, ...] = (20, 50, 100, 200)
    rsi_period: int = 14
    atr_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    volume_avg_period: int = 20
    breakout_lookback: int = 20
    pivot_window: int = 5
    level_lookback: int = 250
    #: Pivots closer than this many ATRs are merged into one zone.
    zone_merge_atr: float = 0.6
    consolidation_range_atr: float = 4.0
    breakout_volume_mult: float = 1.5
    #: Do not chase: breakout entry zone extends this many ATR above the level.
    entry_zone_atr: float = 0.5
    stop_atr_min: float = 1.0
    stop_atr_max: float = 2.0
    min_rr_for_valid_setup: float = 1.5
    min_score_for_master: int = 60


@dataclass(frozen=True)
class CostConfig:
    """NEPSE trading costs. VERIFY CURRENT RATES with SEBON/your broker before relying on them.

    Defaults: broker commission ~0.36% (smallest slab, conservative), SEBON fee
    0.015%, DP charge NPR 25 per sell, capital-gains tax 7.5% (individual,
    holding < 365 days). Slippage models NEPSE's thin order books.
    """

    commission_pct: float = 0.36
    sebon_fee_pct: float = 0.015
    dp_charge_npr: float = 25.0
    cgt_pct: float = 7.5
    slippage_pct: float = 0.25
    notional_npr: float = 100_000.0  # used to convert the fixed DP charge into %

    @property
    def per_side_pct(self) -> float:
        """Percentage cost per side excluding tax."""
        return self.commission_pct + self.sebon_fee_pct + self.slippage_pct


@dataclass(frozen=True)
class BacktestConfig:
    """Trade-simulation rules."""

    start_date: str = "2019-01-01"
    #: NEPSE settles T+2: shares bought cannot be sold for this many sessions.
    min_hold_sessions: int = 3
    max_hold_sessions: int = 20
    #: Skip the signal if the stock's next bar is more than this many calendar days later
    #: (illiquid stock did not trade; entering weeks later would be a stale signal).
    max_entry_delay_days: int = 5
    #: Model NEPSE +/-10% circuit locks: a bar traded at a single price at the limit
    #: cannot be bought (upper) or sold (lower) that day.
    model_circuit_locks: bool = True
    circuit_lock_pct: float = 9.5
    #: Skip entry if next open is above entry-zone high by more than this fraction.
    max_entry_gap_pct: float = 1.0
    #: Walk-forward: first out-of-sample year (train = all prior years, expanding).
    first_test_year: int = 2022
    min_bucket_trades: int = 50
    max_calibration_error_pp: float = 10.0
    min_total_oos_trades: int = 300


@dataclass(frozen=True)
class Settings:
    """All settings bundled."""

    data: DataConfig = field(default_factory=DataConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)


DEFAULT_SETTINGS = Settings()
