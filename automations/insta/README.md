# 인스타 게시글 자동화 (insta)

소재 수집 → 글 생성 → 카드 제작 → 업로드를 한 번에 돌린다. **코드는 플랫폼당 한 벌**이고, 계정마다 `config.actions.yaml` 의 `accounts` 항목 + `profiles/<주제>.yaml` 만 다르다(팀 = 플랫폼, 자동화 = 계정). 전부 무료 경로만 쓴다(Claude 구독 토큰 → Gemini 무료 등급, R2 무료, Playwright).

조사·설계: `docs/superpowers/specs/2026-09-11-인스타-게시글-자동화-research.md`

## 흐름 (사용자 결정 2026-09-11: 기사 먼저, 카드는 요약)

| 단계(직원) | 파일 | 하는 일 | 품질 장치 |
|---|---|---|---|
| topic 소재 선정 | `insta_sources.py` | 프로필의 RSS 출처에서 72시간 내 글 수집, 이미 올린 소재 제외, 신호 단어로 정렬 → 편집장(모델)이 1건 선정 | 중복 제외(`data/insta/<계정>/posted.jsonl`), 광고·행사 제외 지시 |
| write 글쓰기 | `insta_research.py` → `insta_writer.py` | ① 소재 원문 + 원문이 가리키는 공식 링크 본문 읽기 ② 모델이 검색어 3개(한 2·영 1) → Bing 뉴스 RSS 로 **같은 주제의 기사·블로그** 6건 본문·사진 수집 ③ **기사 한 편** 작성: 어그로 제목(사실 안에서) + 부제 + 문단 6개 안팎, **문단 하나 = 소주제 하나, 3~4줄** ④ **글쓰기 전문가 검수**(가독성·흥미·사실·구조, 최대 50점) | 스키마·금지어·출처 URL·문단 길이 코드 검사. 사실 오류가 있으면 점수와 무관하게 반려. 반려되면 **이전 기사 + 지적을 주고 그 부분만 고쳐** 재검수(최대 3회). 통과했는데 손질 거리가 길면 1회 더 다듬기(점수 안 떨어질 때만 채택). 3회 안에 만족 못 해도 기준 점수(38)를 넘는 판이 있으면 채택하고 지적은 메모로. 결과는 `out/…/article.md` 로 사람이 읽을 수 있게 저장 |
| card 카드 제작 | `insta_writer.plan_cards` → `insta_cards.py` + `templates/*.html` | 표지(제목·부제) + **문단마다 카드 1장** — 소제목은 한 줄, 본문은 기사 문단을 **요약하지 않고 문장 단위로 그대로** 정렬(사용자 결정 2026-09-11) + 마무리. 모델은 표지 문구와 사진만 고른다. 사진 후보(소재 원문·공식 링크·관련 기사의 사진, 공식 페이지 캡처)에 번호를 붙여 주고 모델이 소주제에 맞는 것을 고름 → Playwright 로 1080×1350 JPEG | Pretendard 글꼴, 어절 단위 줄바꿈, 글자·사진 넘침 자동 축소, 너무 작은 사진(폭 480 미만) 제외, 사진 아래 **출처 도메인 표기**, 검토용 preview.jpg |
| upload 업로드 | `insta_publisher.py` | R2 에 올려 공개 URL → Instagram API 캐러셀 게시 → 게시 기록 커밋 | 컨테이너 상태 확인, 하루 100건 한도 |

사진 출처에 대해: "조회수 높은 글의 사진" 은 공개 지표가 없어 고를 수 없다. 대신 **공식 출처(제품 페이지·공식 블로그) 사진을 앞에** 두고 관련 기사 사진은 뒤에 둔다. 언론사 사진은 저작권이 있을 수 있으니 카드에 출처를 찍고, 공식 사진이 있으면 그것을 우선 쓰게 프롬프트에 적혀 있다.

중간 산출물(`out/<계정>/<날짜>/`): `topic.json`(소재·원문·관련 기사·검색어) → `article.json`·`article.md`(기사·검수) → `post1/plan.json`(카드 계획·사진) → `post1/NN.jpg`·`preview.jpg` → `cards.json`.

## 새 계정(주제) 붙이기

