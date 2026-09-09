---
name: pipeline-qa
description: "tech-news-orchestrator 가 pipeline-qa 에이전트에게 시키는 하위 절차 — 사용자 요청은 오케스트레이터가 먼저 받는다. 주간 테크 뉴스 브리핑 파이프라인의 읽기 전용 검증 규약: pytest 회귀 기준선, 번들 검사기 check_fixtures.py 실행 규약(9개 검사군), 모듈 경계면 12종 교차 검증표(수집→랭킹→보강→요약→렌더→Notion→카카오, 생산자·소비자 파일 쌍), dry-run 출력의 SPEC 4절 대조 기준, incremental QA 순서, PASS/FAIL/미검증 리포트 형식. 코드 변경 직후 검증이나 SPEC 개정 후 코드 대조를 맡은 에이전트는 이 스킬을 읽는다. 코드를 고치는 규약은 pipeline-dev, SPEC 개정 판정은 spec-change."
---

# 파이프라인 검증 절차

pytest 216개는 각 모듈을 **따로** 검증한다. 이 프로젝트에서 실제로 어긋나는 곳은 모듈 사이 — 한쪽이 쓰는
`extra` 키를 다른 쪽이 다른 이름으로 읽거나, 렌더러가 기대하는 문장 수와 요약기가 주는 문장 수가 다르거나,
워크플로우의 환경 변수 이름과 `config.REQUIRED` 가 다른 곳이다. 그런 결함은 양쪽 파일을 **같이 열어야** 보인다.
이 절차의 절반은 그 "같이 열기"의 목록이다.

## 실행 명령

| 단계 | 명령 | 기대 |
|------|------|------|
| 회귀 | `python3 -m pytest -q` | passed ≥ 기준선(216, 2026-09-09). 실패 0 |
| fixture 정합성 | `python3 .claude/skills/pipeline-qa/scripts/check_fixtures.py` (`-v` 로 통과 항목도) | `N passed, 0 failed`, 종료 코드 0 |
| 실측 | `python3 -m src.main --dry-run --no-llm --date {지난 월요일}` | stdout 에 SPEC 4절 형식 렌더. Gemini 비용 0, Notion·카카오 발행 없음. **전제:** `.env` 에 `config.REQUIRED` 7개 키가 있어야 뜬다(없으면 `환경 변수 누락` SystemExit). 네이버·HN·RSS 는 **실제 호출**된다 (네이버 일 한도 소모, arXiv 3초 간격) |
| 실측(요약 포함) | `python3 -m src.main --dry-run --date {지난 월요일}` | 위 + Gemini 요약. 소액 과금 — 요약 규칙 검증 때만 |

**Reddit 은 제거된 소스다** (커밋 `bbd2e80`, SPEC 6절 "Reddit 을 뺀 이유"). 그런데 fixture 의 `reddit:*` 항목, `SourceKind.REDDIT`, `publisher_name` 의 `subreddit`/`is_self` 인자, `rank_overseas` 의 reddit 합성 공식은 **의도적으로 남아 있다** — 결함으로 적지 않는다. 반대로 코드 주석에 "HN+Reddit" 이 남아 있으면 그것은 낡은 주석이다.

`python` 명령은 없다. `python3` 다. pytest 가 뜨지 않으면 `pytest.ini` 의 `-p no:` 목록(ROS 2 플러그인 차단)을 먼저 본다.

`check_fixtures.py` 는 9개 검사군을 돈다: 스키마 왕복·건수 / `article_id` 규약 / KST / URL 정규화 키(해외 有·국내 無) /
보강 산출물(enriched−ranked = `enrich_*` 뿐) / 예비 풀 / 순위 연속성 / BriefItem↔RankedArticle(fallback 형태 포함) /
publisher 표 재현. fixture 건수를 바꾸면 스크립트의 `SCHEMA_FILES` 도 고친다.

## 검증 순서 — incremental

engineer 가 "모듈 완성" 을 알리면 전체를 기다리지 않고 **그 모듈의 경계면부터** 본다.

1. 바뀐 파일 목록 확인 (`git diff --stat`, changes 파일)
2. 아래 경계면 표에서 바뀐 파일이 생산자 또는 소비자로 등장하는 행만 골라 교차 검증
3. 그 모듈의 테스트 파일만 먼저: `python3 -m pytest -q tests/test_{module}.py`
4. 발견 즉시 `SendMessage(to: "pipeline-engineer")` — 모아서 보내지 않는다 (첫 호출 전 `ToolSearch("select:SendMessage")`)
5. 모든 모듈 완료 후 회귀 전체 + `check_fixtures.py` + 실측(해당 시)
6. 리포트 작성

## 경계면 목록 — 양쪽을 같이 연다

각 행의 "대조" 를 실제 코드에서 확인한다. 상세(함수명, 함정, 확인 방법)는 `references/boundaries.md`.

