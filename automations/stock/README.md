# 주식 신호

매일 아침(미국 장 마감 뒤, KST 06:30) 시장 상태(SPY 200일선·VIX·환율)를 텔레그램으로 한 통 보내고, **분기가 바뀐 첫 실행에는** SEC 공시 재무값으로 S&P 500 구성종목의 **가치+주주환원** 점수를 매겨 상위 20종목을 한 통 더 보낸다. 주문은 사람이 미래에셋 앱에서 한다.

근거와 검증: `docs/stock/12-재무제표-팩터-검증.md`(2011~2026 CAGR 21.3% / 낙폭 −19% / 샤프 1.21, SPY 14.1% / −34% / 0.86). 설계: `docs/superpowers/specs/2026-09-22-주식-신호-자동화-design.md`.

실행은 GitHub Actions(`.github/workflows/stock.yml`)가 맡고, 대시보드(`/home`)의 **▶ 시작** 버튼이나 Actions 탭 "Run workflow"로 언제든 수동 실행할 수 있다. 끝나면 `../common/report_status.py` 가 `public/status/home/stock.json` 을 커밋해 화면 상태가 바뀐다.

## 실행

```bash
cd "/g/내 드라이브/dev/자동화"                      # 저장소 = 이 폴더
python automations/stock/run_stock.py --dry-run                 # 시험 (상태 파일 안 씀, 보내지 않음)
python automations/stock/run_stock.py --dry-run --screen --facts <companyfacts.zip 경로>   # 분기 종목까지
python automations/stock/run_stock.py --find-chat --dry-run     # 봇에게 말을 건 대화방 번호
python automations/stock/run_stock.py                           # 실제
```

## 어떻게 도나

| 직원 | 하는 일 |
|---|---|
| `quotes` | 위키 구성종목 → 야후 시세 18개월(구성종목 + SPY·VIX·환율). 못 받은 종목이 5% 넘으면 그날은 신호 없음. 분기 첫 실행이면 SEC companyfacts.zip(1.4GB)을 받아 구성종목만 해석 |
| `scan` | 시장 상태. 분기면 점수(가치 4비율 평균 + 주주환원) → 상위 20 |
| `notify` | 텔레그램 1통(+1통). 상태 파일에는 날짜·건수만 — **종목명은 텔레그램에만** |

- 같은 미국 날짜로 이미 보냈으면(상태 파일의 `기준일`) 다시 보내지 않는다 → 미국 휴장일·중복 실행에 안전.
- 분기 판정은 상태 파일의 `[분기] YYYY-Qn` 줄로. 1·4·7·10월 첫 실행에 자동.
- 재무값은 공시일(`filed`)이 기준일 이전인 것만 쓴다(미래 정보 없음). 회계기준 변경으로 태그가 바뀐 회사는 후보 태그를 합쳐 잇는다.

## 설정 (config.actions.yaml)

- `top_n` 20 · `weight` equal/invvol · `observe_until` 관찰 모드 표시 종료일
- `max_fail_rate` 시세 실패 허용 비율 · `min_candidates` 분기 알림 최소 후보 수
- `facts_cache` companyfacts.zip 둘 곳(비우면 임시 폴더) · `local_secrets` 이 PC 시험용 비밀값 파일(gitignore)
- `tasks` 화면 직원 id — `app/workspaces/home.ts` 와 같아야 함
- 비밀값은 환경변수로만: `TELEGRAM_BOT_TOKEN_JUNJAE_BOT`, `TELEGRAM_CHAT_ID_STOCK` (봇 junjae_bot)

## 테스트

```bash
python -m pytest -q automations/stock
```

## 문제 해결

- "시세를 받아오지 못했어요 (야후가 막았을 수 있어요)" — GitHub 서버 주소가 야후에 막힌 것. 워크플로 `runs-on` 을 사무실 PC(`[self-hosted, windows, kr-office]`)로 바꾼다.
- "텔레그램 봇·받는 분 설정이 없어요" — GitHub Secrets 에 두 값이 있는지, 받는 사람이 봇에게 먼저 말을 걸었는지.
- 분기 알림이 안 옴 — 상태 파일 `[분기]` 줄이 이번 분기면 이미 보낸 것. 강제로 보려면 `--screen`.
- SEC 묶음 내려받기가 느림 — 분기에 한 번뿐이고 60분 안에 끝난다. 워크플로 `timeout-minutes: 90`.
