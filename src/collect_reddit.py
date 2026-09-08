"""해외 수집 — Reddit `top?t=week` (SPEC 6절 "해외").

    GET https://www.reddit.com/r/<sub>/top.json?t=week&limit=100&raw_json=1

`t=week` 의 창은 호출 시각 기준 최근 7일이라 이 프로젝트의 월~일 창과 어긋난다.
그래서 `created_utc` 를 KST 로 바꿔 **수집 창으로 다시 필터한다 — 생략 불가.**
`raw_json=1` 은 title/selftext 의 HTML 엔티티 이스케이프를 끈다.

순수: parse_listing · 네트워크: fetch_subreddit / collect_reddit (get_json 주입 가능)
"""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from src.http import get_json
from src.publishers import publisher_name
from src.schema import KST, Origin, RawArticle, RawMetrics, SourceKind, WeekMeta, ensure_kst, now_kst
from src.urls import anchor_url, normalize_for_compare

REDDIT_TOP_URL = "https://www.reddit.com/r/{sub}/top.json"
DEFAULT_SUBREDDITS: tuple[str, ...] = ("robotics", "MachineLearning")   # SPEC 6절
LIMIT = 100

GetJson = Callable[..., Any]


def parse_post(data: dict[str, Any], collected_at: datetime) -> RawArticle:
    url = data["url"]
    anchor = anchor_url(url)
    subreddit = data["subreddit"]
    is_self = bool(data.get("is_self"))
    return RawArticle(
        article_id=f"reddit:{data['id']}",
        origin=Origin.OVERSEAS,
        source=SourceKind.REDDIT,
        title=html.unescape(data["title"]).strip(),
        url=url,
        publisher=publisher_name(anchor, subreddit=subreddit, is_self=is_self),
        published_at=datetime.fromtimestamp(float(data["created_utc"]), tz=timezone.utc).astimezone(KST),
        collected_at=ensure_kst(collected_at),
        metrics=RawMetrics(comments=data.get("num_comments"), upvotes=data.get("ups")),
        description=html.unescape(data.get("selftext") or "").strip(),   # 링크 글은 ""
        query=f"r/{subreddit}",
        extra={
            "subreddit": subreddit,
            "is_self": is_self,
            "upvote_ratio": data.get("upvote_ratio"),
            "domain": data.get("domain"),
            "normalized_url": normalize_for_compare(url),
            "anchor_url": anchor,
        },
    )


def parse_listing(payload: dict[str, Any], collected_at: datetime) -> list[RawArticle]:
    children = payload.get("data", {}).get("children", [])
    return [parse_post(c["data"], collected_at) for c in children if c.get("kind") == "t3" and not c["data"].get("stickied")]


def fetch_subreddit(sub: str, week: WeekMeta, *, get_json: GetJson = get_json,
                    collected_at: datetime | None = None) -> list[RawArticle]:
    payload = get_json(REDDIT_TOP_URL.format(sub=sub), {"t": "week", "limit": str(LIMIT), "raw_json": "1"})
    stamp = collected_at or now_kst()
    return [a for a in parse_listing(payload, stamp) if week.contains(a.published_at)]   # 창 재필터 — 필수


def collect_reddit(week: WeekMeta, *, subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
                   get_json: GetJson = get_json, collected_at: datetime | None = None) -> list[RawArticle]:
    stamp = collected_at or now_kst()
    return [a for sub in subreddits for a in fetch_subreddit(sub, week, get_json=get_json, collected_at=stamp)]
