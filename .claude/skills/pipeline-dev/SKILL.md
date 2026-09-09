---
name: pipeline-dev
description: "tech-news-orchestrator 가 pipeline-engineer 에게 시키는 하위 절차 — 사용자 요청은 오케스트레이터가 먼저 받는다. 주간 테크 뉴스 브리핑 파이프라인 src/·tests/·.github/workflows/ 구현 규약: 모듈 맵(18개 모듈의 역할·SPEC 절·순수/네트워크·테스트·튜닝 상수), Services 주입·_guard 격리·KST·article_id/extra 키 계약, 금지 항목, 테스트 우선 변경 절차, dry-run 실측 명령과 비용, fixture 갱신 규칙, 커밋 규약(푸시 금지). 수집기·랭킹·보강·요약·Notion·카카오·진입점·워크플로우 코드를 고치거나 키워드·임계값·타임아웃·publisher 표를 튜닝하는 에이전트는 이 스킬을 읽는다. SPEC 규칙 자체를 바꾸는 일은 spec-change 가 먼저다."
---

# 파이프라인 구현 규약

`src/` 18개 모듈 약 2,400줄(테스트·fixture 별도), 실행 의존성 하나(`trafilatura`)짜리 작은 코드베이스다. 작다는 것이 곧 규약이 느슨하다는
뜻은 아니다 — 모든 모듈이 `src/schema.py` 계약과 SPEC 절 번호로 서로를 가리키고 있어, 한 곳의 키 이름을
바꾸면 조용히 다른 곳이 어긋난다. 이 문서는 그 연결을 끊지 않고 고치는 방법이다.

## 환경

| 항목 | 값 | 비고 |
|------|-----|------|
| 인터프리터 | `python3` (3.10) | `python` 명령은 **없다** |
| 테스트 | `python3 -m pytest -q` | 기준선 216 passed (2026-09-09). `pytest.ini` 가 ROS 2 플러그인을 `-p no:` 로 끈다 — 지우지 말 것 |
| 의존성 | `pip install -r requirements-dev.txt` | 실행 의존성은 `trafilatura` 뿐. 나머지는 표준 라이브러리 |
| 실행 | `python3 -m src.main [--dry-run] [--no-llm] [--date YYYY-MM-DD]` | 아래 "실측" 참조 |
| 자격 증명 | 로컬 `.env` (gitignore) / Actions Secrets | `config.Settings.from_env()` 가 `REQUIRED` 7개를 검사 |

## 모듈 맵

