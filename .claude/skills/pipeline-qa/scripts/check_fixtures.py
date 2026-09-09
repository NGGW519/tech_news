#!/usr/bin/env python3
"""fixture ↔ schema ↔ SPEC 규약 정합성 검사기 (pipeline-qa 스킬 번들).

tests/fixtures/README.md 가 "테스트가 의존해도 되는 것" 으로 못박은 규약을 기계적으로 확인한다.
pytest 가 각 모듈을 따로 검증한다면, 이 스크립트는 **경계면**(파일 간 계약)을 교차 비교한다.

    python3 .claude/skills/pipeline-qa/scripts/check_fixtures.py          # 전체 검사
    python3 .claude/skills/pipeline-qa/scripts/check_fixtures.py -v       # 통과 항목도 출력

종료 코드: 0 = 전부 통과, 1 = 실패 있음. 프로젝트 루트에서 실행한다 (src 를 import 한다).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]      # .claude/skills/pipeline-qa/scripts → 프로젝트 루트
sys.path.insert(0, str(ROOT))

from src.schema import BriefItem, RankedArticle, RawArticle  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"

# README "스키마별" 표 — 파일 ↔ 타입 ↔ 건수. README 를 고치면 여기도 고친다.
SCHEMA_FILES: dict[str, tuple[type, int]] = {
    "raw_articles_domestic.json": (RawArticle, 3),
    "raw_articles_overseas.json": (RawArticle, 12),
    "ranked_articles_domestic.json": (RankedArticle, 3),
    "ranked_articles_overseas.json": (RankedArticle, 5),
    "ranked_articles_overseas_reserve.json": (RankedArticle, 1),
    "enriched_articles_overseas.json": (RankedArticle, 5),
    "brief_items_domestic.json": (BriefItem, 3),
    "brief_items_overseas.json": (BriefItem, 5),
}

ID_PREFIXES = ("naver:", "hn:", "reddit:", "rss:")
ENRICH_KEYS = {"enrich_status", "enrich_text", "enrich_url"}
FALLBACK_SUFFIX = "⚠️ 자동 요약 실패"


class Report:
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.failed = 0
        self.passed = 0

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        if ok:
            self.passed += 1
            if self.verbose:
                print(f"  PASS  {label}")
        else:
            self.failed += 1
            print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))


def load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def check_roundtrip(r: Report) -> dict[str, list]:
    """스키마 from_dict → to_dict 왕복이 원본 JSON 과 같은가 (README: 전부 확인돼 있다)."""
    print("[1] 스키마 왕복 · 건수")
    loaded: dict[str, list] = {}
    for name, (cls, expected_n) in SCHEMA_FILES.items():
        raw = load(name)
        r.check(len(raw) == expected_n, f"{name} 건수 {expected_n}", f"실제 {len(raw)}")
        objs, mismatches = [], []
        for i, d in enumerate(raw):
            try:
                obj = cls.from_dict(d)
            except Exception as e:  # noqa: BLE001
                mismatches.append(f"#{i} from_dict 예외: {e}")
                continue
            objs.append(obj)
            if obj.to_dict() != d:
                mismatches.append(f"#{i} 왕복 불일치")
        r.check(not mismatches, f"{name} {cls.__name__} 왕복", "; ".join(mismatches[:3]))
        loaded[name] = objs
    return loaded


def article_of(x) -> RawArticle:
    return x.article if isinstance(x, RankedArticle) else x


def check_article_ids(r: Report, loaded: dict[str, list]) -> None:
    """article_id 규약 (SPEC 6절) — 접두사, 파일 내 고유성, 병합/클러스터 근거 ID 의 자기 포함."""
    print("[2] article_id 규약")
    for name in ("raw_articles_domestic.json", "raw_articles_overseas.json",
                 "ranked_articles_domestic.json", "ranked_articles_overseas.json"):
        ids = [article_of(x).article_id for x in loaded[name]]
        bad = [i for i in ids if not i.startswith(ID_PREFIXES)]
        r.check(not bad, f"{name} article_id 접두사", f"{bad}")
        r.check(len(ids) == len(set(ids)), f"{name} article_id 고유", "중복 있음")
    for name in ("ranked_articles_domestic.json", "ranked_articles_overseas.json"):
        for ra in loaded[name]:
            aid = ra.article.article_id
            ev = ra.to_dict().get("evidence", {})
            merged = ev.get("merged_article_ids") or []
            cluster = ev.get("cluster_article_ids") or []
            r.check(aid in merged or aid in cluster,
                    f"{name} {aid} 근거 ID 가 자기 자신을 담음", f"merged={merged} cluster={cluster}")


def check_timezone(r: Report, loaded: dict[str, list]) -> None:
    """모든 시각은 tz-aware KST(+09:00) — 직렬화 문자열에서 확인 (schema 계약)."""
    print("[3] 시각 KST")
    for name, objs in loaded.items():
        if "brief" in name:
            continue
        bad = []
        for x in objs:
            d = article_of(x).to_dict()
            ts = d.get("published_at") or ""
            if not ts.endswith("+09:00"):
                bad.append(f"{d.get('article_id')}: {ts}")
        r.check(not bad, f"{name} published_at +09:00", "; ".join(bad[:3]))


def check_url_keys(r: Report, loaded: dict[str, list]) -> None:
    """URL 정규화 산출물 (SPEC 4·6절 v1.3): 해외는 normalized_url·anchor_url 둘 다, 국내는 둘 다 없음."""
    print("[4] URL 정규화 키 (해외 有 / 국내 無)")
    for name in ("ranked_articles_overseas.json", "enriched_articles_overseas.json",
                 "ranked_articles_overseas_reserve.json"):
        missing = [ra.article.article_id for ra in loaded[name]
                   if not {"normalized_url", "anchor_url"} <= set(ra.article.extra)]
        r.check(not missing, f"{name} normalized_url·anchor_url 존재", f"{missing}")
    present = [ra.article.article_id for ra in loaded["ranked_articles_domestic.json"]
               if {"normalized_url", "anchor_url"} & set(ra.article.extra)]
    r.check(not present, "ranked_articles_domestic.json 정규화 키 없음", f"{present}")
    # 해외 출력 앵커 = anchor_url (normalized_url 이 아니다)
    anchors = {ra.article.article_id: ra.article.extra["anchor_url"] for ra in loaded["enriched_articles_overseas.json"]}
    bad = [b.source_article_id for b in loaded["brief_items_overseas.json"]
           if anchors.get(b.source_article_id) != b.url]
    r.check(not bad, "brief_items_overseas.url == extra.anchor_url", f"{bad}")


def check_enrich(r: Report, loaded: dict[str, list]) -> None:
    """본문 보강 (SPEC 6.5절): enriched 와 ranked 의 차이는 extra.enrich_* 키뿐. 국내엔 enrich_* 없음."""
    print("[5] 본문 보강 산출물")
    ranked = {ra.article.article_id: ra.to_dict() for ra in loaded["ranked_articles_overseas.json"]}
    for ra in loaded["enriched_articles_overseas.json"]:
        d = ra.to_dict()
        aid = d["article"]["article_id"]
        base = ranked.get(aid)
        r.check(base is not None, f"{aid} ranked 에도 존재")
        if base is None:
            continue
        extra_e = dict(d["article"]["extra"])
        extra_r = dict(base["article"]["extra"])
        stripped = {k: v for k, v in extra_e.items() if k not in ENRICH_KEYS}
        r.check(stripped == extra_r, f"{aid} enrich_* 외 extra 동일")
        d_wo = {**d, "article": {**d["article"], "extra": stripped}}
        r.check(d_wo == base, f"{aid} extra 외 필드 동일")
        status = extra_e.get("enrich_status")
        r.check(status in ("success", "failed"), f"{aid} enrich_status 값", f"{status}")
        if status == "failed":
            r.check("enrich_text" not in extra_e, f"{aid} failed 면 enrich_text 키 없음")
        if status == "success":
            r.check(bool(extra_e.get("enrich_text")), f"{aid} success 면 enrich_text 존재")
        r.check(extra_e.get("enrich_url") == extra_e.get("anchor_url"), f"{aid} enrich_url == anchor_url")
    for ra in loaded["ranked_articles_domestic.json"]:
        r.check(not (ENRICH_KEYS & set(ra.article.extra)), f"{ra.article.article_id} 국내 enrich_* 없음")


def check_reserve(r: Report, loaded: dict[str, list]) -> None:
    """예비 풀 (SPEC 6절): sort_score -1.0, normalized_score null, score_components {}."""
    print("[6] 예비 풀")
    for ra in loaded["ranked_articles_overseas_reserve.json"]:
        d = ra.to_dict()
        aid = d["article"]["article_id"]
        r.check(d.get("sort_score") == -1.0, f"{aid} sort_score -1.0", f"{d.get('sort_score')}")
        ev = d.get("evidence", {})
        r.check(ev.get("normalized_score") is None, f"{aid} normalized_score null", f"{ev.get('normalized_score')}")
        r.check(ev.get("score_components") in ({}, None), f"{aid} score_components 비어 있음", f"{ev.get('score_components')}")
    main_ids = {ra.article.article_id for ra in loaded["ranked_articles_overseas.json"]}
    reserve_ids = {ra.article.article_id for ra in loaded["ranked_articles_overseas_reserve.json"]}
    r.check(not (main_ids & reserve_ids), "예비 풀 ↔ 본 랭킹 겹치지 않음", f"{main_ids & reserve_ids}")


def check_ranks(r: Report, loaded: dict[str, list]) -> None:
    """rank 는 1..N 연속, sort_score 내림차순 (동점은 허용)."""
    print("[7] 순위 연속성")
    for name in ("ranked_articles_domestic.json", "ranked_articles_overseas.json"):
        ds = [ra.to_dict() for ra in loaded[name]]
        ranks = [d["rank"] for d in ds]
        r.check(ranks == list(range(1, len(ds) + 1)), f"{name} rank 1..{len(ds)}", f"{ranks}")
        scores = [d["sort_score"] for d in ds]
        r.check(scores == sorted(scores, reverse=True), f"{name} sort_score 내림차순", f"{scores}")


def check_brief_items(r: Report, loaded: dict[str, list]) -> None:
    """요약 산출물 (SPEC 7절): source_article_id 가 ranked 에 존재, fallback 형태, 순위 매칭."""
    print("[8] BriefItem ↔ RankedArticle")
    pairs = (("brief_items_domestic.json", "ranked_articles_domestic.json"),
             ("brief_items_overseas.json", "enriched_articles_overseas.json"))
    for bname, rname in pairs:
        ranked = {ra.article.article_id: ra for ra in loaded[rname]}
        for b in loaded[bname]:
            d = b.to_dict()
            aid = d["source_article_id"]
            ra = ranked.get(aid)
            r.check(ra is not None, f"{bname} {aid} 가 {rname} 에 존재")
            if ra is None:
                continue
            r.check(d["rank"] == ra.rank, f"{aid} rank 일치", f"brief {d['rank']} vs ranked {ra.rank}")
            r.check(d["origin"] == ra.article.origin.value if hasattr(ra.article.origin, "value") else d["origin"] == ra.article.origin,
                    f"{aid} origin 일치")
            lines = d["summary_lines"]
            if d["summary_status"] == "gemini":
                r.check(1 <= len(lines) <= 2, f"{aid} gemini 문장 수 1~2", f"{len(lines)}")
                r.check(not any(FALLBACK_SUFFIX in s for s in lines), f"{aid} gemini 에 fallback 표식 없음")
            else:
                r.check(len(lines) in (0, 1), f"{aid} fallback 문장 수 0 또는 1", f"{len(lines)}")
                if lines:
                    r.check(lines[0].endswith(FALLBACK_SUFFIX), f"{aid} fallback 말미 표식", f"{lines[0][-20:]}")
                    src = ra.article.description or ra.article.extra.get("enrich_text") or ""
                    head = src[:120].rstrip()
                    r.check(lines[0] == f"{head} {FALLBACK_SUFFIX}", f"{aid} fallback = 원천[:120] + 표식")


def check_publishers(r: Report, loaded: dict[str, list]) -> None:
    """publisher 표 (SPEC 6절): fixture 에 등장하는 도메인은 전부 표에서 재현돼야 한다."""
    print("[9] publisher 표 재현")
    from src.publishers import publisher_name

    # raw 풀 전체(12+3건)로 본다 — 랭킹에서 잘린 항목의 도메인도 표에 있어야 한다 (SPEC 6절 "초기 표")
    for name in ("raw_articles_domestic.json", "raw_articles_overseas.json"):
        for a in loaded[name]:
            url = a.extra.get("anchor_url", a.url)      # 국내는 originallink(=url), 해외는 앵커용 URL
            got = publisher_name(url, subreddit=a.extra.get("subreddit"), is_self=bool(a.extra.get("is_self")))
            r.check(got == a.publisher, f"{a.article_id} publisher 재현", f"표 {got!r} vs fixture {a.publisher!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    r = Report(args.verbose)
    loaded = check_roundtrip(r)
    check_article_ids(r, loaded)
    check_timezone(r, loaded)
    check_url_keys(r, loaded)
    check_enrich(r, loaded)
    check_reserve(r, loaded)
    check_ranks(r, loaded)
    check_brief_items(r, loaded)
    check_publishers(r, loaded)
    print(f"\n{r.passed} passed, {r.failed} failed")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
