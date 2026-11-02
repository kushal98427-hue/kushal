from nepse_ta.scoring import SCORING_RULES, ScoreInputs, compute_score, score_bucket


def base(**kw) -> ScoreInputs:
    d = dict(
        daily_trend="sideways",
        sma50_rising=None,
        weekly_trend="sideways",
        rsi=None,
        macd_above_signal=None,
        macd_hist_rising=None,
        setup_type="none",
        breakout_volume_confirmed=None,
        bullish_pattern=False,
        up_day=False,
        rel_volume=None,
        volume_reliable=True,
        rr1=None,
    )
    d.update(kw)
    return ScoreInputs(**d)


def test_empty_inputs_score_zero():
    r = compute_score(base())
    assert r.total == 0 and r.breakdown == [] and r.band == "none"


def test_full_breakout_is_clamped_to_100():
    r = compute_score(
        base(
            daily_trend="uptrend",
            sma50_rising=True,
            weekly_trend="uptrend",
            rsi=60,
            macd_above_signal=True,
            macd_hist_rising=True,
            setup_type="breakout",
            breakout_volume_confirmed=True,
            bullish_pattern=True,
            up_day=True,
            rel_volume=2.0,
            rr1=3.5,
        )
    )
    assert r.total == 100
    assert sum(p for _, p in r.breakdown) == 105  # transparent: raw sum is shown


def test_breakdown_points_match_rule_table():
    table = {r[0]: r[1] for r in SCORING_RULES}
    r = compute_score(base(daily_trend="uptrend", rsi=45, setup_type="pullback", rr1=2.1))
    assert dict(r.breakdown) == {k: table[k] for k in ("daily_uptrend", "rsi_neutral", "pullback_in_uptrend", "rr_2")}
    assert r.total == 10 + 5 + 20 + 15


def test_only_highest_rr_tier_counts():
    r = compute_score(base(rr1=3.0))
    assert [k for k, _ in r.breakdown] == ["rr_3"]


def test_volume_ignored_when_unreliable():
    r = compute_score(base(up_day=True, rel_volume=3.0, volume_reliable=False))
    assert r.total == 0


def test_penalties_never_go_below_zero():
    r = compute_score(base(rsi=85, low_liquidity=True, short_history=True, recent_repairs=10, recent_break=True))
    assert r.total == 0
    assert {"pen_overbought", "pen_low_liquidity", "pen_short_history", "pen_data_repairs", "pen_recent_break"} == {
        k for k, _ in r.breakdown
    }


def test_buckets():
    assert [score_bucket(s) for s in (0, 39, 40, 55, 60, 69, 70, 100)] == [
        "0-39", "0-39", "40-49", "50-59", "60-69", "60-69", "70-100", "70-100"
    ]
