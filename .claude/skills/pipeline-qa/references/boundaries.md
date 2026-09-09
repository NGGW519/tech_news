# 경계면 상세 — 함수·함정·확인 방법

SKILL.md 경계면 표의 각 행을 실제 코드 위치와 fixture 가 심어 둔 함정으로 풀어 쓴 것. 번호는 표와 같다.

## 1. 수집 → 계약 (`RawArticle`)

- 생산자: `collect_naver.collect_domestic`, `collect_hn.collect_hn`, `collect_rss.collect_rss` 안의 `RawArticle(...)` 생성부
- 소비자: `schema.RawArticle` 필드 주석, `rank_*` 가 읽는 필드
- 확인:
  - `article_id`: `naver:<sha1(originallink)[:12]>` (URL 문자열 그대로, 정규화 전), `hn:<objectID>`, `rss:<피드키>:<슬러그>`. `originallink` 없으면 `link`
  - `metrics`: 국내 전 필드 `None`. HN 은 `points`/`comments`, `upvotes=None`. **None 과 0 을 섞지 않는다** — min-max 정규화에서 0 은 "최하위", None 은 "신호 없음 → 예비 풀"
  - `published_at`: `ensure_kst` 를 통과한 tz-aware. HN `created_at_i` 는 epoch UTC
  - `title`/`description`: `<b>`·엔티티 정제 완료, `[단독]` 접두사는 **유지** (제거는 랭킹에서). 원문은 `extra.raw_title`
  - `query`: 국내는 키워드, 해외는 서브레딧/피드 이름
- 함정 (fixture): 네이버 `[포토]` 접두사 노이즈 기사, 같은 기사가 두 키워드에 중복 등장 (키워드 간 중복 제거)

## 2. 수집 → 매체명

- 생산자: 수집기의 `publisher_name(url)` 호출 (`collect_naver` 는 `originallink`, `collect_hn`/`collect_rss` 는 앵커용 URL)
- 소비자: `publishers.publisher_name` — 특례(arXiv, Reddit self-post) → 표 → TLD 제거 fallback
- 확인: 국내는 `originallink` 도메인, 해외는 **앵커용 URL** 도메인 (링크 글은 링크 대상 도메인). `check_fixtures.py` [9] 가 raw 풀 전체(15건)로 재현 검사
- Reddit: 수집기는 제거됐다 (`bbd2e80`). `subreddit=`/`is_self=` 인자와 self-post 특례는 fixture 의 `reddit:*` 항목 재현에만 쓰인다. SPEC 6절 "Reddit 을 뺀 이유"가 fixture·`SourceKind.REDDIT` 유지를 명시 — 결함 아님
- 함정: `news.mt.co.kr` 의 등록 도메인은 `mt.co.kr` (`MULTI_LABEL_SUFFIXES`). 낯선 소문자 매체명이 출력에 보이면 표 추가가 정상 운영 절차 (SPEC 6절)

## 3. 수집 → 랭킹·보강·출력 (URL 두 종류)

- 생산자: **해외 수집기** — `collect_hn.py` (`normalized_url`/`anchor_url` 을 `extra` 에 넣는 곳), `collect_rss.py` (같은 위치). 둘 다 `urls.normalize_for_compare` / `urls.anchor_url` 을 쓴다. `rank_overseas` 는 **읽기만** 한다
- 소비자 (셋, 부재 처리가 다르다):
  - `rank_overseas` — 병합 키로 `extra["normalized_url"]` 직접 접근. 없으면 **ValueError** ("해외 수집기는 비교용 정규화 URL 을 반드시 채워야 한다")
  - `enrich.enrich_article` — `extra.get("anchor_url") or article.url` 로 fetch 대상 결정, `enrich_url` 에 기록
  - `summarize` (BriefItem 조립) — `extra.get("anchor_url", a.url)` 로 출력 앵커. 없으면 **조용히 원본 URL 로 강등** (rank 의 예외와 비대칭 — 새 해외 수집기가 `anchor_url` 만 빠뜨리면 utm 이 붙은 앵커가 나간다)
