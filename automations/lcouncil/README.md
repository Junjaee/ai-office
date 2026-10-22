# 지방의회 회의록

지방의회(1단계: 광역의회 16곳) 홈페이지의 회의록 본문을 글자(.txt)로 받아 구글 드라이브에 쌓는다.
회의록은 공개 자료지만 양이 커서(수십 GB) 저장소에는 넣지 않고 건수만 남긴다.

실행은 GitHub Actions(`.github/workflows/lcouncil.yml`)가 맡고, 예약(매일 KST 02:00)은 `worker/schedule.ts`.
대시보드(`/assembly`)의 **▶ 시작** 으로 수동 실행할 수 있다. 끝나면 `../common/report_status.py` 가
`public/status/assembly/lcouncil.json` 을 커밋해 카드 상태가 바뀐다.

## 어떻게 받나

1. `councils.yaml` 의 의회를 차례로 돈다. `template` 가 있는 의회만 받고, 없는 의회는 "준비 중"으로 건너뛴다.
2. 어댑터(`lcouncil_sites.py`)가 **최근 대수·회기부터** 회의록 목록을 훑는다. 그래서 새 회의록이 먼저 들어오고,
   남는 한도만큼 과거분을 이어서 받는다(의회당 `per_run_limit` 건/실행). 과거분 전체는 며칠에 나눠 끝난다.
3. 의회마다 드라이브에 `manifest.json`(받은 회의록 id → 경로)을 두고, 있는 것은 건너뛴다.
   임시회의록(`temp`)은 나중에 확정본으로 바뀌면 다시 받아 교체한다.
4. 저장 경로: `<drive_folder_id>/<의회 이름>/제N대/제K회/<위원회>_<차수>_<날짜>.txt`

### 틀(template)

| 이름 | 쓰는 의회 | 목록 → 본문 |
|---|---|---|
| `ejournal` | 전북·인천·전남광주 (기초의회 다수) | `/assem/search/simple/LoadingSession_Year.json` → `LoadingList.json` → `viewer.do?cdUid=` (`#bodyBox`) |
| `record` | 서울·경남 | `/record/sessionList.do` → `committeeList.do` → `orderList.do` → `recordView.do?key=` (`#canvas`) |

새 틀을 붙일 때는 `lcouncil_sites.py` 에 클래스 하나(`terms / iter_docs / fetch_text`)를 더하고 `build_site` 에 연결한다.
틀 조사 자료: `docs/지방의회/회의록_보유현황.tsv`.

## 실행

```bash
cd "/g/내 드라이브/dev/자동화"
python -X utf8 automations/lcouncil/run_lcouncil.py --dry-run --council jeonbuk --limit 5      # 받을 목록만
python -X utf8 automations/lcouncil/run_lcouncil.py --local /tmp/lc --council seoul --limit 5  # 폴더에 저장(시험)
python -X utf8 automations/lcouncil/run_lcouncil.py                                            # 실제(드라이브, 상태 보고)
```

옵션: `--council <id|all>` `--limit N` `--local <폴더>` `--dry-run`. 워크플로 입력 `council`·`limit` 도 같다.

## 설정 (config.actions.yaml)

- `drive_folder_id` 결과를 둘 드라이브 상위 폴더 id — **비어 있으면 실행이 실패한다**
- `per_run_limit` 의회당 한 번에 받는 최대 건수(기본 300), `request_delay` 요청 간격(1.5초)
- `tasks` 화면 직원 id(`scan`·`fetch`) — `app/workspaces/assembly.ts` 와 같아야 함
- 비밀값은 환경변수로만: `GOOGLE_CLIENT_ID` `GOOGLE_CLIENT_SECRET` `GOOGLE_REFRESH_TOKEN`

## 테스트

```bash
python -m pytest -q automations/lcouncil
```

## 문제 해결

- "대수 목록을 찾지 못함": 사이트 화면이 바뀌었거나 해외 IP 를 막는 경우. 그 의회만 실패로 남고 나머지는 계속 돈다.
  막는 의회가 확인되면 그 의회만 사무실 PC 실행기로 돌리는 워크플로를 따로 둔다.
- "본문이 너무 짧음": 본문 그릇 선택자(`#bodyBox`·`#canvas`)가 안 맞는 경우. 해당 의회 viewer 화면을 열어 그릇 id 를 확인한다.
- 드라이브 토큰 오류: `GOOGLE_REFRESH_TOKEN` 만료. 국회회의록 자동화와 같은 토큰을 쓴다.
