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

1. 가장 최근 거래일의 코스피·코스닥 시가총액을 받는다(KRX Open API 를 쓰면 인증키는 개인 폴더의 `config.yaml` 에 있다 — 값은 어디에도 적지 않는다).
2. 보통주만 남긴다: 종목명에 `우`·`스팩`·`리츠` 가 들어가거나 코드 끝자리가 0 이 아닌 것, ETF 는 뺀다.
3. 코스피 상위 250 + 코스닥 상위 100 을 쓴다. 머리 주석 한 줄에 기준일과 출처를 적는다.
4. `python automations/analyst/run_analyst.py --market kr --dry-run` 으로 받아지는지 확인한다.
