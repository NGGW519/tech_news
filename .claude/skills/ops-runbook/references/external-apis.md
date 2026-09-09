# 외부 API 사양 점검표 (SPEC 11절)

SPEC 이 "기억에 의존하지 말고 최신 공식 문서를 확인할 것"이라 한 항목의 현재 기록값과 점검 방법.
**기록값은 SPEC 이 원본**이다 — 이 표가 SPEC 과 다르면 SPEC 을 따르고 이 표를 고친다.
점검 결과는 항목마다 확인일·출처 URL·변경 유무를 적고, 변경이 있으면 guardian(SPEC 갱신)과 engineer(코드)에게 넘긴다.

| # | 항목 | SPEC | 현재 기록값 (확인일) | 어디서 확인 | 판정 규칙 | 바뀌면 고칠 곳 |
|---|------|------|--------------------|-----------|----------|---------------|
| 1 | Gemini 모델 ID | 7절 "모델 ID" | `gemini-3.8-flash` (2026-09-08). 대안 `gemini-3.7-flash` | `models` 엔드포인트 실조회(`generateContent` 지원 목록) + 공식 models·deprecations·pricing 문서 | (1) ID 에 `flash` 포함 (2) `preview`·`lite`·`image`·`tts`·`omni`·`live`·`transcribe` 제외 (3) 공식 문서가 stable 로 표시한 최신. `*-latest` 별칭 금지 | `summarize.GEMINI_MODEL`, SPEC 7절 표·확인일, 단가 |
| 2 | Gemini JSON 강제 옵션명 | 7절 | `generationConfig.responseMimeType` = `application/json` + `responseSchema` (2026-09-08) | 공식 structured output 문서 | 옵션 키 이름이 그대로인가. `generateContent` 가 deprecated 됐는가 (Interactions API 로 대체 권고만이면 유지) | `summarize.RESPONSE_SCHEMA` 주변, SPEC 7절 |
| 3 | Gemini 단가 | 7·10절 | 입력 $0.75 / 출력 $3.75 per 1M (2026-12-31 까지), 2027-01-01 부터 $1.50 / $7.50 | pricing 문서 | 자릿수가 바뀌는가 (월 수십 원 규모) | SPEC 7·10절 |
| 4 | Notion API 버전·엔드포인트 | 5·11절 | `Notion-Version: 2022-06-28`, `blocks.children.list/append`, `pages` (코드 `notion.NOTION_VERSION`) | Notion API 변경 로그·reference | 버전이 sunset 예고됐는가. 블록 children 페이지네이션(`start_cursor`) 형식 변경 | `notion.py`, SPEC 5·9절 예시 |
| 5 | Notion 블록 앵커 URL | 8절 | `https://www.notion.so/<page_id>#<하이픈 없는 block_id 32자>` (2026-09-09). **로그 전용** — 알림 경로에는 쓰지 않는다 | `logs/last_run.txt` 의 `notion:` 값을 브라우저에서 열어 확인 | 프래그먼트로 블록 위치에 도달하는가 | `notion.block_anchor_url`, SPEC 8절 |
| 6 | 통합 발 멘션의 푸시 동작 | 8절 | 통합(봇)이 만든 본문 멘션도 사람 멘션과 같이 **모바일 푸시를 낸다** (2026-09-09 실측). 폰·PC 어디든 Notion 이 열려 있으면 푸시 대신 인박스 뱃지 | **공식 문서에 없다 — 실측만이 근거.** 테스트 페이지에 `[text, mention(user)]` 블록 1개 append 후 폰 확인 (Notion 전부 닫은 상태로) | 푸시 배너가 오는가. 안 오면 8절 전체가 무효 → 대안 재검토 | SPEC 8·11절 |
| 7 | 멘션에 필요한 통합 권한 | 8·12절 | 사용자 기능 = 「이메일 주소를 제외한 사용자 정보 읽기」 이상 (콘솔 실확인 2026-09-09). 미설정 시 토글 append 가 `400 validation_error` | `notion.so/profile/integrations` › `tech_news` › 기능 › 사용자 기능 | 라벨 문구·단계 구성 변경. **증상이 알림 누락이 아니라 그 주 미발행**임에 주의 | SPEC 8·12절, README 설정 절 |
| 8 | Notion mention 객체 형식 | 5절 | `{"type":"mention","mention":{"type":"user","user":{"object":"user","id":…}}}` (2026-09-09 공식 문서) | Rich text 레퍼런스 | 키 이름·중첩 구조 변경 | `render_notion` 의 mention 헬퍼, SPEC 5절 표 |
| 9 | 사용자 ID 확보 경로 | 12절 | 권한 켜기 전 `GET /v1/users` 403, 켠 뒤 200. `type: person` 1 + `type: bot` 2 반환, person ID 가 루트 `created_by.id` 와 일치 (2026-09-09 실측) | `GET /v1/users` 실조회 | `person`/`bot` 판별 필드 변경. 값은 상수라 재조회 불필요 | SPEC 12절 |
| 10 | 네이버 검색 API 엔드포인트·헤더 | 6절 | NAVER API HUB `https://naverapihub.apigw.ntruss.com/search/v1/news`, 헤더 `X-NCP-APIGW-API-KEY-ID` / `X-NCP-APIGW-API-KEY` (2026-09-08). 개발자센터 키·URL 은 쓰지 않음 | API HUB 콘솔·문서 | URL·헤더·응답 필드(`originallink`, `pubDate`, `<b>` 태그) 변경. 유료 요금제 도입 여부 | `collect_naver.py` 상수, SPEC 6·10·12절 |
| 11 | 네이버 페이지네이션 상한 | 6·11절 | `display` 100, `start` 최대 1000 (`MAX_START`) | 문서 | 상한 변경 시 수집 폭 | `collect_naver.DISPLAY/MAX_START`, SPEC 6절 |
| 12 | HN Algolia | 6절 | `search_by_date`, `hitsPerPage` 100, 최대 10페이지(1000건) | hn.algolia.com API 문서 | 상한·필드(`points`, `num_comments`, `created_at_i`) 변경 | `collect_hn.py`, SPEC 6절 |
| 13 | arXiv export API | 6·11절 | 요청 간 3초, 429 시 15초 후 1회 재시도, 타임아웃 30초 (실측 2026-09-08) | arXiv API 이용 약관 | 간격·상한 변경 | `collect_rss.ARXIV_DELAY_SECONDS/RATE_LIMIT_RETRY_SECONDS/FEED_TIMEOUT` |
| 14 | 보조 RSS 피드 URL | 6절 | `collect_rss.DEFAULT_FEEDS` (DeepMind, arXiv cs.RO 등) | 각 피드 GET 200 + 항목 존재 | 피드 이동·폐쇄·형식(RSS 2.0 ↔ Atom) 변경 | `collect_rss.DEFAULT_FEEDS`, fixture `api_rss_*.xml` |
| 15 | GitHub Actions 60일 비활성화 | 9절 | 무료 계정 60일 무활동 시 schedule 중단. 로그 커밋으로 방지. `permissions: contents: write` 필요 | GitHub 문서 | 기간·조건 변경 | `weekly_brief.yml`, SPEC 9절 |
| 16 | GitHub Actions cron 지연 | 2절 | UTC 일 23:10 = KST 월 08:10 (20분 당김) | 실행 이력의 `run_at` | 지연이 30분을 넘기는가 | `weekly_brief.yml` cron |

## 점검 절차

1. 위 표 순서대로, 항목마다 WebFetch/WebSearch 로 **공식 문서**를 연다. 2차 출처(블로그·커뮤니티)는 "2차" 라고 표시
2. 실조회가 가능한 것(#1 `models` 엔드포인트, #14 피드 GET)은 실조회를 우선한다. 키가 필요한 조회는 `.env` 가 있을 때만, 값을 찍지 않고
3. 결과를 `_workspace/{NN}_ops-investigator_diagnosis.md` 에 표로: `# | 확인일 | 출처 URL | 변경 없음/있음 | 있으면 옛 값 → 새 값`
4. 변경 있음 → guardian 에게 절 번호와 함께 (SPEC 헤더 "확인 완료" 날짜 갱신 포함), 코드 상수 영향은 engineer 에게
5. 변경 없음도 확인일을 남긴다 — SPEC 11절의 "한 달 이상 뒤면 재확인" 기준점이 된다
