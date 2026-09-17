# 상임위 메일 (`mail`)

재경위·예결위에서 온 **새 메일을 5분마다 확인**해 텔레그램으로 알리고, 지메일에서 위원회 라벨을 붙여
받은편지함에서 빼 준다(= 그 라벨 폴더로 정리).

- 사무실: 국회(`/assembly`) · 부서 `qa`(상임위 메일팀) · 직원 `check`(새 메일 확인) `notify`(알림·정리)
- 실행: GitHub 서버(`ubuntu-latest`), `.github/workflows/mail.yml`, 예약 `*/5 * * * *`
- 개인 메모: `ai-assembly/04_상임위메일/README.md`

## 어떻게 도는가

1. `config.actions.yaml` 의 `committees` 규칙마다 지메일을 찾는다.
   검색어에 `-label:"<라벨>"` 과 `newer_than:<lookback_days>d` 를 자동으로 붙이므로,
   **이미 라벨이 붙은 메일 = 처리 끝**으로 보고 건너뛴다(중복 알림 방지).
2. 찾은 메일을 받은 시각 순으로 모아 **텔레그램 한 통**으로 보낸다(제목·보낸사람·첨부 이름·바로가기 링크).
3. 보내기가 성공하면 메일마다 라벨을 붙이고 `INBOX` 를 뗀다. 라벨이 없으면 만든다.
   순서가 중요하다 — 보내기에 실패하면 라벨이 안 붙어 다음 실행에서 다시 시도한다.

## 공개 저장소 주의 (사용자 결정 2026-09-16)

이 저장소는 공개다. 그래서 **메일 제목·보낸사람은 텔레그램으로만** 보내고,
커밋되는 상태 파일(`public/status/assembly/mail.json`)·실행 일지에는 `mail_gmail.safe_lines()` 가 만든
**위원회별 건수만**("재경위 2건") 남긴다. `log_lines` 에 제목을 넣지 말 것.

또 5분마다 돌기 때문에 **새 메일이 없는 실행은 상태 파일을 쓰지 않는다**(`skip_report`).
카드는 마지막으로 메일을 처리한 때를 계속 보여 준다. 사무실 설정에 `schedule` 을 넣지 않은 이유도
이것이다 — 조용한 날이 이어지면 "예약 놓침"으로 잘못 보인다.

## 설정 (`config.actions.yaml`)

- `committees[].label` 지메일 라벨 이름, `committees[].query` 지메일 검색어(`{a b}` = a 또는 b).
- `lookback_days`(기본 7) 며칠 안의 메일만, `max_per_run`(기본 20) 위원회마다 한 번에 처리할 최대 수.
- `tasks: [check, notify]` — `app/workspaces/assembly.ts` 의 직원 id 와 같아야 한다.

**위원회를 더하려면** `committees` 에 두 줄을 추가하면 된다. 코드는 고치지 않는다.

예결위는 2026-09-16 기준 받은 메일이 아직 없어 주소를 몰라서 제목·본문으로 잡는다
(`from:assembly.go.kr {예결위 예산결산특별위원회}`). 실제 메일이 오면 발신 주소를 확인해
`from:<주소>` 로 바꾸는 편이 정확하다.

## 비밀값 (GitHub 저장소 Settings → Secrets and variables → Actions)

- `GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` · `GOOGLE_REFRESH_TOKEN` 공용 구글 토큰(`gmail.modify` 권한 포함)
- `NOTICE_530_BOT_TOKEN` 보내는 봇 — **@notice_530_bot**(530호 알림 공용). 캘린더 봇(`TELEGRAM_BOT_TOKEN`)은 주말 일정 전송에만 쓴다(사용자 결정 2026-09-17).
  앞으로 530호 알림 자동화를 더 만들면 같은 봇을 쓰고, 받는 사람만 `TELEGRAM_CHAT_ID_*` 로 나눈다
- `TELEGRAM_CHAT_ID_MAIL` 받는 사람의 대화방 번호 — 주말 일정 알림(`TELEGRAM_CHAT_ID`)과 **다른 사람**이라 따로 둔다

## 시험해 보기

Actions → "상임위 메일" → Run workflow → "시험 실행"을 켜면, 보낼 글이 실행 기록에만 찍히고
텔레그램으로 가지 않으며 라벨도 붙지 않는다.

```bash
python -m pytest -q automations/mail          # 네트워크 없이 도는 테스트
python automations/mail/run_mail.py --dry-run # 실제 지메일을 훑고 보낼 글만 출력 (GOOGLE_* 환경변수 필요)
```
