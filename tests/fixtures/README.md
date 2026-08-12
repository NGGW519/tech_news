# tests/fixtures

API 키 없이 순수 로직(클러스터링·랭킹·주차 계산·렌더링)을 단위 테스트하기 위한 고정 입력이다.
(SPEC 3절 유의점 4 — 네트워크 호출부와 순수 로직 분리)

모든 파일은 **2026년 8월 2주** 한 주치로 통일돼 있다.
(SPEC v1.3 기준. 이전 판에서 "미정"이던 항목이 전부 확정되어 반영돼 있다 — 맨 아래 참조)

예외는 `summary_cases/` 뿐이다. 요약 단계만 검증하는 **독립 케이스**이며 위 주차 풀에
속하지 않는다 (아래 "요약 케이스" 참조).

| | 값 |
|---|---|
| 실행일 | 2026-08-17 (월) |
| 수집 창 | 2026-08-10 ~ 2026-08-16 |
| 앵커(목) | 2026-08-13 → `week_key` = **8월 2주** |
| 결과 | **국내 3 / 해외 5** — 국내가 5건에 미달하는 **부분 발행 케이스**다 (SPEC 2절) |

토글에 적히는 최종 텍스트는 `8월 2주 (08/10~08/16) · 국내 3 / 해외 5` 이고,
멱등성 비교는 `8월 2주` 접두 일치로만 한다 (SPEC 5·9절).

## 파일

### 수집기용 — API 응답 흉내

각 파일은 **실제 API 응답 1개 그대로**다. 감싸는 층이 없으므로 수집기가 이 파일로
파싱을 검증하면 실제 호출에서도 같은 코드가 동작한다.

| 파일 | 대응 호출 |
|---|---|
| `api_naver_news_humanoid.json` | 네이버 검색 API(news) `query=휴머노이드` — 6건 |
| `api_naver_news_robot.json` | `query=로봇` — 6건 |
| `api_naver_news_autonomous_driving.json` | `query=자율주행` — 1건 |
| `api_naver_news_ros.json` | `query=ROS` — 1건 |
| `api_hn_algolia.json` | HN Algolia `search_by_date` — 5 hits |
| `api_reddit_top_week.json` | Reddit `top?t=week` 리스팅 — 5 children |
| `api_rss_deepmind.xml` | DeepMind 블로그 RSS 2.0 — 1 item |
| `api_rss_arxiv_cs_ro.xml` | arXiv cs.RO Atom — 1 entry |

- 키워드는 파일명으로만 구분한다. 실제 응답에 질의어 필드가 없기 때문이다.
- 네이버 `title`·`description` 의 `<b>` 태그와 HTML 엔티티(`&quot;`, `&apos;`)는 실제 그대로다.
- HN `created_at` 은 UTC, `created_at_i` 는 epoch. Reddit `created_utc` 는 epoch. 둘 다 **KST 아님**.
- HN 링크 글은 `story_text: null`, Reddit 링크 글은 `selftext: ""` — **원문 본문을 주지 않는다.**

네이버 4개 파일을 합치면 항목 14개 / 고유 12건이며, 클러스터링까지 검증되게 짜여 있다:

- 삼성 AP 사건 4건 · 아틀라스 사건 3건 · LG Q9 사건 2건 · 무관 기사 3건 → 클러스터 크기 **4 / 3 / 2**
- 삼성(전자신문)과 아틀라스(연합뉴스)는 `휴머노이드`·`로봇` 두 파일에 **중복 등장** → 키워드 간 중복 제거 검증용
- 접두사는 `[단독]`(대표), `[속보]`(대표), `[포토]`(노이즈) 세 종류

### 스키마별 — `src/schema.py` 타입에 1:1 대응