- 확인: 비교용 = 소문자 + `www.` 제거 + 트래킹 제거 + 후행 슬래시 제거. 앵커용 = 트래킹만 제거. 새 해외 수집기는 **두 키를 모두** 채우는지
- 함정 (fixture): `hn:41240355` 앵커는 `https://www.1x.tech/...` (www 유지), `reddit:1mqk4pz` 앵커는 utm 두 개만 지워짐. HN+Reddit 같은 TechCrunch URL 병합, RSS+HN 후행 슬래시 차이 병합. 국내에는 두 키 모두 **없음**

## 4. 보강 → 요약 (입력 선택)

- 생산자: `enrich.enrich_article` — 성공 시 `enrich_status="success"` + `enrich_text` + `enrich_url`, 실패 시 `enrich_status="failed"` + `enrich_url` 만 (**`enrich_text` 키 자체가 없음**), 국내는 세 키 모두 없음
- 소비자: `summarize` 의 입력 선택 — `enrich_text` → `description` → 제목뿐. 제목뿐이면 프롬프트에 `TITLE_ONLY_INSTRUCTION` 추가
- 확인: 소비자가 `extra.get("enrich_text")` 로 부재를 다루는가. `MIN_CHARS`(200) 미만은 실패 처리 (쿠키 배너)
- 함정 (fixture): 해외 4위 `hn:41253117` 은 failed + description 없음 → 제목뿐 경로. 5위 `reddit:1mq0a4b` 는 success 지만 `enrich_text == description` (소득 없음, 정상)

## 5. 요약 → 렌더

