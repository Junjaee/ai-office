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

## 소재 출처와 우선순위 (사용자 결정 2026-09-12)

출처 탐색(`ai-side/01_인스타게시글_aitips/research/출처탐색_2026-09-11.md`) 결과, 한국 AI 인스타 계정들은 외국 AI 인스타가 아니라 **원출처(회사 공식 계정·X 창작자)** 를 다음 날 오전에 옮겨 적는다. 그래서 후보는 이렇게 모은다.

1. **🇺🇸 미국 원출처** — 공식 RSS(`openai_news` `anthropic_news` `deepmind` `google_ai`), 뉴스레터·유출(`rundown` `testingcatalog` `techcrunch_ai`), 그리고 프로필 `watch_foreign` 의 인스타 계정(openai·googledeepmind·therundownai 등, 최근 48시간). 편집장은 이 중 **한국 계정이 아직 안 다룬 것을 `gap: true`(빈자리)** 로 표시한다 — 검토 칸에 "🇺🇸 빈자리" 표가 붙는다.
2. **🇰🇷 한국 AI 인스타** — 프로필 `watch_accounts`(ai.trend.kr·ai_freaks.kr·prompt_what·ai_dori_·trenddalkak.ai)의 최근 게시물, 좋아요 순. **같은 주제를 골라도 된다**(피하지 않는다). 우리는 우리 식(기사→카드, 우리가 그린 화면)으로 다시 쓴다.
3. 그 외 RSS·커뮤니티는 공식 링크가 있을 때만 맨 뒤. 시끄러운 출처는 `source_caps` 로 상한.

인스타 계정 읽기는 Instagram Graph API 의 비즈니스 디스커버리(`insta_watch.py`, 캡션·좋아요·댓글 수만, 사진은 쓰지 않음). 그룹별 상한은 `watch_cap`(기본 15).

준비물(한 번): 페이스북 페이지 하나 + 그 페이지에 인스타 프로페셔널 계정 연결 + 페이지 권한이 있는 사용자 토큰(`instagram_basic`, `pages_show_list`, `pages_read_engagement`, 장기 60일). `python automations/insta/discovery_setup.py <토큰 파일> --app-id … --app-secret-file …` 이 장기 토큰 교환·인스타 계정 id 확인·시험 조회까지 해 준다. 값은 GitHub Secrets `IG_DISCOVERY_TOKEN`, `IG_DISCOVERY_USER_ID`. 없으면 참고 계정만 건너뛰고 RSS 로 진행한다.

## 주제 검토 방식 (사용자 결정 2026-09-11 — 기본 운영 방식)

사용자가 사이트에서 고른 것을 만들되, **아무도 안 고르면 07:30 에 편집장 1순위가 자동으로 나간다**(사용자 결정 2026-09-12 — "오전 7시 30분 발행". `config.actions.yaml` 의 `auto_pick`, 0 이면 끔).

| 때 | 실행 방식(`--mode`) | 하는 일 |
|---|---|---|
| 매일 06:30 KST (cron `30 21 * * *`) | `topics` | 미국 원출처·한국 참고 계정·RSS 후보 → 편집장(모델)이 **10건** 골라 한국어 제목·이유·각도·빈자리 표시를 붙여 `public/review/<사무실>/insta_<계정>.json` 에 저장·커밋. 이미 올린 것·예약된 것은 제외 |
| 사이트 검토 칸 "선택 N개 만들기" | `queue` (입력 `picks=id,id`) | 고른 N개를 **고정 시간대(`slots`: 07:30·12:30·18:30)의 다음 빈 칸부터 차례로** 예약(이미 예약된 칸은 건너뜀, 하루 3건이 상한). 시각이 된 것이 있으면 이어서 만든다 |
| (매시 30분 확인 안에서) 07:30 창 | `publish` 의 자동 선택 | 첫 시간대 창(07:30~08:29)에 예약·진행 중인 것이 없으면 후보 1번(`auto_pick` 개수)을 바로 만들어 게시. 사용자가 미리 골라 뒀으면 건너뛴다 (`--mode auto` 로 손으로도 가능) |
| 매시 30분 (cron `30 * * * *`, 게시 시간대와 맞춤) | `publish` | 댓글→DM 답장 → 예약 시각이 된 항목을 만들어 게시. 만들 것이 없으면 `review_due.py`(표준 라이브러리만) 로 20초 안에 끝낸다(의존성 설치 전) |
| 카드 ▶ 주제 뽑기 / 검토 칸 "주제 다시 뽑기" | `topics` | 지금 후보를 새로 뽑는다 |
| 이 PC 시험 | `run` | 후보 1건을 골라 바로 게시(옛 방식) |

- 검토 파일 모양과 예약 규칙: `insta_review.py` 머리말. 상태는 `queued → making → done | failed`, 끝난 항목은 2일 뒤 정리.
- 대시보드: `app/office/ReviewPanel.tsx` (사무실 설정의 `review: { kind: "topics" }` 가 있는 자동화 카드에 붙는다). Worker `/api/review` 가 파일을 읽고, `/api/run` 의 `inputs.mode·picks` 로 워크플로에 전달한다(허용 목록 검사).
- 게시 시각은 고정 시간대다. 예: 09:17 에 3개 고르면 12:30·18:30·다음 날 07:30 (사용자 결정 2026-09-12 — 출근 직후·점심·퇴근 무렵이 저장·공유가 가장 많다).

