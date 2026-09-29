# toss_record — 토스증권 Open API 로 실시간 호가·체결 녹음, 1분봉(2022-11~)·일별 수급(2019-04~) 백필

설계: `docs/superpowers/specs/2026-09-28-호가-녹음-design.md` 7절. 목적은 kis_record 와 같다(세력 흔적을 자료로 남겨 통계로 검증). 주문 기능은 없다. 2026-09-29 사용자 결정 "토스부터 붙여보자".

## 무엇을 받나 (2026-09-29 실측)

| 도구 | 무엇을 | 한도(공식·실측) | 실행 |
|---|---|---|---|
| `record_toss.py` 실시간 녹음 | 국내 10단계 호가(매 프레임 전체 스냅샷, KRX+NXT 통합)·체결(가격·수량·시각) | 계정당 연결 2개 × 연결당 100건 → **호가+체결 100종목** 또는 호가만 200종목. 시험: 4종목 1분에 호가 4,353·체결 1,056행 | 평일 08:55~15:35 |
| `toss_candles.py` 1분봉 백필 | (종목, 날짜) 하루 1분봉을 KIS 와 같은 열 이름으로 저장 | **국내 2022-11-23 부터** 제공. 200봉/호출·초당 20건 → 1년치 1종목 약 25초, 1,641종목 1년 약 11시간 | 밤 |
| `toss_flows.py` 수급 백필 | 투자자별 매매동향(개인·외국인·기관 4분류 + 기관 세부 7, 외국인 보유, CFD), 프로그램매매, 공매도, 신용, 대차 — 일별 | **투자자별·프로그램·공매도 2019-04-01 부터**, 신용 2023-04, 대차 2021-04. 100일/호출·초당 15건 → 1종목 5종 약 80호출, 1,641종목 약 2.5시간 | 밤 또는 낮 |
| `probe.py` 점검 | 토큰·호가 단계·보관 기간·종목 수 | 호출 90회로 끝 | 처음 한 번 |

- 조회 한도(공식): 시세 그룹 초당 15건, 차트 초당 20건, 현재가는 한 호출에 200종목. 응답 헤더 `X-RateLimit-Remaining` 이 0 이면 `X-RateLimit-Reset` 초 쉰다. 429 면 `Retry-After`.
- **허용 IP 필수**: WTS 설정 > Open API 에 이 PC 공인 IP 를 등록해야 한다(아니면 403). IP 가 바뀌면 다시 등록. GitHub 서버에선 못 쓴다.
- **클라이언트당 토큰 1개**: 새로 발급하면 이전 토큰이 즉시 무효. 그래서 `%LOCALAPPDATA%\toss-record\token.json` 하나를 모든 프로그램이 공유하고, 만료 직전·401 일 때만 재발급한다(재발급 전에 파일을 다시 읽어 다른 프로그램이 먼저 갱신했으면 그것을 쓴다).
- 체결 메시지에 매수/매도 구분·체결강도가 없다. 직전 호가 스냅샷과 대조해(체결가 ≥ 매도1 이면 매수 체결) 추정하는 것은 분석 단계에서 한다.
- 1분봉은 통합(KRX+NXT) 거래량이고 08:01~20:00 봉이 온다. 저장은 정규장(09:00~15:30 시작 봉)만 기본(`--all-sessions` 로 전부). 토스 timestamp 는 봉 종료 시각이라 봉 시작 시각으로 바꿔 저장한다.
- 자료는 **본인 매매 목적만, 제3자 배포 금지**(FAQ 데이터 이용 정책). 원자료는 이 PC 에만 두고 저장소에는 건수·집계값만.

## 사이트 실시간 화면 (2026-09-29)

- 녹음기는 5초마다 종목별 집계(체결강도·잔량비·가장 큰 벽·벽 신호)와 10단계 호가·최근 체결 20건을 사이트 `/api/live` 로 보낸다(`live_board.py`). 백필 두 개는 60초에 한 번 살아있음 신호만(`live_post.Heart`). 사이트 쪽은 `worker/live.ts`(R2 `ai-office-live`), 화면 `app/office/LiveBoard.tsx`(`/home/live/orderbook`), 카드 상태 규칙 `app/status-rules.ts` 3.7절.
- 설정: `config.yaml` 의 `live_url`(생략 시 운영 사이트, `off` 면 전송 안 함), `live_token`(선택 — 사이트에 Worker 비밀값 `LIVE_TOKEN` 을 뒀을 때만 같은 값. 사용자 결정 2026-09-29: 토큰 없이 운영). `--no-live` 로 끌 수 있다.
- 체결 방향은 추정이다: 직전 호가 스냅샷 기준으로 체결가 ≥ 매도1 → 매수, ≤ 매수1 → 매도, 그 사이 → 중간(통합 호가라 KRX·NXT 가격이 겹칠 때 생김).

