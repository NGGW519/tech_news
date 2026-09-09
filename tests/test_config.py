"""src/config.py — REQUIRED 키 집합과 Settings 의 1:1 대응, 누락 시 조기 종료 (SPEC 12절).

`Settings.from_env()` 는 어떤 API 도 부르기 전에 도는 유일한 게이트다. 키가 없으면 여기서 멈춰야
Gemini 비용을 쓰기 전에 드러나고, 값을 채운 뒤 `workflow_dispatch` 로 그 주를 회복할 수 있다 (SPEC 9·12절).
"""

from __future__ import annotations

import dataclasses

import pytest

from src.config import REQUIRED, Settings

VALUES = {
    "NAVER_CLIENT_ID": "nid",
    "NAVER_CLIENT_SECRET": "nsecret",
    "GEMINI_API_KEY": "gkey",
    "NOTION_TOKEN": "ntoken",
    "NOTION_ROOT_PAGE_ID": "11111111-2222-3333-4444-555555555555",
    "NOTION_USER_ID": "1cfd872b-0000-4000-8000-000000000000",
}


@pytest.fixture
def env(monkeypatch):
    for key, value in VALUES.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_required_is_six_keys_matching_settings_fields(env):
    # SPEC 12절 자격 증명 표 = config.REQUIRED = 워크플로우 env:. 셋이 어긋나면 런타임에야 드러난다
    assert len(REQUIRED) == 6
    assert set(REQUIRED) == set(VALUES)
    assert [f.name for f in dataclasses.fields(Settings)] == [k.lower() for k in REQUIRED]
    assert Settings.from_env().notion_user_id == VALUES["NOTION_USER_ID"]


@pytest.mark.parametrize("missing", REQUIRED)
def test_missing_key_exits_before_any_api_call(env, missing):
    env.delenv(missing)
    with pytest.raises(SystemExit) as exc:
        Settings.from_env()
    assert missing in str(exc.value)


def test_missing_key_error_names_keys_only_never_values(env):
    # 비밀값은 어떤 출력에도 찍지 않는다 (SPEC 12절). 누락 메시지는 키 이름만 나열한다
    env.delenv("NOTION_USER_ID")
    with pytest.raises(SystemExit) as exc:
        Settings.from_env()
    message = str(exc.value)
    assert not any(v in message for v in VALUES.values())
