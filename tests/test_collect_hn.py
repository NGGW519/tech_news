"""src/collect_hn.py — Algolia 응답 파싱(순수) → raw_articles_overseas.json 의 HN 5건 재현 + 페이지네이션."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.collect_hn import HN_SEARCH_URL, collect_hn, fetch_query, parse_hit, parse_hits
from src.schema import KST
from src.week import compute_week

FIXTURES = Path(__file__).parent / "fixtures"
COLLECTED = datetime(2026, 8, 17, 8, 12, 55, tzinfo=KST)     # raw_articles_overseas.json 이 고정한 값
WEEK = compute_week(datetime(2026, 8, 17).date())


def _payload():
    return json.loads((FIXTURES / "api_hn_algolia.json").read_text(encoding="utf-8"))


def _expected_hn():
    raw = json.loads((FIXTURES / "raw_articles_overseas.json").read_text(encoding="utf-8"))
    return {r["article_id"]: r for r in raw if r["source"] == "hacker_news"}


def test_parse_reproduces_fixture_exactly():
    got = {a.article_id: a.to_dict() for a in parse_hits(_payload(), "hn_front_page", COLLECTED)}
    expected = _expected_hn()
    assert set(got) == set(expected) and len(got) == 5
    for article_id, exp in expected.items():
        assert got[article_id] == exp, article_id


def test_link_post_has_empty_description_and_utc_converted_to_kst():
    a = next(x for x in parse_hits(_payload(), "q", COLLECTED) if x.article_id == "hn:41253117")
    assert a.description == ""                                              # story_text: null
    assert a.published_at.isoformat() == "2026-08-13T22:40:00+09:00"        # 13:40Z → KST
    assert a.metrics.points == 664 and a.metrics.comments == 512 and a.metrics.upvotes is None


def test_ask_hn_without_url_falls_back_to_item_url_and_story_text():
    hit = {"objectID": "1", "title": "Ask HN: x?", "url": None, "story_text": "<p>Body &amp; more</p>",
           "author": "u", "points": 3, "num_comments": 1, "created_at_i": 1786458151}
    a = parse_hit(hit, "q", COLLECTED)
    assert a.url == "https://news.ycombinator.com/item?id=1"
    assert a.description == "Body & more"
    assert a.publisher == "Hacker News"                                    # 표: ycombinator.com
    assert a.extra["anchor_url"] == a.url


class FakeAlgolia:
    def __init__(self, pages: list[list[dict]]):
        self.pages, self.calls = pages, []

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        page = int(params["page"])
        return {"hits": self.pages[page], "nbPages": len(self.pages), "page": page}


def _hit(i: int, epoch: int, title: str | None = None) -> dict:
    return {"objectID": str(i), "title": title or f"Robot story {i}", "url": f"https://a.com/{i}", "story_text": None,
            "author": "u", "points": 1, "num_comments": 0, "created_at_i": epoch}


def test_title_keyword_filter_drops_fuzzy_matches():
    # 실측: Algolia 가 "robot" 검색에 "root", "humanoid" 검색에 "Humanitas" 를 돌려준다
    inside = int(datetime(2026, 8, 12, 12, 0, tzinfo=KST).timestamp())
    fake = FakeAlgolia([[
        _hit(1, inside, "Omarchy: Any User Process Can Escalate to Root"),
        _hit(2, inside, "Thoughts on Pope Leo XIV's Magnifica Humanitas"),
        _hit(3, inside, "Launch HN: Nori Robotics – a low-cost humanoid"),
        _hit(4, inside, "Waymo expands self-driving to freeways"),
        _hit(5, inside, "Physical AI needs better simulators"),
    ]])
    got = fetch_query("robot", WEEK, get_json=fake, collected_at=COLLECTED)
    assert [a.article_id for a in got] == ["hn:3", "hn:4", "hn:5"]
    assert fake.calls[0][1]["restrictSearchableAttributes"] == "title"


def test_fetch_paginates_all_pages_and_refilters_window():
    inside = int(datetime(2026, 8, 12, 12, 0, tzinfo=KST).timestamp())
    outside = int(datetime(2026, 8, 17, 9, 0, tzinfo=KST).timestamp())
    fake = FakeAlgolia([[_hit(1, inside), _hit(2, outside)], [_hit(3, inside)]])
    got = fetch_query("robot", WEEK, get_json=fake, collected_at=COLLECTED)
    assert [a.article_id for a in got] == ["hn:1", "hn:3"]
    assert [p["page"] for _, p in fake.calls] == ["0", "1"]
    url, params = fake.calls[0]
    assert url == HN_SEARCH_URL
    assert params["tags"] == "story" and params["query"] == "robot" and params["hitsPerPage"] == "100"
    start = int(WEEK.window_start_dt.timestamp()); end = int(WEEK.window_end_dt.timestamp())
    assert params["numericFilters"] == f"created_at_i>{start},created_at_i<{end}"


def test_collect_dedupes_across_queries_keeping_first_query():
    inside = int(datetime(2026, 8, 12, 12, 0, tzinfo=KST).timestamp())
    fake = FakeAlgolia([[_hit(1, inside)]])
    got = collect_hn(WEEK, queries=("robot", "humanoid"), get_json=fake, collected_at=COLLECTED)
    assert len(got) == 1 and got[0].query == "robot"
    assert [p["query"] for _, p in fake.calls] == ["robot", "humanoid"]
