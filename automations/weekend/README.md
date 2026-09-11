# 주말 일정 알림 (weekend)

매주 목요일 17:00(KST)에 **530호 일정 (비공개)** 구글 캘린더의 이번 주 토·일 일정을 모아, 사용자 텔레그램 봇으로 받는 분(1:1)에게 보낸다. 국회 사무실 일정·의사일정팀 카드.

| 직원 | 하는 일 |
|---|---|
| `fetch` 주말 일정 모으기 | Calendar API 로 오늘 이후 가장 가까운 토·일 일정 읽기(반복 일정 펼침, 취소 제외, 여러 날 일정은 날마다) |
| `send` 텔레그램 보내기 | 날짜별로 `시간  제목 @ 장소` 로 정리해 보내기(4096자 넘으면 잘라서) |

## 보내는 내용 (공개 범위)

- 제목·장소에 `reveal_keywords`(기본 `동탄`) 단어가 든 일정은 그대로: `· 16:00~17:00  동탄맨 콘텐츠 촬영`.
- 나머지는 누구와 무엇을 하는지 빼고 종류만: `· 09:30~10:30  등산 일정`, `· 19:00~21:00  저녁 식사 일정`.
  종류는 등산·골프·운동·결혼식·조문·식사(시각으로 아침·점심·저녁)·회의·방송·촬영·행사, 안 맞으면 "기타 일정" (`weekend_calendar.py` 의 `KINDS`).
- 대시보드 실행 기록에 남는 일정 목록도 같은 규칙으로 가린다.

## 실행

- 예약: `.github/workflows/weekend.yml` cron `0 8 * * 4` (매주 목 17:00 KST), GitHub 서버.
- 수동: 대시보드 카드 ▶ 시작 = 지금 바로 보내기.
- 시험 실행: Actions → "주말 일정 알림" → Run workflow → "시험 실행" 켜기 → 보낼 글이 실행 기록에만 찍힌다.
- 대화방 찾기: 같은 화면에서 "대화방 찾기" 켜기 → 봇에게 '시작'을 누른 대화방 번호가 실행 기록에 찍힌다.
  아무도 안 나오면(같은 봇을 다른 프로그램이 읽는 경우) 받는 분이 @userinfobot 에서 자기 Id 를 확인해 `TELEGRAM_CHAT_ID` 로 넣는다.

## 비밀값 (GitHub Secrets)

- `TELEGRAM_BOT_TOKEN` 보내는 봇 토큰, `TELEGRAM_CHAT_ID` 받는 분 대화방 번호.
- `GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` · `GOOGLE_REFRESH_TOKEN` 공용 토큰. **캘린더 읽기 권한**이 있어야 한다(`python automations/common/google_auth.py <client_secret.json> <출력 파일>` 로 다시 발급, 권한 목록은 그 파일의 `SCOPES`).
- 봇 토큰은 오류 문구·실행 기록에 남기지 않는다(`***` 로 가림).

## 설정 (config.actions.yaml)

- `calendar_id` 읽을 캘린더, `calendar_name` 메시지 첫 줄 이름, `tasks: [fetch, send]`.
- 사무실 설정(`app/workspaces/assembly.ts`)에는 `schedule` 을 넣지 않는다 — 주 1회라 36시간 기준 "예약 놓침" 경고가 잘못 뜬다. 카드 문구는 `next_run`.

## 문제 해결

- "텔레그램으로 보내지 못했어요" + `bot can't initiate conversation` → 받는 분이 봇에서 '시작'을 누르지 않았다.
- "텔레그램 봇·받는 분 설정이 없어요" → `TELEGRAM_BOT_TOKEN`·`TELEGRAM_CHAT_ID` 비밀값이 비어 있다.
- "구글 캘린더를 읽지 못했어요" → HTTP 403 이면 공용 토큰에 캘린더 권한이 없다(다시 발급, Google Cloud 에서 Calendar API 사용 설정), 404 면 `calendar_id` 확인.

## 테스트

```bash
python -m pytest -q automations/weekend
```

네트워크 없이 돈다(캘린더·텔레그램은 가짜).
