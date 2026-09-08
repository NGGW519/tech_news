"""src/week.py — SPEC 5절 목요일 앵커 규칙. fixture `week_meta.json` 4케이스 + 경계."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.schema import KST, WeekMeta
from src.week import compute_week, current_week

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "week_meta.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["case"] for c in CASES])
def test_fixture_cases(case):
    expected = WeekMeta.from_dict(case["week"])
    got = compute_week(date.fromisoformat(case["week"]["run_date"]))
    assert got == expected
    # 파생 문자열까지 fixture 의 expected 와 대조
    exp = case["expected"]
    assert got.month_page_title == exp["month_page_title"]
    assert got.week_key == exp["week_key"]
    assert got.week_label == exp["week_label"]
    assert got.window_start_dt.isoformat() == exp["window_start_dt"]
    assert got.window_end_dt.isoformat() == exp["window_end_dt"]


def test_window_is_exactly_seven_days_ending_the_day_before_run():
    w = compute_week(date(2026, 8, 17))
    assert (w.window_end - w.window_start).days == 6
    assert w.window_end == w.run_date - timedelta(days=1)
    assert w.window_start.weekday() == 0 and w.window_end.weekday() == 6


@pytest.mark.parametrize("offset", range(1, 7))  # 화 ~ 일
def test_non_monday_run_snaps_to_that_weeks_monday(offset):
    monday = date(2026, 8, 17)
    assert compute_week(monday + timedelta(days=offset)) == compute_week(monday)


def test_current_week_uses_kst_calendar_not_utc():
    # SPEC 2절 cron: UTC 일요일 23:10 = KST 월요일 08:10. UTC 날짜로 계산하면 한 주가 어긋난다.
    utc_sunday_night = datetime(2026, 8, 16, 23, 10, tzinfo=timezone.utc)
    assert current_week(utc_sunday_night) == compute_week(date(2026, 8, 17))
    assert current_week(utc_sunday_night).week_key == "8월 2주"


def test_current_week_rejects_naive_datetime():
    with pytest.raises(ValueError):
        current_week(datetime(2026, 8, 17, 8, 30))


def test_contains_boundaries():
    w = compute_week(date(2026, 8, 17))
    assert w.contains(datetime(2026, 8, 10, 0, 0, tzinfo=KST))
    assert w.contains(datetime(2026, 8, 16, 23, 59, 59, tzinfo=KST))
    assert not w.contains(datetime(2026, 8, 9, 23, 59, 59, tzinfo=KST))
    assert not w.contains(datetime(2026, 8, 17, 0, 0, tzinfo=KST))
    # UTC 로 넘겨도 KST 로 환산해 판정한다: UTC 08/16 15:30 = KST 08/17 00:30 → 창 밖
    assert not w.contains(datetime(2026, 8, 16, 15, 30, tzinfo=timezone.utc))
