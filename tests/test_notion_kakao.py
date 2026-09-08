"""src/notion.py · src/kakao.py — 가짜 HTTP 로 멱등성·append·링크·토큰·발송 계약 검증."""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.kakao import KakaoError, build_message_text, refresh_access_token, send_to_me
from src.notion import NOTION_API, NotionApi, block_anchor_url, page_url
from src.week import compute_week

ROOT = "11111111-2222-3333-4444-555555555555"


class FakeNotion:
    """루트 아래 child_page 목록과 월 페이지의 블록 목록을 흉내 낸다. 페이지네이션 2쪽."""

    def __init__(self, month_pages: dict[str, str], month_blocks: list[dict]):
        self.month_pages, self.month_blocks, self.calls = month_pages, month_blocks, []

    def get_json(self, url, params, headers):
        self.calls.append(("GET", url, dict(params)))
        assert headers["Authorization"] == "Bearer tok" and "Notion-Version" in headers
        block_id = url.split("/blocks/")[1].split("/")[0]
        if block_id == ROOT:
            results = [{"type": "child_page", "id": pid, "child_page": {"title": t}} for t, pid in self.month_pages.items()]
        else:
            results = self.month_blocks
        # 2쪽으로 쪼개서 has_more/next_cursor 경로를 태운다
        if params.get("start_cursor") is None:
            return {"results": results[:1], "has_more": len(results) > 1, "next_cursor": "c1" if len(results) > 1 else None}
        return {"results": results[1:], "has_more": False, "next_cursor": None}

    def post_json(self, url, payload, headers):
        self.calls.append(("POST", url, payload))
        return {"id": "new-month-page-id"}

    def patch_json(self, url, payload, headers):
        self.calls.append(("PATCH", url, payload))
        return {"results": [{"id": "aaaa-bbbb", "type": "toggle"}]}


def _toggle(text):
    return {"type": "toggle", "toggle": {"rich_text": [{"plain_text": text}]}}


def test_month_page_reuse_and_create():
    fake = FakeNotion({"2026-07": "p7", "2026-08": "p8"}, [])
    api = NotionApi("tok", fake.get_json, fake.post_json, fake.patch_json)
    assert api.ensure_month_page(ROOT, "2026-08") == "p8"                    # 2쪽째에 있는 페이지도 찾는다
    assert api.ensure_month_page(ROOT, "2026-09") == "new-month-page-id"
    create = [c for c in fake.calls if c[0] == "POST"][0]
    assert create[1] == f"{NOTION_API}/pages"
    assert create[2]["parent"] == {"page_id": ROOT}
    assert create[2]["properties"]["title"]["title"][0]["text"]["content"] == "2026-09"


def test_idempotency_uses_week_key_prefix_only():
    blocks = [{"type": "paragraph"}, _toggle("8월 2주 (08/10~08/16) · 국내 3 / 해외 5"), _toggle("8월 3주 (08/17~08/23) · 국내 5 / 해외 5")]
    api = NotionApi("tok", *[getattr(FakeNotion({}, blocks), m) for m in ("get_json", "post_json", "patch_json")])
    assert api.week_toggle_exists("p8", "8월 3주") is True                     # 건수·날짜가 달라도 접두 일치
    assert api.week_toggle_exists("p8", "8월 2주") is True
    assert api.week_toggle_exists("p8", "8월 4주") is False
    assert api.week_toggle_exists("p8", "8월") is True                         # 접두 일치의 의미 그대로


def test_append_returns_block_id_and_anchor_url():
    fake = FakeNotion({}, [])
    api = NotionApi("tok", fake.get_json, fake.post_json, fake.patch_json)
    block = {"object": "block", "type": "toggle", "toggle": {"rich_text": [], "children": []}}
    block_id = api.append_week_toggle("p8-id", block)
    assert block_id == "aaaa-bbbb"
    patch = [c for c in fake.calls if c[0] == "PATCH"][0]
    assert patch[1] == f"{NOTION_API}/blocks/p8-id/children" and patch[2] == {"children": [block]}
    assert block_anchor_url("1111-2222", block_id) == "https://www.notion.so/11112222#aaaabbbb"
    assert block_anchor_url("1111-2222", None) == page_url("1111-2222") == "https://www.notion.so/11112222"


# ─────────────────────────────────────────────────────────────────────────────
# 카카오
# ─────────────────────────────────────────────────────────────────────────────


def test_message_text_matches_spec_8_and_fits_limit():
    week = compute_week(date(2026, 9, 7))
    text = build_message_text(week, 3, 5)
    assert text == "📡 이번 주 테크 브리핑 · 국내 3 / 해외 5\n9월 1주 (08/31~09/06)"
    assert len(text) <= 200


def test_refresh_token_flow_with_and_without_rotation():
    calls = []

    def fake(url, form, headers=None):
        calls.append((url, dict(form)))
        return {"access_token": "acc", "expires_in": 43199} if "client_secret" in form else \
               {"access_token": "acc2", "refresh_token": "new-r", "refresh_token_expires_in": 100}

    t = refresh_access_token("rest", "old-r", "sec", post_form=fake)
    assert t.access_token == "acc" and t.new_refresh_token is None
    assert calls[0][1] == {"grant_type": "refresh_token", "client_id": "rest", "refresh_token": "old-r", "client_secret": "sec"}
    t2 = refresh_access_token("rest", "old-r", None, post_form=fake)
    assert t2.new_refresh_token == "new-r" and "client_secret" not in calls[1][1]


def test_refresh_failure_raises():
    with pytest.raises(KakaoError):
        refresh_access_token("rest", "r", post_form=lambda u, f, h=None: {"error": "invalid_grant", "error_code": "KOE319"})


def test_send_to_me_template_and_result_check():
    calls = []

    def fake(url, form, headers=None):
        calls.append((url, dict(form), dict(headers or {})))
        return {"result_code": 0}

    send_to_me("acc", "본문", "https://www.notion.so/abc#def", post_form=fake)
    url, form, headers = calls[0]
    assert url == "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    assert headers == {"Authorization": "Bearer acc"}
    template = json.loads(form["template_object"])
    assert template == {"object_type": "text", "text": "본문",
                        "link": {"web_url": "https://www.notion.so/abc#def", "mobile_web_url": "https://www.notion.so/abc#def"},
                        "button_title": "Notion에서 보기"}
    with pytest.raises(KakaoError):
        send_to_me("acc", "x", "u", post_form=lambda u, f, h=None: {"result_code": -401})