## 영상 소재 → 릴스 (사용자 결정 2026-09-12)

소재에 영상이 딸려 있으면 카드 대신 **릴스**로 게시한다(`insta_video.py`, `config.actions.yaml` 의 `reels: true`). 남의 영상은 **출처를 화면과 캡션에 표기**하고 쓴다 — 화면 아래 `Source · @이름 / X`, `Source · OpenAI / YouTube`, 캡션에 원문 링크. 원작자가 문제 삼으면 내린다.

- 영상을 찾는 순서: 소재 링크 자체가 영상(유튜브·X·틱톡) → 본문 속 영상 링크 → 공식 페이지 안의 `<video>`·mp4·webm·유튜브 embed. **인스타그램 게시물의 영상은 로그인 없이 받을 수 없어**(2026-09-12 확인) 시도하지 않는다 — 그런 건 앱에서 직접 리포스트한다.
- 회사 공식 유튜브 채널(`yt_openai` `yt_anthropic` `yt_deepmind` `yt_gemini`)이 출처에 들어 있어 발표·데모 쇼츠가 후보에 `[🎬영상]` 표시로 올라온다.
- **GitHub 서버에서 받을 수 있는 것(2026-09-12 실측)**: X 영상 ✅, 공식 페이지의 mp4/webm ✅, **유튜브 ❌**("Sign in to confirm you're not a bot" — 데이터센터 IP 차단, 클라이언트를 바꿔도 안 됨). 유튜브 소재는 서버에서는 자동으로 카드로 대체된다. 이 PC(가정용 IP)에서는 유튜브도 받아지므로, 유튜브 릴스가 꼭 필요하면 사무실 PC 실행기에 영상 받기 단계를 두는 방법이 있다(미구현).
- 만들기: yt-dlp 로 받기(300초 넘으면 안 씀) → ffmpeg 로 1080×1920(세로는 꽉 채워 자르고, 가로는 위아래 배경) + 제목·부제·출처·계정 오버레이(`templates/reel_overlay.html`, 카드와 같은 글꼴) → 90초까지 → R2 에 올려 `media_type=REELS` 로 게시(피드에도 표시). 실패하면 카드로 진행한다.
- 게시 기록(`data/insta/<계정>/posted.jsonl`)에 `kind: reel`, `credit`, `video_url` 이 남는다.

## 하루 게시 상한 (2026-09-12)

새 계정(팔로워 0)이 하루 11건을 몰아 올렸더니 좋아요 1개·댓글 0개(비즈니스 디스커버리 실측). 인스타는 몰아 올리는 새 계정을 스팸처럼 취급하고, 팔로워가 없으면 게시물이 갈 곳도 없다. 그래서 `config.actions.yaml` 의 `slots`(07:30·12:30·18:30)로 **하루 3건, 고정 시간대**만 쓰고, 더 고르면 다음 날 칸으로 넘긴다(`insta_review.slot_times`). 대시보드 문구는 `app/review.ts` 의 `SLOTS` 와 맞춘다.

## 댓글 → DM (프롬프트 보내기, 2026-09-12)

글마다 편집장이 `dm_keyword`(댓글로 남길 말)와 `dm_text`(보낼 프롬프트 전문)를 쓰고, 캡션 마지막 줄에 "💬 댓글에 '<키워드>' 라고 남기면 … DM 으로" 를 붙인다(모델이 빠뜨리면 `local_checks` 가 붙인다). 매시 예약 확인 실행에서 `insta_dm.py`(표준 라이브러리)가 최근 7일 게시물의 댓글을 읽어 키워드 댓글에 **비공개 답장(DM)** 과 공개 답글을 보낸다. 기록은 `data/insta/<계정>/dm_log.jsonl`(댓글당 1회). 토큰에 `instagram_business_manage_messages`·`instagram_business_manage_comments` 가 필요하다 — 없으면 한 줄 안내하고 끝난다. 다른 AI 계정들은 이걸 ManyChat(유료)으로 하는데, 댓글 유도 글의 댓글 수가 3~18배 높았다(`research/성장전략_2026-09-12.md`).

## 검토 칸에서 예약 고치기 (사용자 요청 2026-09-12)

후보는 최대 **20건**이 보이고, 예약 항목마다 **시각 변경**(HH:MM, 지났으면 내일)·**취소** 버튼이 있다. 버튼은 워크플로 `mode=edit` + `edits=id=cancel|id=HH:MM`(Worker 허용 목록 검사)로 가고, `review_edit.py`(표준 라이브러리만)가 의존성 설치 없이 검토 파일만 고쳐 커밋한다(약 20초 뒤 화면에 반영).

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
- **한글 화면만**(사용자 지적 2026-09-11 밤): 영어가 찍힌 외국 홍보 사진은 "AI 로 만든 티"가 나서 안 쓴다. 외국 매체 사진은 후보에서 빼고(`is_korean_source`), 페이지 캡처는 `Accept-Language: ko-KR` 로 잡는다. 사진이 없으면 모델이 **한글 채팅 화면 목업**(`mock`: 앱·사용자 입력·답변 줄, 표는 `|`)을 구성하고 템플릿이 폰 프레임으로 그린다 — 100% 우리 그래픽, "직접 구성한 예시 화면" 표기. 프롬프트 문장이 있는 카드는 말풍선 그래픽. 무작위 CC 사진 검색은 기본 끔(주제와 무관·부적절한 사진이 걸렸음).

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
