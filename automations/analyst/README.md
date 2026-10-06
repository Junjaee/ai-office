# 주식 분석 (automations/analyst)

매일 한 번 야후 파이낸스에서 종목 자료를 받아 점검표·발굴 관점을 계산하고 사이트(Worker `/api/stock/ingest`)에 올린다. AI 호출 없음. 미국(`us`)과 국내(`kr`)가 같은 코드를 쓰고 시장만 다르다. 설계는 `docs/superpowers/specs/2026-10-05-주식-분석-봇-design.md`.

## 파일

- `run_analyst.py` — 실행 진입점. 시장 표(`MARKETS`)·수집·계산·저장·상태 보고를 묶는다.
- `analyst_sources_us.py` — 야후 파이낸스에서 미국 종목 시세·재무 받기.
- `analyst_sources_kr.py` — 국내 종목(`005930.KS`/`.KQ`)을 같은 방식으로 받고 한글 이름·원화를 붙인다.
- `analyst_sources_edgar.py` — 미국 공시(8-K) 목록. 국내는 공시를 받지 않는다.
- `analyst_sources_news.py` — 관심 종목의 구글 뉴스 기사 제목(국내는 한국어 질의).
- `analyst_metrics.py` — 받은 자료로 종목 기록(record) 만들기.
- `analyst_checks.py` — 점검표 7가지, 발굴 관점, 판(board) 줄.
- `analyst_events.py` — 미국 공시(8-K)를 종류·날짜로 분류.
- `analyst_score.py` — 발굴 관점의 사후 성적(지수 대비) 채점.
- `analyst_publish.py` — 사이트에 읽고 쓰는 얇은 클라이언트.
- `save_opinion.py` — 대화에서 쓴 해석을 사이트에 저장(`.claude/skills/stock-opinion`).
- `rules.yaml` — 문턱값(두 시장 같은 값). `config.actions.yaml` — 실행 설정. `universe_us.txt`·`universe_kr.txt` — 발굴 대상 목록.

## 실행

```bash
python automations/analyst/run_analyst.py --market us --dry-run   # 받아서 계산만, 보내지 않는다
python automations/analyst/run_analyst.py --market kr --dry-run
python automations/analyst/run_analyst.py --market kr              # 실제 저장(사이트 주소·토큰은 설정/환경변수)
```

예약은 Worker(`worker/schedule.ts`)가 맡는다 — 미국 화~토 07:00, 국내 월~금 16:30. 손으로 돌릴 때는 `gh workflow run analyst.yml -f market=kr`. 공개 로그에는 건수만 남기고 종목 코드·이름은 찍지 않는다.

## 대상 목록(`universe_kr.txt`) 다시 뽑기

한 줄은 `코드 거래소  # 이름`(거래소 `KS`=코스피, `KQ`=코스닥). 가끔 사람이 다시 뽑는다.

1. 네이버 시가총액 목록을 쪽별로 받는다: `https://m.stock.naver.com/api/stocks/marketValue/<KOSPI|KOSDAQ>?page=N&pageSize=100` (시가총액 큰 순서).
2. `stockEndType == "stock"` 만 남기고, 종목명이 `우`·`우B`·`우C`·`우(전환)` 로 끝나는 것(우선주 — 이름에 `우` 가 들어간다고 다 우선주는 아니다, `우리금융지주` 는 보통주)과 이름에 `스팩`·`리츠`·`ETF`·`ETN` 이 들어간 것은 뺀다. 코드는 숫자로 시작하는 6자리이고 신규 상장은 `0126Z0` 처럼 끝에 영문이 섞인다(`^[0-9][0-9A-Z]{5}$`, 검사는 `tests/test_universe_kr.py`). 이름에 `리츠` 가 없는 리츠는 걸러지지 않으니 손으로 뺀다.
3. 코스피 상위 250 + 코스닥 상위 100 을 쓴다. 머리 주석 한 줄에 기준일과 출처를 적는다.
4. `python automations/analyst/run_analyst.py --market kr --dry-run` 으로 받아지는지 확인한다.