1. `profiles/<주제>.yaml` 을 `aitips.yaml` 복사해 채운다: 독자·말투·형식·문단 수·제목 패턴·금지어·출처·템플릿·검수 가중치. 참고 원고 `refs/<주제>.md` 도.
2. `config.actions.yaml` 의 `accounts` 에 항목 추가 (`profile`, `handle`, `dept`, `result_link`).
3. `.github/workflows/insta.yml` 의 env 에 `INSTA_<계정대문자>_TOKEN`, `INSTA_<계정대문자>_USER_ID` 두 줄 추가, GitHub Secrets 에 값 등록.
4. `app/workspaces/side.ts` 의 `AUTOMATIONS` 에 `{ id: "insta_<계정>", dept, workflow: "insta.yml", inputs: { account: "<계정>" }, tasks: [topic, write, card, upload] }`.
5. `ai-side/NN_인스타게시글_<계정>/README.md` 개인 폴더.
6. 카드 겉모습을 바꾸려면 `templates/<이름>.html` 을 만들고 프로필 `template` 에 이름을 적는다.

주의: 대시보드의 실행 상태는 **워크플로 파일 단위**로 잡힌다. 같은 `insta.yml` 을 쓰는 계정이 둘 이상이면 최근 실행 하나만 보이므로, 두 번째 계정을 붙일 때 Worker 의 run 매칭에 `inputs.account` 를 반영해야 한다(할 일).

## 참고 계정 주제 (한국 AI 인스타 계정이 올린 것 먼저 — 사용자 결정 2026-09-11)

후보의 앞자리는 RSS 가 아니라 **참고 계정(`profiles/<주제>.yaml` 의 `watch_accounts`)의 최근 게시물**이다. Instagram Graph API 의 비즈니스 디스커버리로 캡션·좋아요·댓글 수를 읽어(`insta_watch.py`) 좋아요 순으로 후보에 넣고, 편집장은 "인스타에서 반응 좋았던 주제 → 공식 소식 → 커뮤니티" 순으로 고른다. 레딧 같은 시끄러운 출처는 `source_caps` 로 후보 수를 제한한다.

준비물(한 번): 페이스북 페이지 하나 + 그 페이지에 인스타 프로페셔널 계정 연결 + 페이지 권한이 있는 사용자 토큰(`instagram_basic`, `pages_show_list`, `pages_read_engagement`, 장기 60일). `python automations/insta/discovery_setup.py <토큰 파일> --app-id … --app-secret-file …` 이 장기 토큰 교환·인스타 계정 id 확인·시험 조회까지 해 준다. 값은 GitHub Secrets `IG_DISCOVERY_TOKEN`, `IG_DISCOVERY_USER_ID`. 없으면 참고 계정만 건너뛰고 RSS 로 진행한다.

## 주제 검토 방식 (사용자 결정 2026-09-11 — 기본 운영 방식)

주제는 자동으로 고르지 않고 **사용자가 사이트에서 고른 것만** 만든다.

| 때 | 실행 방식(`--mode`) | 하는 일 |
|---|---|---|
| 매일 08:00 KST (cron `0 23 * * *`) | `topics` | RSS 후보 → 편집장(모델)이 **10건** 골라 한국어 제목·이유·각도를 붙여 `public/review/<사무실>/insta_<계정>.json` 에 저장·커밋. 이미 올린 것·예약된 것은 제외 |
| 사이트 검토 칸 "선택 N개 만들기" | `queue` (입력 `picks=id,id`) | 고른 N개를 **24÷N 시간 간격**으로 예약(첫 개는 지금, 나머지는 다음 정각으로 올림) → 첫 개는 바로 기사→카드→게시 |
| 매시 정각 (cron `0 * * * *`) | `publish` | 예약 시각이 된 항목을 만들어 게시. 만들 것이 없으면 `review_due.py`(표준 라이브러리만) 로 20초 안에 끝낸다(의존성 설치 전) |
| 카드 ▶ 주제 뽑기 / 검토 칸 "주제 다시 뽑기" | `topics` | 지금 후보를 새로 뽑는다 |
| 이 PC 시험 | `run` | 후보 1건을 골라 바로 게시(옛 방식) |

- 검토 파일 모양과 예약 규칙: `insta_review.py` 머리말. 상태는 `queued → making → done | failed`, 끝난 항목은 2일 뒤 정리.
- 대시보드: `app/office/ReviewPanel.tsx` (사무실 설정의 `review: { kind: "topics" }` 가 있는 자동화 카드에 붙는다). Worker `/api/review` 가 파일을 읽고, `/api/run` 의 `inputs.mode·picks` 로 워크플로에 전달한다(허용 목록 검사).
- 게시 시각은 정각 단위다(매시 정각에 확인). 예: 09:17 에 3개 고르면 09:17(바로)·18:00·02:00.

## 카드를 보고 고치기 (초기 세팅 때)

카드를 눈으로 보고 지적할 게 있으면 원고를 처음부터 다시 쓰지 말고 **지적만 넣어 다듬는다** — 이전 원고를 모델에 같이 주고 지적된 부분만 고치게 한다.