| 파일 | 타입 | 건수 |
|---|---|---|
| `raw_articles_domestic.json` | `list[RawArticle]` | 3 (대표 기사) |
| `raw_articles_overseas.json` | `list[RawArticle]` | **12 (병합 전 수집 풀 전체)** |
| `ranked_articles_domestic.json` | `list[RankedArticle]` | 3 |
| `ranked_articles_overseas.json` | `list[RankedArticle]` | 5 (**본문 보강 전**) |
| `ranked_articles_overseas_reserve.json` | `list[RankedArticle]` | 1 (**예비 풀**) |
| `enriched_articles_overseas.json` | `list[RankedArticle]` | 5 (**본문 보강 후**) |
| `brief_items_domestic.json` | `list[BriefItem]` | 3 |
| `brief_items_overseas.json` | `list[BriefItem]` | 5 |
| `week_meta.json` | `list[{case, note, week, expected}]` | 4 케이스 |
| `summary_cases/*.json` | 요약 입력 → 기대 출력 (독립 케이스) | 3 파일 |

해외 랭킹 결과가 세 파일인 것은 SPEC 6.5절 **본문 보강**이 랭킹과 요약 사이에 끼기 때문이다.

```
ranked_articles_overseas.json     랭킹 직후 — extra 에 enrich_* 키가 없다
        ↓  src/enrich.py
enriched_articles_overseas.json   보강 후  — extra 에 enrich_* 키가 붙는다
        ↓  Gemini 요약
brief_items_overseas.json
```

두 파일의 차이는 **`article.extra` 의 `enrich_*` 키뿐**이다. 그 외는 완전히 같다.
`ranked_articles_overseas_reserve.json` 은 위 흐름에 타지 않는다 (아래 "예비 풀" 참조).

로딩은 스키마의 `from_dict()` 를 쓴다. 전부 `to_dict()` 왕복이 원본 JSON과 동일함이 확인돼 있다.

```python
import json
from src.schema import RawArticle

with open("tests/fixtures/raw_articles_overseas.json", encoding="utf-8") as f:
    articles = [RawArticle.from_dict(d) for d in json.load(f)]
```

`WeeklyBrief` fixture 는 따로 두지 않았다. `week_meta.json[0]` + `brief_items_*.json` 으로 조립하면 된다.

## 해외 랭킹 — 계산 근거

SPEC 6절 공식을 `raw_articles_overseas.json` 의 원시 지표에 그대로 적용한 결과다.
`ranked_articles_overseas.json` 의 `score_components` 는 이 표에서 나왔다.

**1) 소스 내 합성** `hn = 0.7*log1p(points) + 0.3*log1p(comments)` / `reddit = log1p(upvotes)`

| id | points/ups | comments | raw | min-max |
|---|---|---|---|---|
| `hn:41240355` (1X NEO) | 731 | 604 | 6.53861 | **1.00000** (max) |
| `hn:41236780` (Figure) | 842 | 331 | 6.45742 | 0.91907 |
| `hn:41253117` (Waymo) | 664 | 512 | 6.42193 | 0.88370 |
| `hn:41248903` (Show HN) | 517 | 143 | 5.86593 | 0.32950 |
| `hn:41244517` (Gemini Robotics) | 396 | 88 | 5.53535 | **0.00000** (min) |
| `reddit:1mqk4pz` (π-0.6) | 3120 | 214 | 8.04591 | **1.00000** (max) |
| `reddit:1mr2h8k` (Figure) | 1870 | 342 | 7.53423 | 0.74125 |
| `reddit:1mq0a4b` (Unitree) | 1104 | 156 | 7.00760 | 0.47493 |
| `reddit:1mpz8vr` (Cross-embodiment) | 892 | 97 | 6.79459 | 0.36721 |
| `reddit:1mr7t2c` (actuator 질문) | 431 | 268 | 6.06843 | **0.00000** (min) |

**2) URL 정규화 병합 후 합산** → 경쟁 9건, 예비 풀 1건

