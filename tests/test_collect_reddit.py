"""src/collect_reddit.py — 리스팅 파싱(순수) → raw_articles_overseas.json 의 Reddit 5건 재현 + 창 재필터."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.collect_reddit import collect_reddit, fetch_subreddit, parse_listing
from src.schema import KST
from src.week import compute_week

FIXTURES = Path(__file__).parent / "fixtures"
COLLECTED = datetime(2026, 8, 17, 8, 12, 55, tzinfo=KST)
WEEK = compute_week(datetime(2026, 8, 17).date())


def _payload():
    return json.loads((FIXTURES / "api_reddit_top_week.json").read_text(encoding="utf-8"))


def test_parse_reproduces_fixture_exactly():
    raw = json.loads((FIXTURES / "raw_articles_overseas.json").read_text(encoding="utf-8"))
    expected = {r["article_id"]: r for r in raw if r["source"] == "reddit"}
    got = {a.article_id: a.to_dict() for a in parse_listing(_payload(), COLLECTED)}
    assert set(got) == set(expected) and len(got) == 5
    for article_id, exp in expected.items():
        assert got[article_id] == exp, article_id


def test_self_post_vs_link_post():
    by_id = {a.article_id: a for a in parse_listing(_payload(), COLLECTED)}
    self_post, link_post = by_id["reddit:1mq0a4b"], by_id["reddit:1mqk4pz"]
    assert self_post.publisher == "Reddit r/robotics" and self_post.extra["is_self"] is True
    assert len(self_post.description) == 213                                # selftext 가 description
    assert link_post.publisher == "Physical Intelligence" and link_post.description == ""
    assert link_post.extra["anchor_url"] == "https://www.physicalintelligence.company/blog/pi06-open-weights"
    assert link_post.url.endswith("utm_source=reddit&utm_medium=social")   # 수집 원본은 그대로


def _post(id_: str, epoch: float, **over) -> dict:
    data = {"id": id_, "subreddit": "robotics", "title": "t", "selftext": "", "url": f"https://a.com/{id_}",
            "ups": 1, "num_comments": 0, "created_utc": epoch, "is_self": False, "domain": "a.com", "upvote_ratio": 1.0}
    data.update(over)
    return {"kind": "t3", "data": data}


def test_fetch_refilters_to_window_and_drops_stickied():
    inside = datetime(2026, 8, 12, 12, 0, tzinfo=KST).timestamp()
    too_new = datetime(2026, 8, 17, 6, 0, tzinfo=KST).timestamp()    # t=week 가 실행 당일 새벽을 섞어 줌
    too_old = datetime(2026, 8, 9, 20, 0, tzinfo=KST).timestamp()
    calls = []

    def fake(url, params):
        calls.append((url, dict(params)))
        return {"kind": "Listing", "data": {"children": [
            _post("a", inside), _post("b", too_new), _post("c", too_old), _post("d", inside, stickied=True),
        ]}}

    got = fetch_subreddit("robotics", WEEK, get_json=fake, collected_at=COLLECTED)
    assert [a.article_id for a in got] == ["reddit:a"]
    url, params = calls[0]
    assert url == "https://www.reddit.com/r/robotics/top.json"
    assert params == {"t": "week", "limit": "100", "raw_json": "1"}


def test_collect_iterates_subreddits():
    seen = []

    def fake(url, params):
        seen.append(url)
        return {"data": {"children": []}}

    assert collect_reddit(WEEK, get_json=fake, collected_at=COLLECTED) == []
    assert seen == ["https://www.reddit.com/r/robotics/top.json", "https://www.reddit.com/r/MachineLearning/top.json"]
