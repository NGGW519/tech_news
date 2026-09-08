"""src/collect_naver.py — 네이버 응답 파싱(순수) + 페이지네이션(가짜 http_get)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.collect_naver import (
    DISPLAY,
    MAX_START,
    NAVER_NEWS_URL,
    article_id_for,
    clean_text,
    collect_domestic,
    fetch_query,
    merge_across_queries,
    parse_response,
)
from src.schema import KST, RawArticle
from src.week import compute_week

FIXTURES = Path(__file__).parent / "fixtures"

# fixture README: 키워드는 파일명으로만 구분. collected_at 은 raw_articles_domestic.json 이 고정한 값
API_FILES = [
    ("휴머노이드", "api_naver_news_humanoid.json", datetime(2026, 8, 17, 8, 12, 41, tzinfo=KST)),
    ("자율주행", "api_naver_news_autonomous_driving.json", datetime(2026, 8, 17, 8, 12, 42, tzinfo=KST)),
    ("로봇", "api_naver_news_robot.json", datetime(2026, 8, 17, 8, 12, 43, tzinfo=KST)),
    ("ROS", "api_naver_news_ros.json", datetime(2026, 8, 17, 8, 12, 44, tzinfo=KST)),
]


def _payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def parse_fixture_pool() -> list[RawArticle]:
    """네 키워드 파일을 SPEC 키워드 순서로 파싱·병합한 국내 수집 풀 (고유 12건)."""
    return merge_across_queries(
        a for query, name, stamp in API_FILES for a in parse_response(_payload(name), query, stamp)
    )


# ─────────────────────────────────────────────────────────────────────────────
# 순수 로직
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("삼성, <b>휴머노이드</b>용 AP 양산", "삼성, 휴머노이드용 AP 양산"),
        ("LG전자, 가정용 서비스<b>로봇</b> &apos;Q9&apos; 4분기 출시", "LG전자, 가정용 서비스로봇 'Q9' 4분기 출시"),
        ("확대…&quot;야간 무인화가 목표&quot;", "확대…\"야간 무인화가 목표\""),
        ("  [단독] 제목  ", "[단독] 제목"),           # 접두사는 유지, 공백만 정리
        ("&lt;b&gt;진짜 꺾쇠&lt;/b&gt;", "<b>진짜 꺾쇠</b>"),  # 태그 제거 후 엔티티 해제 — 문자 그대로의 꺾쇠는 살아남는다
    ],
)
def test_clean_text(raw, expected):
    assert clean_text(raw) == expected


def test_article_id_convention():
    assert article_id_for("https://www.etnews.com/20260813000123") == "naver:fc1fc8735424"


def test_fixture_pool_size_and_dedup():
    pool = parse_fixture_pool()
    assert len(pool) == 12                                  # 항목 14 / 고유 12 (README)
    by_id = {a.article_id: a for a in pool}
    assert by_id["naver:fc1fc8735424"].extra["matched_queries"] == ["휴머노이드", "로봇"]  # 삼성(전자신문) 두 파일
    assert by_id["naver:655414b46110"].extra["matched_queries"] == ["휴머노이드", "로봇"]  # 아틀라스(연합뉴스) 두 파일
    assert by_id["naver:fc1fc8735424"].query == "휴머노이드"                              # 먼저 본 키워드
    assert by_id["naver:fc1fc8735424"].collected_at.second == 41                         # 먼저 본 호출의 시각


def test_parsed_articles_match_raw_domestic_fixture_exactly():
    """raw_articles_domestic.json 의 대표 3건은 api_naver_news_*.json 에서 그대로 재현돼야 한다."""
    expected = {d["article_id"]: d for d in json.loads((FIXTURES / "raw_articles_domestic.json").read_text(encoding="utf-8"))}
    got = {a.article_id: a.to_dict() for a in parse_fixture_pool()}
    for article_id, exp in expected.items():
        assert got[article_id] == exp, article_id


def test_domestic_articles_have_no_signal_and_no_normalization_keys():
    for a in parse_fixture_pool():
        assert not a.metrics.has_signal
        assert "normalized_url" not in a.extra and "anchor_url" not in a.extra   # 국내는 정규화 산출물이 없다 (SPEC 4절)
        assert set(a.extra) == {"naver_link", "matched_queries", "raw_title"}


# ─────────────────────────────────────────────────────────────────────────────
# 페이지네이션 — 가짜 http_get
# ─────────────────────────────────────────────────────────────────────────────

WEEK = compute_week(datetime(2026, 8, 17).date())   # 창 08/10 ~ 08/16


def _item(i: int, when: datetime) -> dict:
    return {
        "title": f"기사 {i}", "originallink": f"https://www.etnews.com/{i}", "link": f"https://n.news.naver.com/{i}",
        "description": "", "pubDate": when.strftime("%a, %d %b %Y %H:%M:%S +0900"),
    }


class FakeNaver:
    """최신순으로 정렬된 기사 목록을 display/start 로 잘라 주는 가짜 서버. 호출 기록을 남긴다."""

    def __init__(self, stamps: list[datetime]):
        self.items = [_item(i, t) for i, t in enumerate(sorted(stamps, reverse=True))]
        self.calls: list[dict] = []

    def __call__(self, url, params, headers):
        self.calls.append({"url": url, "params": dict(params), "headers": dict(headers)})
        start, display = int(params["start"]), int(params["display"])
        return {"items": self.items[start - 1 : start - 1 + display]}


def test_fetch_stops_at_window_start_and_skips_items_after_window_end():
    after = [datetime(2026, 8, 17, 7, 0, tzinfo=KST)]                              # 창 뒤 (실행일 새벽)
    inside = [datetime(2026, 8, 16, 23, 0, tzinfo=KST) - timedelta(minutes=30 * i) for i in range(150)]  # 창 안 150건 (약 3일치)
    before = [datetime(2026, 8, 9, 23, 59, tzinfo=KST), datetime(2026, 8, 1, tzinfo=KST)]   # 창 앞
    fake = FakeNaver(after + inside + before)

    got = fetch_query("로봇", WEEK, client_id="id", client_secret="secret", http_get=fake,
                      collected_at=datetime(2026, 8, 17, 8, 0, tzinfo=KST))

    assert len(got) == 150                                        # 창 앞·뒤는 빠지고 안쪽만
    assert all(WEEK.contains(a.published_at) for a in got)
    assert [c["params"]["start"] for c in fake.calls] == ["1", "101"]   # 2페이지에서 창 앞 항목을 만나 종료
    assert fake.calls[0]["params"] == {"query": "로봇", "sort": "date", "display": str(DISPLAY), "start": "1"}
    assert fake.calls[0]["url"] == NAVER_NEWS_URL
    assert fake.calls[0]["headers"] == {"X-NCP-APIGW-API-KEY-ID": "id", "X-NCP-APIGW-API-KEY": "secret"}   # API HUB 헤더
    assert NAVER_NEWS_URL == "https://naverapihub.apigw.ntruss.com/search/v1/news"


def test_fetch_stops_on_short_last_page():
    fake = FakeNaver([datetime(2026, 8, 12, tzinfo=KST) + timedelta(minutes=i) for i in range(30)])
    got = fetch_query("로봇", WEEK, client_id="i", client_secret="s", http_get=fake,
                      collected_at=datetime(2026, 8, 17, 8, 0, tzinfo=KST))
    assert len(got) == 30 and len(fake.calls) == 1


def test_fetch_respects_max_start_cap():
    # 창 안 기사만 2000건 — 상한(1000)에 닿으면 멈춘다
    fake = FakeNaver([datetime(2026, 8, 16, tzinfo=KST) - timedelta(minutes=i) for i in range(2000)])
    got = fetch_query("로봇", WEEK, client_id="i", client_secret="s", http_get=fake,
                      collected_at=datetime(2026, 8, 17, 8, 0, tzinfo=KST))
    assert len(got) == MAX_START
    assert fake.calls[-1]["params"]["start"] == str(MAX_START - DISPLAY + 1)


def test_collect_domestic_merges_queries():
    shared = datetime(2026, 8, 12, 10, 0, tzinfo=KST)
    fake = FakeNaver([shared, shared - timedelta(hours=1)])
    got = collect_domestic(WEEK, client_id="i", client_secret="s", queries=("휴머노이드", "로봇"),
                           http_get=fake, collected_at=datetime(2026, 8, 17, 8, 0, tzinfo=KST))
    assert len(got) == 2                                          # 두 키워드가 같은 2건을 돌려줘도 고유 2건
    assert all(a.extra["matched_queries"] == ["휴머노이드", "로봇"] for a in got)
    assert all(a.query == "휴머노이드" for a in got)
    assert [c["params"]["query"] for c in fake.calls] == ["휴머노이드", "로봇"]
