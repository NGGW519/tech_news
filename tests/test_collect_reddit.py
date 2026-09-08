"""src/collect_reddit.py — 리스팅 파싱(순수) → raw_articles_overseas.json 의 Reddit 5건 재현 + 창 재필터 + OAuth."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

import pytest

from src.collect_reddit import collect_reddit, fetch_subreddit, get_app_token, parse_listing
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

    def fake(url, params, headers=None):
        calls.append((url, dict(params), headers))
        return {"kind": "Listing", "data": {"children": [
            _post("a", inside), _post("b", too_new), _post("c", too_old), _post("d", inside, stickied=True),
        ]}}

    got = fetch_subreddit("robotics", WEEK, get_json=fake, collected_at=COLLECTED)
    assert [a.article_id for a in got] == ["reddit:a"]
    url, params, headers = calls[0]
    assert url == "https://www.reddit.com/r/robotics/top.json" and headers is None
    assert params == {"t": "week", "limit": "100", "raw_json": "1"}


def test_oauth_path_uses_app_token_and_oauth_host():
    seen = []

    def fake_post(url, form, headers=None):
        seen.append(("POST", url, dict(form), dict(headers)))
        return {"access_token": "app-token", "token_type": "bearer"}

    def fake_get(url, params, headers=None):
        seen.append(("GET", url, dict(params), headers))
        return {"data": {"children": []}}

    assert collect_reddit(WEEK, get_json=fake_get, post_form=fake_post, collected_at=COLLECTED,
                          client_id="cid", client_secret="sec") == []
    post = seen[0]
    assert post[1] == "https://www.reddit.com/api/v1/access_token" and post[2] == {"grant_type": "client_credentials"}
    assert post[3]["Authorization"] == "Basic " + base64.b64encode(b"cid:sec").decode()
    gets = [s for s in seen if s[0] == "GET"]
    assert [g[1] for g in gets] == ["https://oauth.reddit.com/r/robotics/top", "https://oauth.reddit.com/r/MachineLearning/top"]
    assert all(g[3] == {"Authorization": "Bearer app-token"} for g in gets)


def test_app_token_failure_raises():
    with pytest.raises(RuntimeError, match="app token"):
        get_app_token("c", "s", post_form=lambda u, f, h=None: {"error": "invalid_grant"})


def test_without_credentials_skips_cleanly_without_any_call(caplog):
    def must_not_call(*a, **k):
        raise AssertionError("자격 증명 없으면 호출하면 안 된다")

    assert collect_reddit(WEEK, get_json=must_not_call, post_form=must_not_call, collected_at=COLLECTED) == []
    assert "건너뛴다" in caplog.text