| 순위 | 합계 | 구성 | 대표 |
|---|---|---|---|
| 1 | **1.66032** | hn 0.91907 + reddit 0.74125 | `hn:41236780` (병합) |
| 2 | 1.00000 | hn 1.0 | `hn:41240355` |
| 3 | 1.00000 | reddit 1.0 | `reddit:1mqk4pz` |
| 4 | 0.88370 | hn 0.8837 | `hn:41253117` |
| 5 | 0.47493 | reddit 0.47493 | `reddit:1mq0a4b` |
| 6 | 0.36721 | reddit | `reddit:1mpz8vr` (컷) |
| 7 | 0.32950 | hn | `hn:41248903` (컷) |
| 8 | 0.00000 | hn 0.0 | `rss:deepmind:...` + `hn:41244517` 병합 (컷) |
| 9 | 0.00000 | reddit 0.0 | `reddit:1mr7t2c` (컷) |
| — | 경쟁 제외 | 신호 없음 | `rss:arxiv:2608.05119` → **예비 풀** |

### 2·3위 동점 — 게시 시각 이른 순 (SPEC 6절 확정)

**2·3위가 1.00000 동점**이다. min-max 특성상 각 소스의 1위는 항상 정확히 1.0이므로
이 동점은 우연이 아니라 상시 발생한다.

SPEC 6절 "동점 처리"에 따라 **게시 시각이 이른 순**으로 깼다.

| | id | 게시 시각(KST) |
|---|---|---|
| 2위 | `hn:41240355` | 08/12 05:30 |
| 3위 | `reddit:1mqk4pz` | 08/12 12:41 |

### 예비 풀 — `ranked_articles_overseas_reserve.json`

`rss:arxiv:2608.05119` 는 HN·Reddit 어디에도 없어 인기도 신호가 없다.
랭킹 대상에서 빠지고 예비 풀로 간다 (SPEC 6절).

| 필드 | 값 | 이유 |
|---|---|---|
| `sort_score` | `-1.0` | 경쟁 최하위(이 주엔 0.47493)보다 확실히 뒤 |
| `normalized_score` | `null` | **0.0 이 아니다.** "신호 없음" ≠ "최하위" |
| `score_components` | `{}` | 기여한 소스가 없다 |
| `rank` | `1` | **예비 풀 내부 순번**이다 — 해외 5건의 순위가 아니다 |

`rank` 는 예비 풀 정렬(게시 시각 **역순**, 최신 우선)에서 나온 값이다.
`sort_score` 가 전부 `-1.0` 으로 같으므로 실질 정렬 기준은 게시 시각이다.
실제로 투입될 때(= 해외가 5건에 못 미칠 때) 해외 목록 뒤에 붙으면서 `rank` 는 재부여된다.

이 주는 해외가 5건을 채웠으므로 **이 파일의 항목은 발행되지 않는다.**
`ranked_articles_overseas.json` 과 합치면 안 된다.

## 본문 보강 — 항목별 상태 (SPEC 6.5절)

`enriched_articles_overseas.json` 의 `article.extra` 에 담긴 결과다.
`ranked_articles_overseas.json` 과의 차이는 **이 세 키뿐**이다.

| rank | id | `enrich_status` | `enrich_text` | `description` | 요약 입력 |
|---|---|---|---|---|---|
| 1 | `hn:41236780` | `success` | 720자 | 없음 | `enrich_text` |
| 2 | `hn:41240355` | `success` | 658자 | 없음 | `enrich_text` |
| 3 | `reddit:1mqk4pz` | `success` | 625자 | 없음 | `enrich_text` |
| 4 | `hn:41253117` | `failed` | **키 없음** | 없음 | **제목뿐** |
| 5 | `reddit:1mq0a4b` | `success` | 213자 | 213자 | `enrich_text` |

요약 입력 우선순위는 `enrich_text` → `description` → 제목뿐 이다 (SPEC 6.5절).

- **1·2·3위**가 보강의 존재 이유다. `description` 이 `""` 인 HN·Reddit 링크 글인데
  `brief_items_overseas.json` 에서 정상 요약(`gemini`)이 나온다. 보강이 없으면
  "제목이 말하지 않은 구체적 사실"(SPEC 7절)의 출처가 없어 **모델이 지어내는 수밖에 없다.**
- **4위**는 보강 실패 + `description` 없음 → 요약 입력이 제목뿐이다.
  메인 5건 중 SPEC 7절 조건부 규칙이 발동하는 유일한 항목이며, 여기서는 Gemini 호출까지
  실패해 요약 줄이 생략된다. 조건부 규칙을 지킨 **정상 산출물**은
  `summary_cases/case_title_only.json` 에 있다.
