"""해외 수집 — Reddit `top?t=week` (SPEC 6절 "해외").

    인증   OAuth2 client_credentials (Reddit "script" 앱의 client id/secret)
           POST https://www.reddit.com/api/v1/access_token  →  GET https://oauth.reddit.com/r/<sub>/top
           비인증 `www.reddit.com/r/<sub>/top.json` 은 데이터센터 IP(Actions 포함)에서 403 이다 (실측 2026-09-08).
           자격 증명이 없으면 비인증 경로를 시도하되 경고를 남긴다 (집 IP 에서는 통한다).
    창     `t=week` 는 호출 시각 기준 최근 7일이라 월~일 창과 어긋난다 → created_utc 로 **재필터, 생략 불가**
    기타   raw_json=1 로 title/selftext 의 HTML 엔티티 이스케이프를 끈다

순수: parse_listing · 네트워크: get_app_token / fetch_subreddit / collect_reddit (get_json·post_form 주입 가능)
"""

from __future__ import annotations

import base64
import html
import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from src import http
from src.publishers import publisher_name
from src.schema import KST, Origin, RawArticle, RawMetrics, SourceKind, WeekMeta, ensure_kst, now_kst
from src.urls import anchor_url, normalize_for_compare

log = logging.getLogger(__name__)

REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_OAUTH_TOP_URL = "https://oauth.reddit.com/r/{sub}/top"
REDDIT_PUBLIC_TOP_URL = "https://www.reddit.com/r/{sub}/top.json"
DEFAULT_SUBREDDITS: tuple[str, ...] = ("robotics", "MachineLearning")   # SPEC 6절
LIMIT = 100

GetJson = Callable[..., Any]
PostForm = Callable[..., Any]


# ─────────────────────────────────────────────────────────────────────────────
# 순수 로직
# ─────────────────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────────────────
# 네트워크 호출부
# ─────────────────────────────────────────────────────────────────────────────


def get_app_token(client_id: str, client_secret: str, *, post_form: PostForm = http.post_form) -> str:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    payload = post_form(REDDIT_TOKEN_URL, {"grant_type": "client_credentials"}, {"Authorization": f"Basic {basic}"})
    if "access_token" not in payload:
        raise RuntimeError(f"reddit app token failed: {payload}")
    return payload["access_token"]


def fetch_subreddit(sub: str, week: WeekMeta, *, get_json: GetJson = http.get_json,
                    collected_at: datetime | None = None, access_token: str | None = None) -> list[RawArticle]:
    params = {"t": "week", "limit": str(LIMIT), "raw_json": "1"}
    if access_token:
        payload = get_json(REDDIT_OAUTH_TOP_URL.format(sub=sub), params, {"Authorization": f"Bearer {access_token}"})
    else:
        payload = get_json(REDDIT_PUBLIC_TOP_URL.format(sub=sub), params)
    stamp = collected_at or now_kst()
    return [a for a in parse_listing(payload, stamp) if week.contains(a.published_at)]   # 창 재필터 — 필수


def collect_reddit(week: WeekMeta, *, subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
                   get_json: GetJson = http.get_json, post_form: PostForm = http.post_form,
                   collected_at: datetime | None = None,
                   client_id: str | None = None, client_secret: str | None = None) -> list[RawArticle]:
    stamp = collected_at or now_kst()
    token = None
    if client_id and client_secret:
        token = get_app_token(client_id, client_secret, post_form=post_form)
    else:
        log.warning("Reddit 자격 증명(REDDIT_CLIENT_ID/SECRET) 없음 — 비인증 JSON 을 시도한다. 데이터센터 IP 에서는 403 이 난다")
    return [a for sub in subreddits
            for a in fetch_subreddit(sub, week, get_json=get_json, collected_at=stamp, access_token=token)]
