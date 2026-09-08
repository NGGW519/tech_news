"""파이프라인 진입점 (SPEC 3절 순서 고정).

    수집(국내·해외) → 랭킹 → 예비 풀 보충 → 본문 보강(해외) → 요약 → 멱등성 체크 → Notion → 카카오 → 실행 로그

모든 외부 호출은 `Services` 로 주입한다. 테스트는 전부 가짜로 채워 fixture 만으로 끝까지 돈다.
한쪽 수집이 통째로 죽어도 다른 쪽은 발행한다 (SPEC 2절 부분 발행). 그런 실패가 있었으면 종료 코드 1 로
Actions 실패 알림을 울리되, 발행 자체는 끝낸 뒤다.

    python -m src.main                 # 실제 실행 (.env 또는 Secrets)
    python -m src.main --dry-run       # Notion·카카오에 쓰지 않고 결과만 출력
    python -m src.main --no-llm        # Gemini 를 부르지 않는다 (전부 fallback) — 비용 없이 수집·랭킹 점검
    python -m src.main --date 2026-08-17
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from functools import partial
from pathlib import Path

from src import kakao
from src.collect_hn import collect_hn
from src.collect_naver import collect_domestic
from src.collect_reddit import collect_reddit
from src.collect_rss import collect_rss
from src.config import PROJECT_ROOT, Settings, load_dotenv
from src.enrich import enrich_ranked
from src.notion import NotionApi, block_anchor_url
from src.rank_domestic import rank_domestic
from src.rank_overseas import TOP_N, OverseasRanking, rank_overseas
from src.render_notion import render_brief_text, render_week_toggle
from src.schema import KST, RankedArticle, RawArticle, SummaryStatus, WeekMeta, WeeklyBrief, now_kst
from src.summarize import Call, call_gemini, summarize_section
from src.week import current_week

log = logging.getLogger("tech_news")

LOG_FILE = PROJECT_ROOT / "logs" / "last_run.txt"


@dataclass
class Services:
    collect_domestic: Callable[[WeekMeta], list[RawArticle]]
    collect_overseas: Callable[[WeekMeta], list[RawArticle]]
    enrich: Callable[[list[RankedArticle]], list[RankedArticle]]
    summarize_call: Call
    notion: NotionApi
    notion_root_page_id: str
    kakao_refresh: Callable[[], kakao.Tokens]
    kakao_send: Callable[[str, str, str], None]          # (access_token, text, link_url)
    persist_refresh_token: Callable[[str], None]
    log_file: Path = LOG_FILE


@dataclass
class RunResult:
    week: WeekMeta
    domestic: int
    overseas: int
    status: str                       # "published" | "already_exists" | "nothing_to_publish" | "dry_run"
    notion_link: str | None = None
    failures: tuple[str, ...] = ()    # 잡아서 넘어간 단계 이름

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0


# ─────────────────────────────────────────────────────────────────────────────
# 실제 서비스 조립
# ─────────────────────────────────────────────────────────────────────────────


def _no_llm_call(_: dict) -> dict:
    raise RuntimeError("--no-llm: Gemini 호출을 건너뛴다")


def build_services(settings: Settings, *, no_llm: bool = False) -> Services:
    def overseas(week: WeekMeta) -> list[RawArticle]:
        stamp = now_kst()
        return (collect_hn(week, collected_at=stamp) + collect_reddit(week, collected_at=stamp)
                + collect_rss(week, collected_at=stamp))

    def persist(new_token: str) -> None:
        path = os.environ.get("KAKAO_NEW_REFRESH_TOKEN_FILE")
        if path:
            Path(path).write_text(new_token, encoding="utf-8")
            log.warning("새 refresh token 을 %s 에 썼다 — 워크플로우가 Secrets 를 갱신한다", path)
        else:
            log.warning("새 refresh token 이 발급됐지만 저장 경로(KAKAO_NEW_REFRESH_TOKEN_FILE)가 없다. "
                        "만료 전에 scripts/kakao_refresh_token.py 로 재발급하라")

    return Services(
        collect_domestic=lambda week: collect_domestic(
            week, client_id=settings.naver_client_id, client_secret=settings.naver_client_secret),
        collect_overseas=overseas,
        enrich=enrich_ranked,
        summarize_call=_no_llm_call if no_llm else partial(call_gemini, api_key=settings.gemini_api_key),
        notion=NotionApi(settings.notion_token),
        notion_root_page_id=settings.notion_root_page_id,
        kakao_refresh=lambda: kakao.refresh_access_token(
            settings.kakao_rest_api_key, settings.kakao_refresh_token, settings.kakao_client_secret),
        kakao_send=kakao.send_to_me,
        persist_refresh_token=persist,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 파이프라인
# ─────────────────────────────────────────────────────────────────────────────


def fill_from_reserve(ranking: OverseasRanking, top_n: int = TOP_N) -> list[RankedArticle]:
    """HN+Reddit 이 5건에 못 미치면 예비 풀(최신순)로 채운다. rank 는 이어서 다시 매긴다 (SPEC 6절)."""
    top = list(ranking.top)
    for r in ranking.reserve[: max(0, top_n - len(top))]:
        top.append(replace(r, rank=len(top) + 1))
    return top


def _guard(stage: str, fn: Callable, default, failures: list[str]):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — 한 단계의 실패가 그 주 전체를 잃게 하지 않는다 (SPEC 2절)
        log.exception("%s 실패 — 계속 진행: %s", stage, e)
        failures.append(stage)
        return default


def run(services: Services, *, now: datetime | None = None, dry_run: bool = False) -> RunResult:
    week = current_week(now)
    failures: list[str] = []
    log.info("week %s / window %s ~ %s", week.week_key, week.window_start, week.window_end)

    # 1. 수집 — 국내·해외 독립
    domestic_raw = _guard("collect_domestic", lambda: services.collect_domestic(week), [], failures)
    overseas_raw = _guard("collect_overseas", lambda: services.collect_overseas(week), [], failures)
    log.info("collected domestic %d / overseas %d", len(domestic_raw), len(overseas_raw))

    # 2. 랭킹 (+ 예비 풀 보충)
    domestic_ranked = list(rank_domestic(domestic_raw).top)
    overseas_ranking = rank_overseas(overseas_raw)
    overseas_ranked = fill_from_reserve(overseas_ranking)
    log.info("ranked domestic %d / overseas %d (reserve pool %d)",
             len(domestic_ranked), len(overseas_ranked), len(overseas_ranking.reserve))

    # 3. 본문 보강 — 해외만
    overseas_ranked = _guard("enrich", lambda: services.enrich(overseas_ranked), overseas_ranked, failures)

    # 4. 요약 — 섹션당 배치 1회
    domestic_items = summarize_section(domestic_ranked, call=services.summarize_call)
    overseas_items = summarize_section(overseas_ranked, call=services.summarize_call)
    brief = WeeklyBrief(week=week, domestic=tuple(domestic_items), overseas=tuple(overseas_items))
    gemini_ok = sum(i.summary_status is SummaryStatus.GEMINI for i in domestic_items + overseas_items)
    log.info("summarized: gemini %d / fallback %d", gemini_ok, len(domestic_items) + len(overseas_items) - gemini_ok)

    result = RunResult(week=week, domestic=len(brief.domestic), overseas=len(brief.overseas), status="", failures=tuple(failures))

    if not brief.domestic and not brief.overseas:
        log.warning("국내·해외 모두 0건 — 토글을 만들지 않는다 (SPEC 2절)")
        return _finish(services, replace(result, status="nothing_to_publish"), brief, dry_run)

    if dry_run:
        print(render_brief_text(brief))
        return _finish(services, replace(result, status="dry_run"), brief, dry_run)

    # 5. 멱등성 — Gemini 뒤에 두는 것은 의도적 (SPEC 3절 유의점 3)
    month_page_id = services.notion.ensure_month_page(services.notion_root_page_id, week.month_page_title)
    if services.notion.week_toggle_exists(month_page_id, week.week_key):
        log.info("%s 토글이 이미 있다 — 종료 (멱등성)", week.week_key)
        return _finish(services, replace(result, status="already_exists"), brief, dry_run)

    # 6. Notion
    block_id = services.notion.append_week_toggle(month_page_id, render_week_toggle(brief))
    link = block_anchor_url(month_page_id, block_id)
    if not block_id:
        log.warning("토글 블록 id 를 못 얻었다 — 월 페이지 URL 로 fallback")
    log.info("notion written: %s", link)

    # 7. 카카오 — Notion 뒤 (링크가 필요하다). 실패해도 Notion 에는 남는다 (SPEC 9절 알려진 한계)
    def send() -> None:
        tokens = services.kakao_refresh()
        services.kakao_send(tokens.access_token, kakao.build_message_text(week, len(brief.domestic), len(brief.overseas)), link)
        if tokens.new_refresh_token:
            services.persist_refresh_token(tokens.new_refresh_token)
    _guard("kakao", send, None, failures)

    return _finish(services, replace(result, status="published", notion_link=link, failures=tuple(failures)), brief, dry_run)


def _finish(services: Services, result: RunResult, brief: WeeklyBrief, dry_run: bool) -> RunResult:
    if not dry_run:
        write_run_log(services.log_file, result, brief)
    return result


def write_run_log(path: Path, result: RunResult, brief: WeeklyBrief) -> None:
    """실행 로그 1개 — 워크플로우가 커밋해 60일 비활성화를 막는다 (SPEC 9절)."""
    gemini = sum(i.summary_status is SummaryStatus.GEMINI for i in brief.domestic + brief.overseas)
    lines = [
        f"run_at: {now_kst().isoformat(timespec='seconds')}",
        f"week: {result.week.week_label}",
        f"domestic: {result.domestic}",
        f"overseas: {result.overseas}",
        f"summary: gemini {gemini} / fallback {result.domestic + result.overseas - gemini}",
        f"status: {result.status}",
        f"notion: {result.notion_link or '-'}",
        f"failures: {', '.join(result.failures) or '-'}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="주간 테크 뉴스 브리핑")
    parser.add_argument("--dry-run", action="store_true", help="Notion·카카오에 쓰지 않는다")
    parser.add_argument("--no-llm", action="store_true", help="Gemini 를 부르지 않는다 (전부 fallback)")
    parser.add_argument("--date", type=date.fromisoformat, help="실행일을 지정한다 (YYYY-MM-DD, KST)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    settings = Settings.from_env()
    now = datetime.combine(args.date, time(8, 30), tzinfo=KST) if args.date else None
    result = run(build_services(settings, no_llm=args.no_llm), now=now, dry_run=args.dry_run)
    log.info("done: %s (국내 %d / 해외 %d) exit=%d", result.status, result.domestic, result.overseas, result.exit_code)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
