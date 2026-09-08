"""주차 계산 — 목요일 앵커 (SPEC 5절 "주차 귀속 규칙").

순수 로직이다. 네트워크·시계에 직접 닿는 것은 `current_week()` 의 `now` 기본값뿐이며,
그마저 `now_kst()` 를 경유해 KST 로 못박는다 (Actions 런너는 UTC — SPEC 5절).

    run_date     = 실행일 (월요일)
    window_start = run_date - 7일   (직전 월요일)
    window_end   = run_date - 1일   (일요일)
    anchor       = window_start + 3 (그 주 목요일)  → 귀속 연/월, 주차 = (anchor.day - 1) // 7 + 1
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from src.schema import WeekMeta, ensure_kst, now_kst

WINDOW_DAYS = 7          # SPEC 2절: 7일 고정
ANCHOR_OFFSET_DAYS = 3   # 월요일 + 3 = 목요일


def compute_week(run_date: date) -> WeekMeta:
    """실행일 → WeekMeta.

    월요일이 아닌 날짜가 들어오면 **그 주 월요일로 맞춘다.** SPEC 2절의 수집 창은
    "직전 월요일 00:00 ~ 일요일 23:59" 로 정의돼 있고, 실패한 주를 `workflow_dispatch` 로
    화요일에 복구할 때(SPEC 2절) 화~일 창을 만들어 버리면 안 되기 때문이다.
    """
    monday = run_date - timedelta(days=run_date.weekday())
    window_start = monday - timedelta(days=WINDOW_DAYS)
    window_end = monday - timedelta(days=1)
    anchor = window_start + timedelta(days=ANCHOR_OFFSET_DAYS)
    return WeekMeta(
        run_date=monday,
        window_start=window_start,
        window_end=window_end,
        anchor=anchor,
        year=anchor.year,
        month=anchor.month,
        week_no=(anchor.day - 1) // 7 + 1,
    )


def current_week(now: datetime | None = None) -> WeekMeta:
    """지금 기준 WeekMeta. `now` 는 tz-aware 여야 하며 KST 달력 날짜로 환산해 쓴다.

    UTC 일요일 23:10 (= KST 월요일 08:10, SPEC 2절 cron) 에 호출해도 월요일로 계산된다.
    """
    moment = now_kst() if now is None else ensure_kst(now)
    return compute_week(moment.date())