| 모듈 | 역할 | SPEC | 성격 | 테스트 | 튜닝 상수 |
|------|------|------|------|--------|----------|
| `schema.py` | 모듈 간 데이터 계약 (`RawArticle`→`RankedArticle`→`BriefItem`→`WeeklyBrief`, `WeekMeta`) | 3·5절 | 순수 | `test_import_smoke` + 모든 fixture | — (계약 고정점, 값 추가 금지) |
| `week.py` | 주차 계산 (목요일 앵커, `week_key`/`week_label`) | 5절 | 순수 | `test_week` | `WINDOW_DAYS`, `ANCHOR_OFFSET_DAYS` |
| `urls.py` | 비교용/앵커용 URL 정규화 | 4·6절 | 순수 | `test_urls` | `TRACKING_PREFIXES`, `TRACKING_KEYS` |
| `publishers.py` | 도메인→매체명 표 + 조회 (데이터 전용) | 4·6절 | 순수 | `test_publishers` | `DOMAIN_TO_NAME`, `MULTI_LABEL_SUFFIXES` |
| `text.py` | HTML 태그·엔티티 정제 | 6절 | 순수 | (수집기 테스트 경유) | — |
| `collect_naver.py` | 국내 수집 (NAVER API HUB) | 6절 | 네트워크 + 파서 | `test_collect_naver` | `DEFAULT_QUERIES`, `DISPLAY`, `MAX_START`, `HTTP_TIMEOUT` |
| `collect_hn.py` | HN Algolia 수집 + 제목 키워드 필터 | 6절 | 네트워크 + 파서 | `test_collect_hn` | `DEFAULT_QUERIES`, `TITLE_KEYWORDS`, `MAX_PAGES` |
| `collect_rss.py` | 보조 RSS/Atom (DeepMind, arXiv 등) | 6절 | 네트워크 + 파서 | `test_collect_rss` | `DEFAULT_FEEDS`, `FEED_TIMEOUT`, `ARXIV_DELAY_SECONDS`, `RATE_LIMIT_RETRY_SECONDS` |
| `rank_domestic.py` | 접두사 제거 → bigram 자카드 클러스터링 → 커버리지 랭킹 | 4·6절 | 순수 | `test_rank_domestic` | `JACCARD_THRESHOLD`(0.35, 튜닝 대상), `MIN_CLUSTER_SIZE`, `TITLE_PREFIX` |
| `rank_overseas.py` | 소스 내 합성 → min-max → URL 병합 → 예비 풀 | 6절 | 순수 | `test_rank_overseas` | `HN_POINTS_WEIGHT`, `HN_COMMENTS_WEIGHT`, `TOP_N` |
| `enrich.py` | 해외 상위 5건 원문 fetch → 앞 1500자 (`extra.enrich_*`) | 6.5절 | 네트워크 (주입 가능) | `test_enrich` | `ENRICH_TIMEOUT`, `MAX_CHARS`, `MIN_CHARS` |
| `summarize.py` | Gemini 배치 요약 + 2단 fallback | 7절 | 네트워크 (`call` 주입) | `test_summarize` | `GEMINI_MODEL`, `MAX_CHARS_PER_SENTENCE`, `FALLBACK_CHARS` |
| `render_notion.py` | 주차 토글 블록 + 텍스트 렌더 | 4·5절 | 순수 | `test_render_notion` | `EMPTY_SECTION_TEXT`, `SOURCE_COLOR` |
| `notion.py` | 월 페이지·토글 존재 확인·append·앵커 URL | 5·8·9절 | 네트워크 | `test_notion_kakao` | `NOTION_VERSION`, `PAGE_SIZE` |
| `kakao.py` | 토큰 갱신 + 나에게 보내기 | 8절 | 네트워크 (`post_form` 주입) | `test_notion_kakao` | `TEXT_LIMIT`(200), `BUTTON_TITLE` |
| `http.py` | 공용 HTTP (GET JSON/텍스트, POST form) | — | 네트워크 | — | `DEFAULT_TIMEOUT`, `USER_AGENT` |
| `config.py` | `.env`/Secrets → `Settings` | 12절 | 순수 | — | `REQUIRED` |
| `main.py` | 진입점. `Services` 주입, `_guard` 격리, 실행 로그 | 2·3·9절 | 조립 | `test_main` (가짜 서비스로 끝까지) | — |
| `scripts/kakao_refresh_token.py` | 최초 발급·재발급·시험 발송 | 8·12절 | 대화형 | — | — |

파이프라인 순서(`main.run`, 3절 고정): 수집(국내 ∥ 해외 소스별) → 랭킹 → 예비 풀 보충 → 보강(해외) → 요약(섹션당 1회) → 멱등성 → Notion → 카카오 → 로그.

## 구현 규약 — 왜 그런지와 함께

**네트워크와 순수 로직을 섞지 않는다** (3절 유의점 4). 랭킹·주차·렌더링은 API 키 없이 fixture 만으로 테스트돼야 한다.
새 외부 호출은 (1) `src/http.py` 함수를 쓰고, (2) 호출하는 함수의 키워드 인자로 주입 가능하게 만든다
(`enrich_ranked(..., fetch=)`, `refresh_access_token(..., post_form=)` 이 그 패턴이다). 그래야 테스트가 가짜를 꽂는다.