- **5위**는 self-post 라 추출 결과가 `selftext`(= `description`)와 같다.
  보강은 성공했지만 얻은 정보가 없다. 성공/실패의 이분법으로 안 잡히는 케이스다.
- `enrich_url` 은 다섯 건 모두 **`anchor_url`** 과 같다 (`normalized_url` 이 아니다 — SPEC v1.3).
  보강은 출력 앵커와 같은 URL을 fetch한다. 실패한 4위에도 남아 있다 —
  "어디에 걸었다가 실패했는지"는 원상태 유지 대상이 아니다.

`enriched_articles_domestic.json` 은 **없고, 앞으로도 만들지 않는다.**
SPEC v1.3에서 본문 보강이 **해외 한정**으로 확정됐다 (6.5절 "왜 해외만인가").
국내 항목의 `extra` 에 `enrich_*` 키가 없는 것은 실패가 아니라 **대상이 아님**이다.

`enrich_text` 는 그럴듯하게 지어낸 원문이다. 실제 사이트 내용이 아니다.
길이·구조가 실제 추출 결과와 같은 성격이면 되는 자리이므로 그대로 둔다.

## 의도적으로 심어 둔 케이스

| 케이스 | 위치 | 왜 |
|---|---|---|
| `[단독]` 접두사 | 국내 1위 `naver:fc1fc8735424` | `title` 은 접두사 포함, `display_title` 은 제거본 |
| `[속보]` 접두사 | 국내 2위 `naver:26348a94c7a0` | 정규식이 `[단독]` 만 잡고 끝나지 않는지 |
| `[포토]` 접두사 | 국내 노이즈 기사 | 클러스터링 전 제거 안 하면 노이즈끼리 묶이는지 |
| **HN+Reddit 병합** | 해외 1위 (`hn:41236780` + `reddit:1mr2h8k`) | 같은 TechCrunch URL. Reddit 쪽에 `?utm_source=reddit` 가 붙어 있다 |
| **RSS+HN 병합** | `rss:deepmind:...` + `hn:41244517` | 후행 슬래시 차이. 병합되면 예비 풀이 아니라 정상 경쟁 |
| **`www.` 제거 (비교용만)** | `reddit:1mqk4pz`, `hn:41240355`, `reddit:1mq0a4b` | `normalized_url` 에서만 지워지고 `anchor_url` 에는 남는다 |
| **예비 풀** | `rss:arxiv:2608.05119` | HN·Reddit 어디에도 없는 RSS 단독 → 랭킹 제외, 5건 미달 시 투입 |
| **본문 보강 성공** | 해외 1·2·3위 | `description` 이 `""` 인데 요약이 정상(`gemini`)인 근거 |
| **본문 보강 실패** | 해외 4위 `hn:41253117` | 타임아웃. `enrich_text` 키 자체가 없다 (`enrich_status: "failed"`) |
| **조건부 프롬프트 발동** | 해외 4위 | 보강 실패 + `description` 없음 → 요약 입력이 **제목뿐** (SPEC 7절 조건부 규칙) |
| **보강해도 소득 없음** | 해외 5위 `reddit:1mq0a4b` | self-post 라 추출 본문 = `selftext` = `description`. 성공했지만 새 정보가 없다 |
| **앵커 ≠ 비교용 URL** | 해외 5건 전부 | `anchor_url` 과 `normalized_url` 이 5건 모두 다르다 |
| **앵커 ≠ 수집 URL** | 해외 3위 `reddit:1mqk4pz` 뿐 | 트래킹만 지우므로 `utm_*` 가 붙은 항목에서만 원본과 달라진다 |
| Reddit self-post (본문 있음) | `reddit:1mq0a4b` | `publisher = "Reddit r/robotics"`, description 존재 → fallback 120자 경로 |
| Reddit self-post (`selftext: ""`) | `reddit:1mr7t2c` | 제목만 있는 글 |
| description 없음 | HN 링크 글 5건 전부 + Reddit 링크 글 | **해외의 상시 상태.** fallback "요약 줄 생략" 경로 |
| arXiv 매체명 | `reddit:1mpz8vr` | 도메인이 `arxiv.org` 면 publisher 는 `arXiv` |
| 인기도 신호 전무 | 국내 3건 + RSS 2건 | `metrics` 3필드 모두 `null` |
| 부분 발행 | 국내 3건뿐 | 토글·카톡 건수 표기 검증 |
| 월/연 경계, 5주차 | `week_meta.json` 2·3·4번 | 목요일 앵커 규칙 |

