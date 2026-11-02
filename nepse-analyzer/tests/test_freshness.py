import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd

from nepse_ta.freshness import assess, count_sessions_between, expected_latest_session, infer_trading_weekdays

NPT = ZoneInfo("Asia/Kathmandu")
MON_FRI = (0, 1, 2, 3, 4)


def test_infer_weekdays_from_recent_sessions():
    sun_thu = pd.bdate_range("2025-01-05", periods=60, freq="C", weekmask="Sun Mon Tue Wed Thu")
    assert infer_trading_weekdays(list(sun_thu)) == (0, 1, 2, 3, 6)
    mon_fri = pd.bdate_range("2026-09-01", periods=60)
    assert infer_trading_weekdays(list(mon_fri)) == MON_FRI


def test_expected_session_respects_close_time_and_weekend():
    mon_before_close = dt.datetime(2026, 11, 2, 14, 0, tzinfo=NPT)
    assert expected_latest_session(mon_before_close, MON_FRI) == dt.date(2026, 10, 30)  # previous Friday
    mon_after_close = dt.datetime(2026, 11, 2, 17, 45, tzinfo=NPT)  # = 21:00 KST
    assert expected_latest_session(mon_after_close, MON_FRI) == dt.date(2026, 11, 2)
    saturday = dt.datetime(2026, 10, 31, 20, 0, tzinfo=NPT)
    assert expected_latest_session(saturday, MON_FRI) == dt.date(2026, 10, 30)


def test_assess_statuses():
    sessions = list(pd.bdate_range("2026-08-01", "2026-10-30"))
    md = dt.date(2026, 10, 30)
    sat = assess(md, sessions, dt.datetime(2026, 10, 31, 21, 0, tzinfo=NPT))
    assert sat.status == "current"
    mon = assess(md, sessions, dt.datetime(2026, 11, 2, 17, 45, tzinfo=NPT))
    assert mon.status == "stale" and mon.sessions_missing == 1
    thu = assess(md, sessions, dt.datetime(2026, 11, 5, 17, 45, tzinfo=NPT))
    assert thu.status == "blocked" and thu.sessions_missing == 4


def test_count_sessions_between():
    assert count_sessions_between(dt.date(2026, 10, 30), dt.date(2026, 11, 2), MON_FRI) == 1