- 생산자: `summarize.summarize_section` → `BriefItem.summary_lines` (gemini: 1~2개 / fallback: 1개 또는 0개), `summary_status`
- 소비자: `render_notion.render_item`, `render_item_text`, SPEC 4절 출력 예시, `tests/fixtures/README.md` "렌더링 기대 출력"
- 확인: **fallback 원천 순서는 요약 입력 순서(#4)와 반대다** — `description` → `enrich_text` → 생략. `description` 이 이미 요약문 형태라 먼저다 (SPEC 7절). 문자열 = `원천[:120].rstrip() + " ⚠️ 자동 요약 실패"` (한 칸). 1·2순위는 1개 튜플, 3순위는 빈 튜플. `summary_status` 는 세 순위 모두 `FALLBACK_DESCRIPTION`. #4 를 읽고 여기로 오면 순서를 뒤집어 읽기 쉽다 — 정상 코드를 FAIL 로 적지 않도록 SPEC 7절 fallback 표를 직접 본다
- 함정: 40자 초과는 자르지 않고 경고만 (7절). `lines` 3개 이상이면 앞 2개. fixture 의 해외 4·5위가 SPEC 4절 "요약 실패 시 출력" 을 글자 그대로 재현

## 6. Gemini 응답 → 파서

- 생산자: `summarize.RESPONSE_SCHEMA` (`{"items":[{"id","lines"}]}`), `generationConfig.responseMimeType/responseSchema`
- 소비자: 응답을 `id` 로 원 기사에 되붙이는 코드
- 확인: 순서 무시·`id` 매칭, 요청 id 가 응답에 없으면 그 항목 fallback, 모르는 id 는 버림, JSON 파싱 실패(펜스·빈 문자열)는 예외 → **섹션 전체** fallback, 개별 재시도 없음
- 함정: `summary_cases/*.json` 은 문자열 일치가 아니라 규칙 검증 기준 (입력 선택·status·문장 수·앵커는 단언 가능)

## 7. 주차 → 멱등성

- 생산자: `week.compute_week` — 목요일 앵커, `week_key`="9월 1주", `week_label`="9월 1주 (08/31~09/06)", `month_page_title`="2026-09"
- 소비자: `notion.week_toggle_exists(month_page_id, week_key)` 접두 비교, `render_notion.toggle_label` (라벨 + ` · 국내 N / 해외 M`)
- 확인: 비교에 `week_label` 이나 건수가 섞이면 재실행 시 토글이 두 개 (9절). `iter_children` 페이지네이션(`PAGE_SIZE` 100)
- 함정 (fixture): `week_meta.json` 의 월/연 경계·5주차 케이스. 비월요일 `--date` 는 그 주 월요일로 스냅

## 8. 렌더 → Notion (알림)

- 생산자: `render_week_toggle` 이 만드는 토글 `rich_text` — **조각 2개**
- 소비자: `notion.append_week_toggle` (쓰기), `notion.week_toggle_exists` (읽기·멱등성)
- 확인: **`rich_text[0]` 은 라벨 텍스트, mention 은 그 뒤** (SPEC 5·9절 계약). `rich_text[0].plain_text` 가
  `week_key` 로 시작해야 멱등성이 선다. mention 은 `{"type":"mention","mention":{"type":"user","user":{"object":"user","id":…}}}`
  이며 `id` 는 `NOTION_USER_ID`. 건수는 실제 발행 건수이고 그 라벨이 곧 알림 문구 (SPEC 8절)
- 함정 1: **mention 을 `rich_text[0]` 에 넣으면 매주 토글이 중복 생성된다.** 접두 일치가 사용자 이름을 보게 된다
- 함정 2: 통합에 「이메일 주소를 제외한 사용자 정보 읽기」 권한이 없으면 append 가 `400 validation_error`
  ("Could not find user with ID …"). **증상이 알림 누락이 아니라 그 주 미발행**이다 (SPEC 8절 "통합 권한")
- 함정 3: Notion 은 `_guard` 밖 — 실패하면 프로세스가 죽고 `last_run.txt` 가 안 써진다.
  알림이 토글과 한 몸이라 **발행과 알림이 함께 실패**한다. 토글이 없으므로 `workflow_dispatch` 로 회복된다
- `block_anchor_url` 은 **로그 전용**이다 (SPEC 8절). None 이면 `page_url`, 프래그먼트는 하이픈 제거 32자 —
  `logs/last_run.txt` 의 `notion:` 필드가 유일한 소비자이며 알림 경로에는 URL 이 쓰이지 않는다

## 9. 조립 (`Services`)

- `main.Services` 필드 ↔ `build_services()` ↔ `tests/test_main.py` 의 `FakeNotion`/`Recorder`/`_fake_call`/`_fake_enrich`
- 확인: 필드 추가 시 세 곳. 해외 소스는 `overseas_collectors` dict 에 이름 키로 — 이름이 `failures` 의 `collect_{name}` 이 된다
- 함정: `summarize_call` 은 `--no-llm` 이면 예외를 던지는 함수로 바뀐다 (전원 fallback)

## 10. 환경 변수

- `.github/workflows/weekly_brief.yml` `env:` ↔ `config.REQUIRED`(**6개**) ↔ SPEC 12절 표
- 확인: 이름 오타는 Actions 에서 `환경 변수 누락:` SystemExit 로만 드러난다. v1.6 기준 필수 6개는
  `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`·`GEMINI_API_KEY`·`NOTION_TOKEN`·`NOTION_ROOT_PAGE_ID`·`NOTION_USER_ID`.
  **선택 항목이 하나도 없다** — 카카오 3키·`GH_PAT`·`KAKAO_NEW_REFRESH_TOKEN_FILE` 이 남아 있으면 drift
- 확인: `NOTION_TOKEN` 은 값뿐 아니라 **권한**도 맞아야 한다 — 콘텐츠 읽기·삽입 + 「이메일 주소를 제외한 사용자 정보 읽기」 (SPEC 12절)

## 11. fixture ↔ 근거표

- `tests/fixtures/README.md` 의 해외 랭킹 계산 근거표(min-max 값, 합산, 동점 처리), 본문 보강 상태표, 앵커 URL 표 ↔ JSON 값
- 확인: `check_fixtures.py` 가 구조·규약을 보고, 수치(점수 5자리)는 `test_rank_overseas` 가 본다. README 표를 고치면 둘 다 다시 돈다
- 함정: 2·3위 1.00000 동점은 min-max 특성상 상시 발생 — 게시 시각 이른 순으로 깬다. 예비 풀 항목은 본 랭킹 파일과 합치면 안 된다

## 12. 부분 발행·0건

- `main.run`: 양쪽 0건 → `nothing_to_publish`, 토글 없음, 로그는 씀. 한쪽 0건 → 토글 생성, `(해당 없음)`
- `render_week_toggle`: 헤더 유지. `toggle_label`: `국내 0 / 해외 5`
- 확인: `test_main` 이 부분 발행(국내 3)을 재현. 0건 케이스는 `test_render_notion`
- 함정: 양쪽 0건에 빈 토글을 만들면 멱등성이 그 주를 영구히 막는다 (SPEC 2절)