**외부 서비스는 `main.Services` 로만 들어온다.** 새 서비스를 붙이면 세 곳을 같이 고친다: `Services` 필드,
`build_services()`, `tests/test_main.py` 의 가짜. 하나라도 빠지면 `test_main` 이 실제 네트워크를 타거나 죽는다.

**단계 실패는 `_guard` 로 격리한다** (2절 부분 발행). 수집기 하나가 죽어도 그 주를 잃지 않기 위해서다.
해외 수집기는 `overseas_collectors` dict 에 소스별로 넣어 각각 격리된다 — 새 해외 소스는 여기에 한 줄 추가하면
된다. 단, 랭킹·요약·렌더는 순수 로직이라 감싸지 않는다. 거기서 예외가 나면 그건 버그다.

**시각은 전부 tz-aware KST** (`schema.KST`, `now_kst()`, `ensure_kst()`). Actions 런너는 UTC 라 `date.today()` 는
틀린 날짜를 준다. HN 의 `created_at_i`(epoch) 같은 값은 수집 단계에서 변환해 담는다.

**`article_id` 와 `extra` 키는 계약이다.** `naver:<sha1 12자>` / `hn:<objectID>` / `rss:<피드키>:<슬러그>` 형식 (`reddit:<id>` 는 소스가 제거됐지만 fixture 에 남아 검사기가 허용한다),
해외의 `extra.normalized_url`(비교용)·`anchor_url`(앵커용), 보강의 `enrich_status`/`enrich_text`/`enrich_url`.
전체 목록은 `tests/fixtures/README.md` "고정된 규약". 새 소스는 접두사를 SPEC 6절 표에 먼저 등록한다(설계 변경).

**상수는 모듈 상단에, SPEC 절 주석과 함께.** 튜닝 대상은 "운영 중 튜닝 대상"처럼 표시하고 확인일·실측 근거를
남긴다 (`JACCARD_THRESHOLD`, `FEED_TIMEOUT` 주석 참조). 값을 코드 중간에 박지 않는다.

**로그는 한국어 + SPEC 절 인용.** `log.warning("… (SPEC 9절 알려진 한계)")` 스타일. 토큰·키·`.env` 값은 어떤
로그에도 찍지 않는다. 오류 응답 본문을 찍을 때는 헤더·인증 정보가 섞여 있지 않은지 본다.

**의존성을 늘리지 않는다.** 등록 도메인 판정에 `tldextract` 를 안 쓰고 `MULTI_LABEL_SUFFIXES` 상수를 둔 것이
이 프로젝트의 태도다. 새 패키지가 필요해 보이면 표준 라이브러리로 되는지 먼저 확인하고, 안 되면 리더에게 묻는다.

## 하지 않는 것

SPEC 이 고정한 결정은 `spec-change` 스킬 2절 표에 있다. 코드 관점에서 특히 자주 유혹받는 것:

- 멱등성 체크를 Gemini 앞으로 옮기기 (3절 유의점 3) — 비용 절감처럼 보이지만 금지
- 카카오 실패 대비 상태 파일·재시도 추가 (9절) — 알려진 한계로 감수하기로 했다
- `SummaryStatus` 에 fallback 원천 값 추가 (7절) — `summary_lines` 길이로 재구성 가능
- `publishers.py` 에 국내/해외 분기 로직 넣기 (6절)
- 40자 초과 문장 자르기 (7절) — 경고만
- `gemini-flash-latest` 류 별칭 (7절)
- 지나가다 본 다른 문제 고치기 — changes 파일 "남은 의문"에 적고 넘어간다

## 변경 절차

incremental QA 가 실제로 돌려면 검증자 알림이 **모듈마다** 나가야 한다. 그래서 4~5 가 루프다.