## 고정된 규약 (테스트가 의존해도 되는 것)

- `article_id` = `naver:<sha1(originallink)[:12]>` / `hn:<objectID>` / `reddit:<id>` / `rss:<피드키>:<슬러그>`
- 모든 시각은 **tz-aware KST(+09:00)**. HN/Reddit 의 UTC·epoch 는 변환된 상태로 들어 있다
- `RawArticle.url` 은 **수집 원본 URL** 이다 (`utm_*` 포함). 손대지 않는다
- 해외 정규화 산출물은 **두 개**다 (SPEC v1.3 · 4절)
  - `extra.normalized_url` — **비교용**. 소문자화 + `www.` 제거 + 트래킹 제거 + 후행 슬래시 제거. 중복 제거에만 쓴다
  - `extra.anchor_url` — **앵커용**. 트래킹만 제거. `www.`·후행 슬래시·대소문자는 원본 유지
- **해외 `BriefItem.url`(출력 앵커) = `extra.anchor_url`** 이다. `normalized_url` 이 아니다
- 국내는 정규화 산출물이 아예 없다 (`normalized_url`·`anchor_url` 두 키 모두 없음).
  앵커도 `RawArticle.url` 원본 그대로다
- 보강 결과는 `extra.enrich_status` / `enrich_text` / `enrich_url` 세 키다.
  실패면 `enrich_text` 키가 **없고**, 보강 대상이 아니었으면 세 키가 **모두** 없다
- `enrich_url` == `anchor_url`. 보강은 출력 앵커와 같은 URL을 fetch한다
- 보강은 **해외에만** 붙는다. 국내 항목에는 `enrich_*` 키가 없다 (SPEC 6.5절)
- fallback 원천은 **`description` → `enrich_text` → 생략** 3단이다 (SPEC v1.3 · 4·7절).
  해외 5위가 1순위 대비다 — `enrich_text` 가 있는데도 출력에 나간 건 `description` 앞 120자다.
  해외 4위는 3순위 대비다 — `description` 도 `enrich_text` 도 없어 요약 줄이 생략됐다.
  **2순위(`enrich_text` 앞 120자)를 실제로 타는 항목은 이 주 fixture에 없다** (아래 "남은 미정" 참조)
- `RawArticle.title` 은 `<b>` 태그·엔티티만 푼 원문(접두사 유지). 원본은 `extra.raw_title`
- `sort_score` = 국내는 `cluster_size`, 해외는 `normalized_score`
- `score_components` 의 키는 `SourceKind` 값(`hacker_news`, `reddit`)이다. 병합 시 소스별로 합산해 둔다
- `merged_article_ids` 는 단건이어도 자기 자신을 담는다
- 병합 항목의 대표는 **게시 시각이 가장 이른 것** (SPEC 6절 확정)

## SPEC v1.3 반영 — 앵커 URL 재산출

v1.2는 앵커에 `normalized_url`(비교용)을 걸었다. v1.3이 이를 **대체**해 정규화를
비교용/앵커용 두 종류로 분리했고, 앵커는 `anchor_url`(트래킹만 제거)을 쓴다.
→ `extra` 에 `anchor_url` 키가 12건 전부에 추가됐고, `brief_items_overseas.json` 의
`url` 5건과 `enriched_articles_overseas.json` 의 `enrich_url` 5건이 그 값으로 바뀌었다.

