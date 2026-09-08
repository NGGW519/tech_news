"""해외 수집 — 보조 RSS/Atom (arXiv · DeepMind · NVIDIA) (SPEC 6절 "보조 RSS 피드 목록").

인기도 신호가 없으므로 랭킹에서 빠지고 **예비 풀**로 간다. 단, HN·Reddit 에도 올라온 글은
URL 정규화 매칭으로 병합돼 정상 경쟁한다 — 그래서 normalized_url 을 똑같이 채운다.

`<피드키>` 는 article_id(`rss:<피드키>:<슬러그>`)의 일부라 바꾸지 않는다.
arXiv 두 카테고리는 같은 피드키를 쓰고 논문 ID 가 슬러그라, 교차 등재는 자연히 1건이 된다.

순수: parse_feed · 네트워크: fetch_feed / collect_rss (get_text 주입 가능)
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import partial
from urllib.parse import urlsplit

from src import http
from src.publishers import publisher_name
from src.schema import KST, Origin, RawArticle, RawMetrics, SourceKind, WeekMeta, ensure_kst, now_kst
from src.text import clean_html
from src.urls import anchor_url, normalize_for_compare

log = logging.getLogger(__name__)

ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_DELAY_SECONDS = 3.0        # arXiv API 이용 약관: 요청 간 3초
RATE_LIMIT_RETRY_SECONDS = 15    # 429 뒤 재시도 대기 (1회)
FEED_TIMEOUT = 30                # arXiv export API 는 10초를 넘기기도 한다 (실측 2026-09-08)
_ARXIV_VERSION = re.compile(r"v\d+$")

GetText = Callable[..., str]
get_text: GetText = partial(http.get_text, timeout=FEED_TIMEOUT)


@dataclass(frozen=True)
class Feed:
    key: str                       # <피드키>
    url: str                       # extra.feed_url 에 그대로 남는 값
    params: dict[str, str] = field(default_factory=dict)   # 요청에만 붙는 파라미터


_ARXIV_PARAMS = {"sortBy": "submittedDate", "sortOrder": "descending", "max_results": "100"}   # 200 은 응답이 느려 타임아웃이 잦다

DEFAULT_FEEDS: tuple[Feed, ...] = (
    Feed("arxiv", "http://export.arxiv.org/api/query?search_query=cat:cs.RO", _ARXIV_PARAMS),
    Feed("arxiv", "http://export.arxiv.org/api/query?search_query=cat:cs.AI", _ARXIV_PARAMS),
    Feed("deepmind", "https://deepmind.google/blog/rss.xml"),
    Feed("nvidia", "https://blogs.nvidia.com/feed/"),
)


# ─────────────────────────────────────────────────────────────────────────────
# 순수 로직
# ─────────────────────────────────────────────────────────────────────────────


def slug_for(feed_key: str, url: str) -> str:
    """URL 마지막 경로 조각. arXiv 는 논문 ID 에서 버전(v1) 을 뗀다."""
    segment = [s for s in urlsplit(url).path.split("/") if s][-1]
    return _ARXIV_VERSION.sub("", segment) if feed_key == "arxiv" else segment


def _parse_when(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        when = parsedate_to_datetime(value)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(KST)


def _text(node: ET.Element | None) -> str:
    return (node.text or "") if node is not None else ""


def _rss_items(root: ET.Element) -> list[dict[str, str]]:
    out = []
    for item in root.iter("item"):
        out.append({
            "title": _text(item.find("title")), "link": _text(item.find("link")).strip(),
            "guid": _text(item.find("guid")).strip(), "when": _text(item.find("pubDate")),
            "summary": _text(item.find("description")),
        })
    return out


def _atom_entries(root: ET.Element) -> list[dict[str, str]]:
    out = []
    for entry in root.iter(f"{ATOM_NS}entry"):
        links = entry.findall(f"{ATOM_NS}link")
        alternate = next((l for l in links if l.get("rel", "alternate") == "alternate"), links[0] if links else None)
        href = (alternate.get("href") if alternate is not None else "").strip()
        out.append({
            "title": _text(entry.find(f"{ATOM_NS}title")), "link": href,
            "guid": href,                                          # fixture: Atom 의 guid 는 alternate 링크
            "when": _text(entry.find(f"{ATOM_NS}published")) or _text(entry.find(f"{ATOM_NS}updated")),
            "summary": _text(entry.find(f"{ATOM_NS}summary")) or _text(entry.find(f"{ATOM_NS}content")),
        })
    return out


def parse_feed(xml_text: str, feed: Feed, collected_at: datetime) -> list[RawArticle]:
    root = ET.fromstring(xml_text)
    entries = _atom_entries(root) if root.tag == f"{ATOM_NS}feed" else _rss_items(root)
    articles = []
    for e in entries:
        if not e["link"] or not e["title"]:
            continue
        anchor = anchor_url(e["link"])
        articles.append(RawArticle(
            article_id=f"rss:{feed.key}:{slug_for(feed.key, e['link'])}",
            origin=Origin.OVERSEAS,
            source=SourceKind.RSS,
            title=clean_html(e["title"]),
            url=e["link"],
            publisher=publisher_name(anchor),
            published_at=_parse_when(e["when"]),
            collected_at=ensure_kst(collected_at),
            metrics=RawMetrics(),
            description=clean_html(e["summary"]),
            query=feed.key,
            extra={
                "feed_url": feed.url,
                "guid": e["guid"] or e["link"],
                "normalized_url": normalize_for_compare(e["link"]),
                "anchor_url": anchor,
            },
        ))
    return articles


def dedupe(articles: Iterable[RawArticle]) -> list[RawArticle]:
    seen: dict[str, RawArticle] = {}
    for a in articles:
        seen.setdefault(a.article_id, a)
    return list(seen.values())


# ─────────────────────────────────────────────────────────────────────────────
# 네트워크 호출부
# ─────────────────────────────────────────────────────────────────────────────


def fetch_feed(feed: Feed, week: WeekMeta, *, get_text: GetText = get_text,
               collected_at: datetime | None = None, sleep: Callable[[float], None] = time.sleep) -> list[RawArticle]:
    """피드 1개. 429(Rate exceeded) 면 한 번만 더 기다렸다 재시도한다 — arXiv 가 그렇다 (실측 2026-09-08)."""
    try:
        xml_text = get_text(feed.url, feed.params or None)
    except http.HttpError as e:
        if e.status != 429:
            raise
        log.warning("rss %s 429 — %ds 뒤 1회 재시도", feed.key, RATE_LIMIT_RETRY_SECONDS)
        sleep(RATE_LIMIT_RETRY_SECONDS)
        xml_text = get_text(feed.url, feed.params or None)
    stamp = collected_at or now_kst()
    return [a for a in parse_feed(xml_text, feed, stamp) if week.contains(a.published_at)]


def collect_rss(week: WeekMeta, *, feeds: Iterable[Feed] = DEFAULT_FEEDS, get_text: GetText = get_text,
                collected_at: datetime | None = None, sleep: Callable[[float], None] = time.sleep) -> list[RawArticle]:
    """피드 전부 수집. **피드 하나의 실패가 나머지를 막지 않는다** — 건너뛰고 로그에 남긴다 (SPEC 6절)."""
    stamp = collected_at or now_kst()
    pooled: list[RawArticle] = []
    previous_key = None
    for feed in feeds:
        if feed.key == "arxiv" and previous_key == "arxiv":
            sleep(ARXIV_DELAY_SECONDS)
        previous_key = feed.key
        try:
            got = fetch_feed(feed, week, get_text=get_text, collected_at=stamp, sleep=sleep)
        except Exception as e:  # noqa: BLE001 — 예비 풀 피드 하나 때문에 해외 수집을 잃지 않는다
            log.warning("rss %s 실패 — 건너뜀 (%s): %s", feed.key, feed.url, e)
            continue
        log.info("rss %s: 창 안 %d건 (%s)", feed.key, len(got), feed.url)
        pooled.extend(got)
    return dedupe(pooled)