## 다른 PC(남는 PC)로 옮기기 (사용자 계획 2026-09-29)

이 폴더는 구글 드라이브 동기화 폴더라 저장소·개인 설정(`ai-home/02_주식신호/config.yaml`)이 그 PC 에도 그대로 내려온다. 그 PC 의 Claude Code 에서 할 일:

1. Python 3.11 이상 + `pip install websockets pyarrow pandas pyyaml requests`. (Windows 가 아니어도 됨 — 잠금·절전 방지는 윈도우에서만 켜진다)
2. 토스 WTS 설정 > Open API > 허용 IP 에 그 PC 의 공인 IP 추가(`curl https://api.ipify.org`). 한투는 IP 등록 없음.
3. **한 계정의 토스 프로그램은 한 PC 에서만** — 이 PC 의 작업 스케줄러(`Toss-record`)와 백필을 먼저 끈다(`install_task.ps1 -Remove`). 두 PC 가 동시에 돌리면 토큰·연결을 서로 끊는다.
4. 자료 저장 위치는 그 PC 의 `%LOCALAPPDATA%\toss-record`(리눅스는 홈 아래). 이 PC 에 쌓인 자료(2026-09-29~)는 필요하면 복사.
5. 절전·자동 재부팅 끄고 전원 연결. `install_task.ps1` 로 08:55 등록.

## 파일

- `toss_rest.py` — 토큰(파일 공유)·유량·재시도, `orderbook()`·`prices()`·`trades()`·`candles()`·`candles_all()`·`daily_series_all()`·`stocks_all()`.
- `toss_ws.py` — 웹소켓: 선언형 구독, PING 60초, 재연결, 호가 평탄화(`flatten_book`), `split_codes()`.
- `record_toss.py` — 하루 녹음기(`--codes | --picks 파일 | --auto`(후보 파일 + 시총 범위 안 거래대금 상위), `--mode both|book|trade`, `--minutes` 시험). 저장 `%LOCALAPPDATA%\toss-record\YYYY-MM-DD\run_HHMMSS\{orderbook|trade}_<코드>.parquet`, 요약 두 벌(summary·safe_summary).
- `toss_candles.py` — 1분봉 백필(`--targets csv | --codes | --universe`, `--since/--until`, `--stop-at`, 재시작 가능 `minutes/done.txt`). 저장 `minutes\YYYY-MM-DD\<코드>.parquet`(KIS 열 이름).
- `toss_flows.py` — 수급 백필(`--codes | --universe | --all-listed`, `--kinds`, `--since`, `--refresh`). 저장 `flows\<종류>\<코드>.parquet`(중첩 필드는 점 연결 이름, 전 열 문자열).
- `start_backfill.ps1` — 분봉(목표 목록) → 수급(시총 범위 전 종목) 을 숨긴 창으로 차례로. `run_chain.py` 가 순서대로 돌린다(REST 작업은 `rest.lock` 으로 하나만).
- `install_task.ps1` — 작업 스케줄러 등록(Toss-record 08:55, 사용자 확인 뒤).
- `tests/` — 네트워크 없는 시험 9개: `python -m pytest -q automations/toss_record/tests`

## 비밀값

`ai-home/02_주식신호/config.yaml`(gitignore) 의 `toss_client_id`·`toss_client_secret`. 코드는 환경변수로만 읽고 값을 찍지 않는다. 키를 재발급하면 이전 키로 받은 토큰이 401 이 되니 config 를 바꾼 뒤 `token.json` 을 지운다.

## 실행

```bash
python automations/toss_record/probe.py                                                   # 점검
python automations/toss_record/record_toss.py --codes 005930,000660 --minutes 1            # 녹음 시험
python automations/toss_record/record_toss.py --auto --candidates <파일> --until 15:35       # 하루 녹음(100종목)
python automations/toss_record/toss_candles.py --codes 005930 --since 2025-09-01           # 분봉
python automations/toss_record/toss_flows.py --codes 005930                                # 수급 5종
powershell -ExecutionPolicy Bypass -File automations/toss_record/start_backfill.ps1        # 밤 백필 묶음
```