| rank | `RawArticle.url` (수집 원본) | `normalized_url` (비교용) | `anchor_url` (앵커 = 출력) |
|---|---|---|---|
| 1 | `.../figure-raises-1-5b-series-d/` | `.../figure-raises-1-5b-series-d` | `.../figure-raises-1-5b-series-d/` |
| 2 | `https://www.1x.tech/discover/neo-preorders` | `https://1x.tech/...` | `https://www.1x.tech/discover/neo-preorders` |
| 3 | `https://www.physicalintelligence.company/blog/pi06-open-weights?utm_source=reddit&utm_medium=social` | `https://physicalintelligence.company/blog/pi06-open-weights` | `https://www.physicalintelligence.company/blog/pi06-open-weights` |
| 4 | `.../freeway-driving-for-everyone/` | `.../freeway-driving-for-everyone` | `.../freeway-driving-for-everyone/` |
| 5 | `https://www.reddit.com/...breakdown/` | `https://reddit.com/...breakdown` | `https://www.reddit.com/...breakdown/` |

- **앵커 = 수집 원본**인 항목이 4건이다 (1·2·4·5위). 트래킹 파라미터가 없으면 지울 것도 없다
- **앵커 ≠ 수집 원본**은 3위 하나뿐이다 — `utm_source`·`utm_medium` 두 개가 지워졌다
- 비교용은 여전히 5건 모두 원본과 다르다. 병합 판정은 이 값으로만 한다
- 병합 쌍의 비교용 값이 같다는 사실은 그대로다 (`hn:41236780` ↔ `reddit:1mr2h8k`,
  `rss:deepmind:...` ↔ `hn:41244517`). **앵커용은 병합에 쓰지 않는다** — 두 값이
  달라도(`reddit:1mr2h8k` 의 앵커는 utm이 지워진 형태) 병합 결과에 영향이 없다

## 이전 판의 "남은 미정" — SPEC v1.2 에서 전부 확정

| 항목 | 확정 내용 | fixture 변화 |
|---|---|---|
| 동점 처리 | 게시 시각 **이른 순** (SPEC 6절) | 없음 — 이미 그 순서였다. 2·3위 유지 |
| 병합 대표 | 게시 시각 **이른 항목** (SPEC 6절) | 없음 — 1위 대표는 `hn:41236780`(08/11 23:22) 유지 |
| 출력 앵커 URL | **정규화본**을 쓴다 (SPEC 4절) | ~~`brief_items_overseas.json` 의 `url` 5건 전부 변경~~ → **v1.3에서 대체됨** (위 절) |
| min-max 바닥 0.0 | 알려진 약점으로 감수 (SPEC 6절) | 없음 — 8·9위는 그대로 0.0, 어차피 컷 |

병합 대표는 `publisher` 를 바꾸지 않는다. 같은 URL이라 도메인이 같기 때문이다
(1위는 HN·Reddit 양쪽 다 `TechCrunch`). 대표가 실제로 정하는 것은 `published_at` 뿐이다.

앵커 URL 변경 내역은 위 v1.3 절의 표로 대체됐다.

> **v1.2에서 같이 고친 버그**: `hn:41240355` 의 `extra.normalized_url` 이
> `https://www.1x.tech/...` 로, `www.` 가 지워지지 않은 채 들어 있었다 (SPEC 6절 규칙 위반).
> 앵커가 이 값을 쓰게 되면서 드러났다. 이제 12건 전부가 정규화 규칙 재적용과 일치한다.

## 요약 케이스 — `summary_cases/`

메인 주차 fixture는 **랭킹까지의 산출물**을 고정한다. 요약 단계는 그 뒤에 오는데,
"어떤 입력이 들어왔을 때 어떤 요약이 나와야 하는가"는 주차 fixture로 덮이지 않는 자리가 있다.
`summary_cases/` 는 그 자리를 채우는 **독립 케이스**다.

