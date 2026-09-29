# kis_record — 한국투자증권 실시간 호가·체결 녹음 + 호가 스냅샷 + 1분봉 수집

설계: `docs/superpowers/specs/2026-09-28-호가-녹음-design.md`. 목적은 "큰 매물이 잡히는 장면"과 매물대를 자료로 남겨 통계로 검증하는 것(`docs/stock/14` 후속). 주문 기능은 없고 계좌번호도 쓰지 않는다.

## 세 도구 (2026-09-28)

| 도구 | 무엇을 | 한도·속도(실측) | 실행 |
|---|---|---|---|
| `record.py` 웹소켓 녹음 | 종목 1~3개의 실시간 호가(10단계)·체결을 건별로 | **연결당 등록 3건, 앱키당 연결 1개** | 평일 08:50~15:35 |
| `kis_snapshot.py` 호가 스냅샷 | '세력이 움직일 수 있는 크기'(시총 300억~5,000억, 기본)만 두 층으로: **A층**(관심·후보·거래대금 상위 150)은 매 바퀴, **B층**(범위 안 나머지 약 1,500)은 남는 예산만큼 돌려 가며. 10단계 호가·잔량·예상체결(71항목)을 REST 조회로 저장 | **조회 약 0.67건/초**(1.5초 간격이 안전선, 문서는 20건/초) → 바퀴당 200건 = 5분(A층 150 + B층 50), B층 전부 한 번 도는 데 약 2.5시간 | 평일 08:55~15:35 |
| `kis_minutes.py` 1분봉 | (종목, 날짜) 의 하루 1분봉 381개(공식 API, **최대 1년 보관**) — 백필(사건 주변) 또는 장 마감 뒤 전 종목 | 하루 1종목 = 4호출 ≈ 4초 → 밤 10시간에 약 9,000 (종목,날짜) | 백필: 밤. 전 종목 하루치: 15:45~약 18:30 |

세 도구는 같은 계좌 조회 한도를 나눠 쓰므로 REST 두 개(`kis_snapshot`·`kis_minutes`)는 잠금 `rest.lock` 으로 동시에 돌지 않게 했고, 백필은 `--stop-at 08:30` 으로 아침 스냅샷 전에 멈춘다. 한도가 풀리면(한투 문의) `--interval` 만 줄인다.

## 구현됨 / 미구현

| 구현됨 | 미구현(설계서에 있음) |
|---|---|
| 접속키·접근토큰(캐시) 발급과 재시도, 웹소켓 구독·재연결·접속키 재발급, 프레임 해석(폭 학습·열 정렬 점검), REST 조회 간격 제한·한도 초과 재시도, csv → Parquet(zstd, 전 열 문자열), 요약 두 벌(로컬용·보고용), 중복 실행 잠금, 절전 방지, 휴장 감지(웹소켓), 텔레그램 한 줄(설정 있을 때만), 작업 스케줄러 등록 스크립트 | 드라이브로 압축본 복사, 장 마감 뒤 자료 검증(체결량 합 대조 — NXT 한계), 세력 흔적 지표로 종목 자동 선별(`--candidates` 파일로 받는 자리만 있음), NXT·통합 TR, 1분봉 매물대 분석(`docs/stock/scripts/kr/` 에 후속) |

## 실측으로 알게 된 것 (2026-09-28, 실전 앱키)

- 웹소켓: 연결 하나에 실시간 등록 3건(4번째부터 `MAX SUBSCRIBE OVER`), 앱키당 연결 1개(새 연결이 붙으면 앞 연결이 끊김, 접속키를 새로 받아도 같음). 공식 예제(40)·공개 자료(41)와 다르다. **녹음 중에는 같은 앱키로 시험 실행을 하지 말 것**.
- REST: 문서는 20건/초지만 실측(간격별 30회) 2.0·1.5초 → 초과 0회, 1.2초 → 6회, 1.0초 → 3회, 0.8초 → 15회(응답도 1.2초로 느려짐). 병렬로 보내도 빨라지지 않음. 그래서 간격 **1.5초(0.67건/초)** 가 기본.
- 대상 범위(2026-09-28 사용자 결정 "시총이 너무 커서 세력이 못 움직이는 종목은 제외"): 14번 연구 2024~ 사건 A 의 종목 시총 중앙값 1,154억, 5,000억 미만이 82%. 현재 상장 보통주 2,549 중 거래정지 104·시총 범위 밖 804 를 빼면 1,641 종목(`--plan` 으로 확인). 시총 5,000억 넘는 곳의 사건은 시장 전체가 움직인 것(삼성전자 등)이라 세력 추적과 무관.
- 실제 웹소켓 메시지의 필드 수는 문서보다 많다(호가 63, 체결 47; 문서 59·46). 초과분은 `EXTRA1..` 열. **초과 필드가 뒤에 붙는지 중간에 끼는지는 확인되지 않았다** — 첫 프레임에서 열 정렬 점검(매도1 > 매수1, 잔량 합, 시각 형식)을 하고 요약 `alignment` 에 남긴다.
- KRX 전용 TR(H0STASP0/H0STCNT0)만 구독하므로 넥스트레이드(NXT) 체결·호가는 들어오지 않는다. 통합 TR(H0UNASP0/H0UNCNT0)로 바꾸는 것은 사용자 결정 사항.
- 1분봉 API 는 요청한 날이 휴장이면 그 전 거래일 자료를 돌려준다(예: 2026-09-25 추석 → 09-23). 수집기는 날짜가 다른 행을 버린다.

