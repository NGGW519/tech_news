"""Notion 호출부 — 월 페이지 확보 · 멱등성 체크 · 주차 토글 append · 링크 (SPEC 5·8·9절).

    1. 루트 아래 월 페이지 `2026-09` → 없으면 생성, 있으면 재사용
    2. 월 페이지 블록 조회(페이지네이션) → `week_key` 로 시작하는 토글이 있으면 "이미 존재"
    3. 주차 토글 append → 생성된 블록 id
    4. 카톡 링크 = https://www.notion.so/<page_id>#<하이픈 제거한 block_id>. 못 얻으면 월 페이지 URL

HTTP 함수는 주입 가능하다 (get_json / post_json / patch_json). 렌더링은 src/render_notion.py 가 한다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from src import http

log = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"      # SPEC 11절 확인 대상. 블록/페이지 엔드포인트는 이 버전에서 안정
PAGE_SIZE = 100


def _bare(notion_id: str) -> str:
    return notion_id.replace("-", "")


def page_url(page_id: str) -> str:
    return f"https://www.notion.so/{_bare(page_id)}"


def block_anchor_url(page_id: str, block_id: str | None) -> str:
    """주차 토글 앵커. block_id 가 없으면 월 페이지 URL 로 fallback (SPEC 8절)."""
    return f"{page_url(page_id)}#{_bare(block_id)}" if block_id else page_url(page_id)


@dataclass
class NotionApi:
    token: str
    get_json: Callable[..., Any] = http.get_json
    post_json: Callable[..., Any] = http.post_json
    patch_json: Callable[..., Any] = http.patch_json
    headers: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self.headers = {"Authorization": f"Bearer {self.token}", "Notion-Version": NOTION_VERSION}

    # ── 블록 조회 ──
    def iter_children(self, block_id: str) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            params = {"page_size": str(PAGE_SIZE)}
            if cursor:
                params["start_cursor"] = cursor
            payload = self.get_json(f"{NOTION_API}/blocks/{block_id}/children", params, self.headers)
            yield from payload.get("results", [])
            if not payload.get("has_more"):
                return
            cursor = payload.get("next_cursor")

    # ── 월 페이지 ──
    def find_child_page(self, parent_page_id: str, title: str) -> str | None:
        for block in self.iter_children(parent_page_id):
            if block.get("type") == "child_page" and block["child_page"].get("title") == title:
                return block["id"]
        return None

    def create_child_page(self, parent_page_id: str, title: str) -> str:
        payload = {
            "parent": {"page_id": parent_page_id},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        }
        return self.post_json(f"{NOTION_API}/pages", payload, self.headers)["id"]

    def ensure_month_page(self, root_page_id: str, title: str) -> str:
        existing = self.find_child_page(root_page_id, title)
        if existing:
            log.info("month page reuse %s (%s)", title, existing)
            return existing
        created = self.create_child_page(root_page_id, title)
        log.info("month page created %s (%s)", title, created)
        return created

    # ── 멱등성 (SPEC 9절: week_key 접두 일치로만) ──
    def week_toggle_exists(self, month_page_id: str, week_key: str) -> bool:
        for block in self.iter_children(month_page_id):
            if block.get("type") != "toggle":
                continue
            rich = block["toggle"].get("rich_text") or []
            if rich and str(rich[0].get("plain_text", "")).startswith(week_key):
                return True
        return False

    # ── append ──
    def append_week_toggle(self, month_page_id: str, toggle_block: dict[str, Any]) -> str | None:
        payload = self.patch_json(f"{NOTION_API}/blocks/{month_page_id}/children", {"children": [toggle_block]}, self.headers)
        results = payload.get("results") or []
        return results[0].get("id") if results else None
