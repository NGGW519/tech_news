"""설정 — 환경 변수(GitHub Secrets) 또는 로컬 .env (SPEC 12절). 코드에 값을 두지 않는다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# SPEC 12절 자격 증명 표와 워크플로우 env: 와 1:1. 셋 중 하나만 바뀌면 drift 다.
REQUIRED = (
    "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "GEMINI_API_KEY",
    "NOTION_TOKEN", "NOTION_ROOT_PAGE_ID", "NOTION_USER_ID",
)


def load_dotenv(path: Path = ENV_FILE) -> None:
    """`.env` 의 KEY=VALUE 를 환경에 넣는다. 이미 있는 변수는 덮지 않는다 (Actions Secrets 우선)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class Settings:
    naver_client_id: str
    naver_client_secret: str
    gemini_api_key: str
    notion_token: str
    notion_root_page_id: str
    notion_user_id: str                        # 알림 멘션 대상. 만료 없는 상수 UUID (SPEC 8·12절)

    @classmethod
    def from_env(cls) -> Settings:
        missing = [k for k in REQUIRED if not os.environ.get(k)]
        if missing:
            raise SystemExit("환경 변수 누락: " + ", ".join(missing) + " (로컬은 .env, Actions 는 Secrets)")
        return cls(
            naver_client_id=os.environ["NAVER_CLIENT_ID"],
            naver_client_secret=os.environ["NAVER_CLIENT_SECRET"],
            gemini_api_key=os.environ["GEMINI_API_KEY"],
            notion_token=os.environ["NOTION_TOKEN"],
            notion_root_page_id=os.environ["NOTION_ROOT_PAGE_ID"],
            notion_user_id=os.environ["NOTION_USER_ID"],
        )