### 한도 확인 절차 (장 마감 뒤 또는 개장 전, 한 번)
1. 30분 이상 어떤 연결도 없이 둔다. 2. 새 접속키 → 연결 1개 → 종목을 1건씩 3초 간격으로 등록하며 몇 번째에서 `MAX SUBSCRIBE OVER` 가 나오는지 적는다. 3. 끝낼 때 등록한 것 전부 해제(tr_type 2)를 보내고 닫는다. 4. 여전히 3이면 KIS Developers 포털 공지·FAQ 에서 "실시간 등록 건수"를 찾고 1:1 문의를 보낸다.
문의 문구(값은 넣지 않는다): "KIS Developers 실전투자 앱키로 웹소켓(ops.koreainvestment.com:21000)에 접속해 국내주식 실시간호가(H0STASP0)·체결가(H0STCNT0)를 등록하면 한 세션에 3건까지만 되고 4번째부터 MAX SUBSCRIBE OVER 가 옵니다. 공식 예제와 안내에는 세션당 41건으로 되어 있습니다. 또 REST 조회는 초당 20건이라고 안내돼 있는데 초당 1~2건에서도 EGW00201(초당 거래건수 초과)이 옵니다. 제 계정의 실시간 등록 한도·REST 조회 한도와 늘릴 수 있는 방법을 알려 주세요. wss(TLS) 접속 주소가 있는지도 알려 주세요."

## 파일

- `kis_client.py` — 웹소켓: 접속키 발급(재시도), 구독 메시지, 프레임 해석(폭 학습·암호화/비정상 분류), 열 정렬 점검, 재연결 세션(`run_session`).
- `kis_rest.py` — REST 공통: 접근토큰 캐시(`%USERPROFILE%\ai-office-data\kis-record\token.json`), 간격 제한, 한도 초과·5xx·토큰 만료 재시도, `asking_price()`·`day_minutes()`.
- `record.py` — 웹소켓 하루 실행기(`--mode both|asp`, 잠금, 절전 방지, 휴장 감지, Parquet, 요약, 텔레그램).
- `kis_snapshot.py` — 호가 스냅샷 실행기(`--n 150`(A층) `--cap-min 300 --cap-max 5000`(억) `--cycle 300`(바퀴 초) `--interval 1.5`, `--candidates` 파일, `--no-tier-b`, `--plan`(대상만 세기), `--sweeps` 시험).
- `kis_universe.py` — 네이버 종목 목록(시총·거래대금·거래정지)으로 두 층 대상 만들기(`fetch_listing`·`build_universe`·`Universe.sweep_plan`).
- `kis_minutes.py` — 1분봉 수집(`--targets csv | --eod`, `--stop-at`, 재시작 가능 `done.txt`), `make_targets()`(사건 + 짝 종목 목표 목록).
- `kis_pick.py` — 종목 고르기(`kis_watchlist` → 거래대금 상위 → 어제 종목). 관심 종목은 따옴표 없이 적어도 문자열로 읽는다.
- `install_task.ps1` + `run_task.cmd` — 작업 스케줄러 등록(사용자 확인 뒤).
- `tests/` — 네트워크 없는 시험 14개: 저장소 폴더에서 `python -m pytest -q automations/kis_record/tests`
- 필요한 패키지: `websockets>=13`, `pyarrow>=15`, `pyyaml`, `requests`, `pandas`(목표 목록).

## 비밀값·기록 규칙

- `ai-home/02_주식신호/config.yaml`(gitignore) 의 `kis_app_key`·`kis_app_secret`. 코드는 환경변수로만 읽고 값을 찍지 않는다. **DEBUG 로깅을 켜지 말 것**. 접속키는 평문 `ws://` 로 오간다(한투 설계).
- 관심 종목 `kis_watchlist: ["000660", "005930"]`. 텔레그램 `telegram_bot_token`·`telegram_chat_id` 가 있으면 끝날 때 한 줄.
- 저장 위치 `%USERPROFILE%\ai-office-data\kis-record\` — `YYYY-MM-DD\run_HHMMSS\`(웹소켓), `YYYY-MM-DD\snap_HHMMSS\book.parquet`(스냅샷), `minutes\YYYY-MM-DD\<종목>.parquet`(분봉). 종목코드가 든 `summary.json` 은 로컬에만, 저장소·텔레그램에는 `safe_summary.json`(건수만).
- 용량: 웹소켓 3건 하루 15~40MB, 스냅샷 400종목 하루 약 3만 행 수 MB, 분봉 종목·일당 381행(수십 KB). 드라이브 복사는 첫 주 실측 뒤 결정.
- PC 조건: 녹음 시간에 로그인 상태(잠금 화면은 됨), 전원 연결. 드라이브(G:)가 늦게 붙어도 10분까지 기다린다.

## 실행

```bash
python automations/kis_record/record.py --codes 005930,000660 --minutes 2                 # 웹소켓 시험
python automations/kis_record/kis_snapshot.py --codes 005930,000660 --sweeps 1             # 스냅샷 시험
python automations/kis_record/kis_snapshot.py --plan                                       # 오늘 대상 세어 보기(호출 없음)
python automations/kis_record/kis_snapshot.py --n 150 --until 15:35                        # 하루 스냅샷(A층 150 + B층 회전)
python automations/kis_record/kis_minutes.py --targets <목표.csv> --stop-at 08:30          # 밤새 백필
python automations/kis_record/kis_minutes.py --eod                                         # 오늘 전 종목 1분봉(장 마감 뒤)
powershell -ExecutionPolicy Bypass -File automations/kis_record/install_task.ps1           # 스케줄러 3개 등록(사용자 확인 뒤)
```