| # | 경계면 | 생산자 | 소비자 | 대조 |
|---|--------|--------|--------|------|
| 1 | 수집 → 계약 | `collect_naver/hn/rss.py` 가 만드는 `RawArticle` | `schema.RawArticle` | `article_id` 접두사, `origin`/`source`, `metrics` None(신호 없음) vs 0, `published_at` KST, `title`/`description` 정제 완료·접두사 유지, `extra.raw_title` |
| 2 | 수집 → 매체명 | 수집기가 `publisher_name()` 에 넘기는 URL (`subreddit`/`is_self` 인자는 Reddit 수집기 제거 후 fixture 재현에만 쓰인다) | `publishers.publisher_name` | 국내는 `originallink`, 해외는 앵커용 URL. fixture publisher 값이 표에서 재현되는가 |
| 3 | 수집 → 랭킹·보강·출력 (URL 두 종류) | **해외 수집기** `collect_hn.py`·`collect_rss.py` 가 `urls.py` 로 채우는 `extra.normalized_url`/`anchor_url` | `rank_overseas` (병합 키, 없으면 ValueError), `enrich.py` (fetch 대상·`enrich_url`), `summarize.py` (`BriefItem.url`) | 병합은 `normalized_url` 로만, fetch·앵커·`enrich_url`·출력 URL 은 `anchor_url`. `www.`·후행 슬래시 유지 여부. 소비자마다 부재 처리가 다르다(예외 vs 원본 URL 강등) |
| 4 | 보강 → 요약 | `extra.enrich_status`/`enrich_text` | `summarize` 의 입력 선택·조건부 지시 | **요약 입력** 우선순위 `enrich_text` → `description` → 제목뿐(+`TITLE_ONLY_INSTRUCTION`). 실패 시 `enrich_text` 키 **부재**를 소비자가 `.get` 으로 다루는가 |
| 5 | 요약 → 렌더 | `BriefItem.summary_lines` (0/1/2개), `summary_status` | `render_notion.render_item`, SPEC 4절 예시 | 2문장/1문장/생략 세 경로. **fallback 원천 순서는 입력 순서와 반대**: `description` → `enrich_text` → 생략 (7절: `description` 이 이미 요약문 형태). 문자열 = `원천[:120].rstrip() + " ⚠️ 자동 요약 실패"`. 40자 초과는 자르지 않고 경고 |
| 6 | Gemini 응답 → 파서 | `summarize.RESPONSE_SCHEMA` | 응답 매칭·형식 위반 처리 | `id` 로만 매칭(순서 무시), 없는 id → fallback, 3문장 이상 → 앞 2개, 0개 → fallback, JSON 파싱 실패 → 섹션 전체 fallback |
| 7 | 주차 → 멱등성 | `week.compute_week` 의 `week_key`/`week_label` | `notion.week_toggle_exists` 접두 비교, `render_notion.toggle_label` | 비교는 `week_key`("9월 1주") 접두, 라벨은 건수 포함. 월/연 경계·5주차 케이스(`week_meta.json`) |
| 8 | Notion → 카카오 | `append_week_toggle` 반환 `block_id` | `block_anchor_url` fallback, `kakao.send_to_me` 링크 | block_id None 이면 월 페이지 URL. 프래그먼트는 하이픈 없는 32자. 본문 ≤ 200자 |
| 9 | 조립 | `main.Services` 필드 | `build_services()`, `tests/test_main.py` 가짜 | 세 곳의 필드가 1:1. 새 해외 소스는 `overseas_collectors` dict |
| 10 | 환경 | `.github/workflows/weekly_brief.yml` `env:` | `config.REQUIRED`, SPEC 12절 표 | 이름 일치. 선택 항목(`KAKAO_CLIENT_SECRET`, `GH_PAT`)은 REQUIRED 에 없어야 |
| 11 | fixture ↔ 근거 | `tests/fixtures/*.json` | `README.md` 계산 근거표, `check_fixtures.SCHEMA_FILES` | 점수·순위·건수·`enrich_*` 상태표가 JSON 과 일치 |
| 12 | 부분 발행 | `main.run` 의 0건 분기 | `render_week_toggle`, `kakao.build_message_text` | 한쪽 0건 → 헤더 유지 + `(해당 없음)`, 양쪽 0건 → 토글 없음·`nothing_to_publish`. 건수 표기가 실제 건수 |

## 실측 출력 검토 (dry-run)

`render_brief_text` 출력을 SPEC 4절 예시와 **글자 단위**로 대조한다:

- 섹션 헤더 `### 국내` / `### 해외`, 항목 `**N. 제목**`, 요약 줄 들여쓰기, 마지막 줄 `매체 · MM/DD`
- 국내 제목에 `[단독]` 류 접두사가 남아 있으면 FAIL (4절 전처리). 해외 제목은 영문 원문 그대로
- 요약 줄이 fallback 이면 말미 표식, 요약 줄이 없으면 제목+출처만 (3순위)
- 해외 앵커가 `www.`·후행 슬래시를 유지하는가 (`anchor_url`), `utm_*` 은 없는가
- 건수: 국내 ≤ 5, 해외 ≤ 5. 미달이면 왜인지 (수집 0건? 클러스터 크기 2 미만? 예비 풀 소진?) — 로그의 `collected`/`ranked` 줄로 판단
- `--no-llm` 이면 전원 fallback 이 정상이다. `summary: gemini 0` 을 결함으로 적지 않는다

## 리포트

`/home/robot/tech_news/_workspace/{NN}_pipeline-qa_report.md`. 형식은 에이전트 정의(`.claude/agents/pipeline-qa.md`)에.
핵심 규칙: 판정은 PASS / FAIL / 미검증. 못 본 것을 PASS 로 적지 않는다. FAIL 마다 `파일:라인`, 현재, 기대, SPEC 절.

## 하지 않는 것

- 테스트를 완화하거나 fixture 를 구현에 맞춰 고쳐서 통과시키기. fixture 가 틀렸다는 판단은 SPEC 근거가 있을 때만, README 근거표와 함께
- 코드 직접 수정 — 수정 요청을 engineer 에게. 진단과 수정이 분리돼야 "왜"가 남는다
- `python3 -m src.main` (dry-run 없이) 실행 — 실제 발행된다
- SPEC 이 모호한 것을 스스로 판정 — guardian 에게 넘긴다