| 파일 | 요약 입력 | 검증 대상 |
|---|---|---|
| `case_title_only.json` | 제목뿐 (`enrich_text` 없음 + `description` 없음) | SPEC 7절 **조건부 규칙**을 지킨 산출물 — 추측 없는 맥락 2문장 |
| `case_with_body.json` | `enrich_text` (보강 성공) | SPEC 7절 공통 제약 — 문장 1 = 본문에서 끌어온 구체적 사실, 문장 2 = 맥락 |
| `case_domestic_normal.json` | `description` (국내 정상 경로) | 국내는 보강을 타지 않는다 — `extra` 에 `enrich_*` 키가 없다 |

각 파일의 구조는 같다.

```
{
  "case", "note", "why", "spec_refs",
  "input":    { "ranked_article": <RankedArticle>, "summary_input": {...} },
  "expected": { "brief_item": <BriefItem>, "rendered": "...", "assertions": [...] }
}
```

- `input.ranked_article` 은 `RankedArticle.from_dict()` 로, `expected.brief_item` 은
  `BriefItem.from_dict()` 로 그대로 로드된다 (왕복 동일함 확인됨)
- `input.summary_input` 은 **요약기가 무엇을 입력으로 골랐어야 하는지**를 명시한다.
  `source` (`title_only` / `enrich_text` / `description`) · `resolved_by` (선택 근거) ·
  `prompt_variant` (국내용/해외용) · `conditional_title_only_rule` (7절 조건부 규칙 발동 여부)
- `expected.rendered` 는 SPEC 4절 출력 블록 그대로다. `assertions` 는 사람이 읽는 근거이며
  테스트가 문자열로 소비하는 값이 아니다
- **이 세 건은 메인 주차 풀(`raw_articles_overseas.json` 12건)에 속하지 않는다.**
  합치면 랭킹 계산 근거표가 어긋난다. `article_id` 도 겹치지 않게 새로 뒀다
- 기대 요약문은 사람이 쓴 것이다. 실제 Gemini 출력이 글자까지 같을 수는 없으므로,
  이 파일들은 **문자열 일치 테스트가 아니라 규칙 검증의 기준**으로 쓴다
  (입력 선택·`summary_status`·문장 수·문장당 40자·앵커 URL은 그대로 단언해도 된다)

## 남은 미정 (fixture 가 임의로 정한 부분)

1. **fallback 2순위(`enrich_text` 앞 120자)를 타는 항목이 없다.** SPEC v1.3이 fallback
   원천을 `description` → `enrich_text` → 생략 3단으로 확정했는데, 이 주 fixture에서
   `description` 이 없고 `enrich_text` 만 있는 항목(해외 1·2·3위)은 요약이 **성공**해
   fallback 자체를 타지 않는다. 2순위 경로의 기대 출력은 아직 fixture에 없다.
2. **보강 성공/실패의 이분법에 안 잡히는 케이스**(해외 5위 — self-post라 추출 결과가
   `description` 과 같다)는 fixture에 있지만, SPEC은 이 상태에 별도 이름을 주지 않았다.
   `enrich_status` 는 `"success"` 다.

## 렌더링 기대 출력

`brief_items_overseas.json` 은 SPEC 4절의 정상 경로와 실패 경로를 한 번에 덮는다.
1위는 SPEC 4절 예시 블록을, 4·5위는 SPEC 4절 "요약 실패 시 출력" 예시를 **글자 그대로** 재현한다.

```
### 국내

**1. 삼성전자, 휴머노이드용 AP 양산 착수**
    2027년 상용화를 목표로 전용 연산 칩을 개발 중이다.
    기존 모바일 AP 대비 추론 성능을 4배로 끌어올렸다.
    전자신문 · 08/13

### 해외

**1. Figure raises $1.5B at $39B valuation**
    휴머노이드 스타트업 피규어가 시리즈 D를 마감했다.
    BMW 공장 실배치 실적이 평가에 결정적으로 작용했다.
    TechCrunch · 08/11

**4. Waymo opens freeway driving to all riders in three metros**
    Waymo · 08/13

**5. Unitree G1 teardown: BOM breakdown and what the $16k price actually buys**
    Spent two weeks disassembling a G1 down to the last harmonic drive. Full parts list with supplier part numbers, actuator ⚠️ 자동 요약 실패
    Reddit r/robotics · 08/11
```
