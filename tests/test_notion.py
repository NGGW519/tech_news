"""src/notion.py — 가짜 HTTP 로 월 페이지·멱등성·append·앵커 URL 계약 검증."""

from __future__ import annotations

from src.notion import NOTION_API, NotionApi, block_anchor_url, page_url
from src.render_notion import mention

ROOT = "11111111-2222-3333-4444-555555555555"
USER_ID = "1cfd872b-0000-4000-8000-000000000000"   # 알림 멘션 대상 (SPEC 12절 NOTION_USER_ID)


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


def _toggle_with_mention(text):
    """실제로 우리가 만드는 토글의 모양 — 라벨 뒤에 mention (SPEC 5절 표).

    Notion 이 돌려주는 mention 조각의 `plain_text` 는 사용자 이름이다. 그것이 `rich_text[1]` 에
    있는 한 멱등성 판정은 영향받지 않는다 — 판정은 `[0]` 만 본다 (SPEC 9절).
    """
    piece = dict(mention(USER_ID), plain_text="@건우 남궁")
    return {"type": "toggle", "toggle": {"rich_text": [{"plain_text": text}, piece]}}


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


def test_idempotency_holds_when_toggle_carries_a_mention():
    # SPEC 9절 계약: mention 이 rich_text[0] 뒤에 있는 한 접두 일치가 유지된다.
    # 앞에 넣으면 첫 조각의 plain_text 가 사용자 이름이 되어 매주 토글이 중복 생성된다
    blocks = [_toggle_with_mention("8월 2주 (08/10~08/16) · 국내 3 / 해외 5")]
    api = NotionApi("tok", *[getattr(FakeNotion({}, blocks), m) for m in ("get_json", "post_json", "patch_json")])
    assert api.week_toggle_exists("p8", "8월 2주") is True
    assert api.week_toggle_exists("p8", "8월 4주") is False

    reversed_blocks = [{"type": "toggle", "toggle": {"rich_text": list(reversed(blocks[0]["toggle"]["rich_text"]))}}]
    api2 = NotionApi("tok", *[getattr(FakeNotion({}, reversed_blocks), m) for m in ("get_json", "post_json", "patch_json")])
    assert api2.week_toggle_exists("p8", "8월 2주") is False       # 순서를 뒤집으면 이렇게 깨진다


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
