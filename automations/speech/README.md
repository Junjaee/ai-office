# 회의 발언 요약

재경위·예결위 생중계 동안 국회 인터넷의사중계의 자막을 받아, 위원 한 사람의 질의가 끝날 때마다 발언을 주제별로 요약하고 **10명씩 묶어** 530 알림 봇(텔레그램)으로 보낸다. **이준석 위원 발언은 항상 따로** 보낸다. 설계는 `docs/superpowers/specs/2026-11-05-회의-발언-요약-알림-design.md`.

실행은 GitHub Actions(`.github/workflows/speech.yml`)가 맡는다. 예약이 아니라 **Cloudflare Worker 가 구글 캘린더(530호 일정)의 재경위·예결위 일정 시간대에 깨운다**(`worker/webcast.ts`). 한 번 켜지면 방송이 끝날 때까지(한 실행은 340분, 넘으면 Worker 가 다시 깨워 R2 상태 `/api/speech/state` 로 이어 받는다) 돈다. "끝남" 표시는 **산회 자막을 봤을 때만** 남긴다.

**손으로 켤 때**는 GitHub Actions 탭 "Run workflow"에서 **채널 번호(xcode)를 직접 넣는 것**이 안전하다. 대시보드 ▶ 시작은 채널 없이 켜져 국회 중계 목록의 `xstat`(방송 중 표시)로 고르는데, 이 값은 회의가 끝난 뒤에도 1 로 남아(2026-11-06 실측) 엉뚱한 채널을 3시간 들을 수 있다. 채널 없이 켠 실행이 도는 동안 Worker 는 어느 채널도 새로 깨우지 않는다.

## 흐름 (한 회의)

1. 행정실 메일의 **질의순서 HWP**(`order_hwp.py`)를 읽어 그날 명단·순번을 얻는다. 표에 이준석 위원이 없으면 "오늘 질의 없음"으로 바로 끝낸다(`special_member_only_days`).
2. 방송이 시작될 때까지 60초마다 기다린다(정회 중에도 끝내지 않는다).
3. 자막(`captions.py`, 속기·AI 두 종류)을 받아 사회자 호명으로 위원별 구간을 자른다(`segmenter.py`).
4. 구간이 닫히면 백그라운드에서 요약한다(`summarizer.py`, `automations/common/llm.py` — Claude 구독 → Gemini).
5. 묶음 규칙대로 보낸다(`dispatcher.py`): 10명 묶음 · 이준석 호명 때 준비된 것 즉시 · 이준석 단독 · 뒤늦게.
6. 산회(또는 감시 시간대 끝)에 남은 것을 보내고 상태 파일(건수만)을 커밋한다.

## 설정 (config.actions.yaml)

- `channels` 지켜볼 채널(xcode → 이름). 재경위 65, 예결위 21
- `order_mail` 채널별 질의순서 메일 검색어, `order_lookback_days`
- `special_member` 항상 단독으로 보내는 위원, `special_member_only_days` 그 위원이 질의하는 날만 돈다
- `batch_size` 묶음 인원(10), `segment_max_minutes` 호명 없이 구간을 닫는 시간(25), `summary_topics_max` 요약 주제 상한(8)
- **`notify_target`** `preview` = 사용자 개인 대화방(`TELEGRAM_CHAT_ID`) · `group` = 530 단체방(`NOTICE_530_CHAT_ID`). 요약 품질을 확인한 뒤 `group` 으로 바꿔 커밋한다
- `state_api_base` 상태 저장 Worker 주소
- `tasks` 화면 직원 id — `app/workspaces/assembly.ts` 와 같아야 함(테스트로 강제)
- `attendees.yaml` 답변자 명단("이름 직책"). 자막이 이름을 틀리게 받아 적어도 이 명단으로 바로잡는다 — **개각·인사 때 사람이 고친다**

비밀값은 환경변수로만: `GOOGLE_*`, `NOTICE_530_BOT_TOKEN`, `NOTICE_530_CHAT_ID`, `TELEGRAM_CHAT_ID`, `CLAUDE_CODE_OAUTH_TOKEN`, `GEMINI_API_KEY`, `LIVE_TOKEN`(없으면 상태 API 검사 없음).

## 이 PC 에서 시험

GitHub Actions 로그는 누구나 보므로 자막·요약이 찍히는 시험은 **이 PC 에서만** 한다.

```bash
cd "/g/내 드라이브/dev/자동화"
set -a; . ./.dev.vars; set +a     # 530 봇 토큰·단체방 번호(.dev.vars, 커밋 안 됨)

# 저장해 둔 자막 기록을 네트워크·전송 없이 재생 → 메시지를 파일로
python -X utf8 automations/speech/run_speech.py --replay "ai-assembly/05_회의발언요약/captions_21_20261105.jsonl" --xcode 21 --out "ai-assembly/05_회의발언요약/replay_out.txt"

# 생중계를 받되 보내지 않고 파일에 쓰기 (+ 자막 기록)
python -X utf8 automations/speech/run_speech.py --xcode 21 --dry-run --out out.txt --record "ai-assembly/05_회의발언요약/captions_21_YYYYMMDD.jsonl"
```

요약은 `claude -p` 를 쓰므로 PC 에서는 `claude login` 상태여야 한다(풀려 있으면 "요약 실패 — 발언 약 N자" 자리표시로 흐름만 끝까지 간다).

## 테스트

```bash
python -m pytest -q automations/speech
bash scripts/npm.sh test -- tests/webcast.test.mjs tests/speech-state.test.mjs
```

## 문제 해결

- **화면에 "회의 일정 캘린더를 읽지 못해…" 배너** — Worker 비밀값 `GOOGLE_REFRESH_TOKEN` 에 캘린더 읽기 권한이 없다. 주말 일정 자동화(`weekend.yml`)가 쓰는 토큰(GitHub Secrets 의 `GOOGLE_*`)과 같은 값으로 Cloudflare Worker 비밀값을 바꾼다. `https://ai-office.smartjohn-d34.workers.dev/api/speech/next` 가 `calendarError: null` 이면 된 것.
- **카드 "다음 실행"이 "캘린더에 잡힌 회의 없음"** — 캘린더에 제목에 `재경위`/`예결위`가 든, 시각이 있는 일정이 없다(종일 일정은 무시).
- **호명을 못 잡아 구간이 합쳐짐** — 자막 기록을 `--replay` 로 돌려 보며 `segmenter.py` 의 `CALL_RE`·`END_RE`·`RECESS_RE` 를 다듬는다. 25분 규칙으로 닫힌 구간은 "(호명 못 잡음)" 표시가 붙는다.
- **답변자 이름이 틀림** — `attendees.yaml` 에 그 사람("이름 직책")을 더한다.
- **같은 묶음이 두 번 옴** — R2 상태(`/api/speech/state?key=<xcgcd>`)의 `sent` 를 본다. 실행이 상태를 저장하기 전(30초 안)에 죽으면 그 사이 보낸 것은 다시 갈 수 있다.