```bash
python automations/insta/run_insta.py --account aitips --until card --resume --revise --feedback "5번 카드: 번호 목록으로. 코드 칸: 빈칸 대신 실제 예시 문장으로."
```

`--revise` 는 기사(article.json)를 다시 쓴다 — 이전 기사와 지적을 같이 주므로 지적 없는 문단은 그대로 남는다. 표지 문구·사진만 다시 고르려면 `out/…/cards.json` 만 지우고 `--resume` 으로 돌린다.

자주 걸리는 지적은 코드 검사(`insta_writer.local_checks`)와 규칙(`_article_rules`)에 이미 들어 있다: 문단 길이(90~200자), 금지어, 출처 URL, 문단 수.

## 사진 규칙 (사용자 지적 2026-09-11 — 절대 규칙)

- **다른 인스타 계정의 사진·화면 캡처는 절대 카드에 넣지 않는다.** 참고 계정 게시물은 "이런 주제가 반응이 좋았다"는 힌트일 뿐이다. `insta_research.is_social` 이 instagram·facebook·threads·tiktok·x 등 소셜 도메인의 이미지·캡처를 후보에서 걸러 낸다.
- 참고 계정 소재는 페이지를 긁지 않는다(캡션만 근거). 사실·출처는 관련 기사·공식 페이지에서 찾고, **SNS 게시물 주소는 claims 출처로 쓸 수 없다**(코드 검사로 반려). 남의 체험담('~해 봤더니')을 우리 체험처럼 쓰는 것도 반려.
- 사진 후보 순서: 공식 출처 사진 → 관련 기사 사진 → 기사가 출처로 든 공식 페이지 캡처(도메인당 1) → 소재 원문 캡처. 맞는 게 없으면 모델이 `image_query`(영문 개념어)를 주고 **Openverse**(CC0·BY·BY-SA, 무료·키 없음)에서 찾아 넣는다. 카드에 '사진: 작가 · CC BY' 로 표기한다. 표지 + 앞 카드 4장까지.
- 같은 사진을 두 카드에 쓰지 않는다.

## 카드 렌더링 함정 (겪은 것)

- `page.set_content()` 로 연 페이지는 주소가 `about:blank` 라서 Chrome 이 `file://` 이미지·글꼴을 막는다. 그래서 글꼴(Pretendard)과 카드 이미지는 **base64 데이터 URI 로 HTML 에 직접 심는다**(`insta_cards.data_uri`). 이 때문에 카드 하나의 HTML 이 수 MB 가 되지만 문제없다.
- `--resume` 은 `out/<계정>/<날짜>/cards.json` 이 있으면 카드를 다시 만들지 않는다. 템플릿·이미지만 고쳐서 다시 보려면 그 파일을 지우고 돌린다(`--revise` 는 자동으로 지운다).
- 공식 페이지 캡처(`screenshot:<url>`)는 1440×900 으로 잡고 쿠키 배너를 닫거나 CSS 로 숨긴다(`_dismiss_banners`). 완벽하지 않으니 표지 캡처는 결과를 눈으로 본다.
- 한글 줄바꿈은 두 겹이다: 모델이 훅·제목에 `\n` 을 직접 넣고(어절 경계), CSS 는 `word-break: keep-all` + `text-wrap: balance/pretty` 로 본문을 어절 단위로 끊는다.

## 비밀값 (GitHub Secrets)

| 이름 | 용도 |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude 구독으로 글 생성. 이 PC 에서 `claude setup-token \| tail -1 \| gh secret set CLAUDE_CODE_OAUTH_TOKEN` |
| `GEMINI_API_KEY` | 대체 글 생성 (Google AI Studio 무료 키) |
| `R2_ACCOUNT_ID` `R2_ACCESS_KEY_ID` `R2_SECRET_ACCESS_KEY` `R2_BUCKET` `R2_PUBLIC_BASE` | 카드 이미지 공개 URL |
| `INSTA_<계정>_TOKEN` `INSTA_<계정>_USER_ID` | Instagram API (Instagram Login 경로, 장기 토큰 60일) |

## 이 PC 에서

```bash
python -m pip install -r automations/requirements.txt
python automations/insta/run_insta.py --account aitips --dry-run            # 카드까지 (게시 X)
python automations/insta/run_insta.py --account aitips --until topic        # 단계별
python -m pytest -q automations/insta
```

카드 렌더는 설치된 Chrome 을 쓴다. 글 생성은 `claude login` 이 된 CLI 또는 `GEMINI_API_KEY` 가 있어야 한다.
