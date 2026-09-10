# 국회회의록 자동 수집

코드 원본은 이 저장소(`automations/minutes`)이고, GitHub Actions(`.github/workflows/minutes.yml`)가 매일 09:00(KST)에 `--daily`를 실행해 Google Drive API로 저장한다. 대시보드(`/assembly`)의 **▶ 시작** 버튼이나 Actions 탭의 "Run workflow"로 언제든 수동 실행할 수 있다. 국회 사이트가 해외 IP를 막으므로 워크플로는 자체 실행기(`runs-on: [self-hosted, windows, kr-office]`)에서 돈다(`../runner/README.md`).

실행이 끝나면 `../common/report_status.py` 가 `public/status/assembly/minutes.json`(v2: `run_id`·`request_id`·`tasks[]` = `collect`·`replace`)을 커밋해 화면 상태가 바뀐다. 실패하면 `ok: false` 와 한국어 오류 문구(`../common/errors.py`)를 남긴다.

로컬 실행은 개인 설정 파일을 지정한다: `python automations/minutes/collect_minutes.py --daily --config "G:\내 드라이브\dev\자동화\ai-assembly\01_국회회의록\config.yaml"`

record.assembly.go.kr 의 제21·22대 회의록 PDF를 드라이브 `02. 위원회_회의/_회의록/` 에 저장한다.

## 실행

```bash
cd "/g/내 드라이브/dev/자동화"                  # 저장소 = 이 폴더
CFG="ai-assembly/01_국회회의록/config.yaml"     # 개인 설정 (Open API 키 포함, 공유 금지)
python automations/minutes/collect_minutes.py --daily --config "$CFG"            # 최근 회기만 (매일 실행용, 수 분)
python automations/minutes/collect_minutes.py --backfill 22 --config "$CFG"      # 22대 전체 (1시간 이상)
python automations/minutes/collect_minutes.py --backfill 21 --config "$CFG"      # 21대 전체
python automations/minutes/collect_minutes.py --daily --dry-run --config "$CFG"  # 받지 않고 목록만
```

중단돼도 다시 실행하면 `_manifest.json` 기준으로 이어서 받는다.

## 저장 구조

```
_회의록/제22대/상임위원회/재정경제기획위원회/제22대국회 제438회(임시회) 제1차 재정경제기획위원회(전체회의) (2026.08.20.).pdf
_회의록/제22대/국회본회의/…
_회의록/제22대/국정감사/과학기술정보방송통신위원회/2025/…
_회의록/_manifest.json   수집 상태
_회의록/_수집로그.md      실행 기록
```

임시회의록은 확정본이 올라오면 같은 자리에 덮어쓴다.

## 설정 (config.yaml)

- `drive_root` 저장 루트, `current_th` 매일 확인할 대수, `recent_sessions` 확인할 최근 회기 수
- `request_delay` 요청 간격(초). 사이트 부담을 줄이기 위해 1초 이상 유지
- `open_api_key` 열린국회정보 Open API 인증키. 있으면 `--daily`가 본회의·상임위·특위·예결위 목록을 API로 받는다(요청 수 180회 → 10회 안팎). 국정감사·국정조사는 API가 데이터를 주지 않아 사이트에서 읽고, 임시회의록의 확정 여부도 사이트에서 재확인한다.
- `api_months` API로 확인할 최근 개월 수 (기본 2)

## 목록 출처 정리

| 회의구분 | 전체 수집(--backfill) | 매일(--daily, 키 있음) |
|---|---|---|
| 본회의·상임위·특위·예결위 | 사이트 트리 순회 | Open API (`nzbyfwhwaoanttzje`, `ncwgseseafwbuheph`) |
| 국정감사·국정조사 | 사이트 트리 순회 | 사이트 트리 순회 (최근 회기/연도) |
| 임시 → 확정 교체 확인 | 트리 순회에 포함 | 사이트에서 해당 회기만 재조회 |

Open API 호출은 브라우저 User-Agent가 없으면 400을 돌려준다(코드에서 처리).

## 테스트

```bash
python -m pytest -q
```

## 구조

- `record_site.py` 사이트 요청과 HTML 파싱
- `catalog.py` 받을 목록 생성
- `store.py` 경로·manifest·로그 공통 규칙 + `LocalDriveStore`(동기화 폴더) / `DriveApiStore`(Google Drive API)
- `../common/google_drive.py` Drive API 래퍼, `../common/google_auth.py` 리프레시 토큰 발급(로컬 1회)
- `collect_minutes.py` CLI

## 문제 해결

- `[실패] … PDF가 아닌 응답`: 사이트가 오류 페이지를 준 경우. 다음 실행에서 자동 재시도.
- 목록이 0건: 사이트 HTML 구조가 바뀐 것. `tests/test_site_parse.py`의 픽스처를 새 HTML로 바꿔 파서를 고친다.
- 설계: `../docs/superpowers/specs/2026-09-09-국회회의록-수집-design.md`