1. `_workspace/{NN}_spec-guardian_impact.md` 가 있으면 읽는다. "닿는 절" 밖은 건드리지 않는다. `ToolSearch("select:SendMessage")` 로 통신 도구를 미리 받는다
2. **테스트부터** — 순수 로직은 fixture 로, 네트워크는 가짜 주입으로. 기존 테스트 파일에 케이스를 더한다
3. 모듈 하나 구현. 상수·주석·로그 규약 준수
4. 그 모듈의 테스트만: `python3 -m pytest -q tests/test_{module}.py`
5. `SendMessage(to: "pipeline-qa")` — 바뀐 파일, 검증 요청 경계면, 테스트 결과. **여기서 전체 완성을 기다리지 않는다.** 다음 모듈이 있으면 3 으로
6. 모든 모듈 끝: `python3 -m pytest -q` — passed 수가 기준선 이상인지
7. `python3 .claude/skills/pipeline-qa/scripts/check_fixtures.py` — fixture 를 건드렸으면 필수
8. 실측 (아래 표) — 수집·랭킹 튜닝은 실제 데이터로 근거를 남긴다
9. `/home/robot/tech_news/_workspace/{NN}_pipeline-engineer_changes.md` 작성 (형식은 에이전트 정의) → `SendMessage(to: "pipeline-qa")` 로 최종 검증 요청
10. qa 의 수정 요청을 반영 (최대 3라운드) → PASS 후 커밋

## 실측

| 명령 | 하는 일 | 비용·부작용 |
|------|--------|-----------|
| `python3 -m src.main --dry-run --no-llm --date 2026-09-08` | 수집·랭킹·보강까지 실제로 돌고 요약은 전부 fallback. 결과를 stdout 에 렌더 | 네이버·HN·RSS·원문 사이트를 **실제 호출** (네이버 일 한도 소모, arXiv 3초 간격). Gemini 비용 0, Notion·카카오 안 씀, `logs/last_run.txt` 안 씀. **`.env` 에 `config.REQUIRED` 7개 키가 전부 있어야 뜬다** — dry-run 이라도 `Settings.from_env()` 를 통과해야 한다 |
| `python3 -m src.main --dry-run` | 위 + Gemini 요약 | Gemini 소액 과금 |
| `python3 -m src.main` | **실제 발행** | Notion 에 토글이 생기고 카톡이 간다. 멱등성 때문에 그 주는 다시 못 돌린다. **로컬에서 돌리지 않는다** |

`--date` 는 비월요일이면 그 주 월요일로 스냅된다(`week.current_week`). 지난주를 재현하려면 지난 월요일 날짜를 준다.
실측 결과(건수, 상위 5건 제목, 이상 징후)는 changes 파일과 커밋 메시지에 "실측 반영:" 으로 남긴다.

## fixture 를 바꿀 때

fixture 는 2026-08-17 실행(8월 2주, 국내 3/해외 5) 한 주치로 통일돼 있고 `README.md` 에 계산 근거표가 있다.
JSON 을 고치면 (1) README 의 해당 표·"고정된 규약", (2) `check_fixtures.py` 의 `SCHEMA_FILES` 건수를 같이 고친다.
새 케이스는 기존 12건 풀에 섞지 말고 `summary_cases/` 처럼 독립 케이스로 둔다 — 섞으면 랭킹 근거표가 어긋난다.

## 커밋

기존 `git log` 스타일 — 한국어 요약형 한 줄, 필요하면 괄호로 근거:

```
실측 튜닝: 네이버 키워드에서 ROS 제거, publisher 표 주요 매체 확장
Reddit 소스 제거 — Data API 가 모더레이션 용도 외 신규 승인을 막음
ff44fd4 네이버 오류 본문·힌트 노출, arXiv 429 1회 재시도, max_results 100
```

- **커밋까지만. 푸시는 사용자가 직접 한다**
- `logs/last_run.txt` 는 Actions 봇이 커밋하는 파일이다. 로컬 실제 실행으로 바뀌었으면 커밋에 섞지 않는다 (`--dry-run` 은 안 건드린다)
- `.env`, `_workspace/` 는 gitignore 대상 — 스테이징에 올라오면 뭔가 잘못된 것
