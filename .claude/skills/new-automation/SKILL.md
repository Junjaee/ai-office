---
name: new-automation
description: AI 오피스에 새 자동화(파이썬 + GitHub Actions + 대시보드 카드)를 국회회의록 수집과 같은 방식으로 추가한다. "새 자동화", "자동화 만들어줘", "/new-automation" 에 사용.
---

# 새 자동화 추가 절차

국회회의록 수집(`automations/minutes`)과 똑같은 구조로 만든다. **템플릿을 복사해 빈칸만 채운다.** 새로 설계하지 않는다.

- 저장소 = **이 폴더** `G:\내 드라이브\dev\자동화` (이하 `REPO`. git 저장소이자 드라이브 동기화 폴더, GitHub `Junjaee/ai-office`). 코드도 여기 두고, 커밋·푸시하면 Actions 가 돈다.
- 템플릿: `templates/automation/` (이 폴더 안)
- 참고 구현(읽을 필요가 있을 때만): `automations/minutes/collect_minutes.py`, `automations/common/report_status.py`

## 0. 시작 전 질문 (한 번에 묻고, 답을 받은 뒤 진행)

1. **무엇을 하는 자동화인가?** 입력(사이트·API·메일·파일)과 결과물(드라이브 폴더·시트·알림). 하위 작업(직원)을 1~3개로 나눌 수 있으면 이름까지. 예: 기사 수집 → `collect`(기사 수집), `digest`(요약 정리)
2. **어느 사무실·부서인가?** 사무실 `assembly`/`home`, 부서 id(`research brand strategy1 qa strategy2 reels carousel partner finance review ops secretary`). 부서 이름은 `REPO/app/workspaces/<사무실>.ts` 의 `DEPARTMENTS` 에서 보여 주고 고르게 한다.
3. **언제 도는가, 비밀값은?** 예약 시각(KST) 또는 "수동만". 필요한 비밀값(구글 드라이브면 `GOOGLE_*`, Open API 면 `OPEN_API_KEY`, 그 외 새 키).

**실행 위치는 묻지 않고 규칙으로 정한다(사용자 결정 2026-09-10):** 기본은 **GitHub 서버(`ubuntu-latest`)**. 국회 사이트(assembly.go.kr)처럼 해외 IP 를 막는 곳이나 이 PC 에만 있는 파일·프로그램을 써야 할 때만 **사무실 PC(`[self-hosted, windows, kr-office]`)**. 어느 쪽인지와 이유를 결정 표에 적는다.

결정 사항을 표로 정리해 확인받은 뒤 1단계로 간다. 개인 폴더 이름(`ai-<사무실>/NN_<이름>`)도 표에 넣는다. id 는 영문 소문자 한 단어(예 `news`, `mail`, `ledger`).

## 1. 드라이브 개인 폴더 만들기

작업 폴더 `G:\내 드라이브\dev\자동화\` 는 **사무실별 상위 폴더 → 자동화별 하위 폴더** 구조다(사용자 결정 2026-09-10). 코드는 넣지 않고 개인 설정·메모만 둔다.

```
자동화/ai-<사무실 id>/NN_<한글 이름>/     예: ai-assembly/01_국회회의록/, ai-home/01_가계부/
    ├─ README.md     무엇을 하는지, 저장소 위치, 이 PC 에서 직접 실행하는 명령
    └─ config.yaml   개인 설정(키·개인 경로). 공유·복사 금지. 없으면 만들지 않는다
```

- 상위 폴더 이름은 `ai-` + 사무실 id (`ai-assembly`, `ai-home`, `ai-stock` …). 없으면 먼저 만든다.
- `NN` 은 그 사무실 안에서 이어지는 번호(01, 02 …). 기존 폴더를 `ls` 로 보고 다음 번호를 쓴다.
- README 에는 코드 경로 `automations/<id>/` (이 저장소 안)와 대시보드 주소를 적는다.

## 2. 템플릿 복사·치환

```bash
cd "/g/내 드라이브/dev/자동화"            # = REPO (이 폴더)
mkdir -p automations/<id>/tests .github/workflows
cp templates/automation/run_TEMPLATE.py automations/<id>/run_<id>.py
cp templates/automation/config.actions.yaml automations/<id>/config.actions.yaml
cp templates/automation/tests/test_run.py automations/<id>/tests/test_run_<id>.py
cp templates/automation/README.md automations/<id>/README.md
cp templates/automation/workflow.yml .github/workflows/<id>.yml
touch automations/<id>/tests/__init__.py
```

치환 자리: `__ID__`(자동화 id) `__NAME__`(카드 제목) `__DEPT__`(부서 id) `__WORKSPACE__`(사무실 id) `__CRON__`(UTC cron, 예 KST 09:00 = `0 0 * * *`) `__RUNS_ON__`(기본 `ubuntu-latest`, 사무실 PC 면 `[self-hosted, windows, kr-office]`) `__NEXT_RUN__`(화면 문구, 예 `매일 09:00`). 파이썬 한 줄로 전부 바꾼다:

```bash
python - <<'PY'
import pathlib,re
rep={"__ID__":"<id>","__NAME__":"<이름>","__DEPT__":"<부서>","__WORKSPACE__":"<사무실>","__CRON__":"0 0 * * *","__RUNS_ON__":"ubuntu-latest","__NEXT_RUN__":"매일 09:00"}
for p in [*pathlib.Path("automations/<id>").rglob("*"), pathlib.Path(".github/workflows/<id>.yml")]:
    if p.is_file():
        s=p.read_text(encoding="utf-8")
        for k,v in rep.items(): s=s.replace(k,v)
        p.write_text(s,encoding="utf-8")
PY
```

사무실 PC 에서 돌리는 경우에만 워크플로에서 (1) `setup-python` 단계를 지우고 (2) 주석 처리된 `defaults.run.shell`(-NoProfile PowerShell) 블록의 주석을 푼다. GitHub 서버면 템플릿 그대로(bash) 쓴다.

## 3. 실제 작업 채우기

`run_<id>.py` 의 `do_work()` 하나만 구현한다. 규칙:
- 반환값 `{"counts": {...}, "lines": [...], "tasks": {task_id: (ok, "한 줄")}}`. `counts` 에는 `total` 을 넣으면 화면에 "누적 N건"으로 나온다.
- 예외는 그냥 던진다. 바깥(`run()`)이 한국어 문구로 바꿔 상태 파일에 남기고 실패로 끝낸다. 새 종류의 오류 문구가 필요하면 `automations/common/errors.py` 의 `to_korean` 에 한 줄 추가.
- 비밀값은 환경변수로만 읽는다(`os.environ`). 설정 파일에 넣지 않는다.
- 사이트 요청은 1초 이상 간격, 재시도 3회(`minutes/record_site.py` 참고).
- 구글 드라이브 저장은 `automations/common/google_drive.py` 의 `DriveClient` 를 쓴다(새로 만들지 않는다).

`config.actions.yaml` 의 `tasks:` 는 화면 직원 id 와 같아야 한다(4단계).

## 4. 사무실 설정에 등록

`REPO/app/workspaces/<사무실>.ts` 의 `AUTOMATIONS` 에서 같은 id 항목이 이미 있으면 `workflow`·`schedule` 만 채우고, 없으면 추가:

```ts
{ id: "<id>", dept: "<부서>", name: "<이름>", workflow: "<id>.yml", schedule: "매일 09:00",
  tasks: [
    { id: "collect", name: "<업무명>", role: "<한 줄 설명>" },
  ] },
```

- `tasks[].id` = yaml `tasks:` = `do_work` 가 돌려주는 `tasks` 키. `tests/workspaces.test.mjs` 가 불일치를 잡는다.
- 그 부서가 `HIDDEN_DEPARTMENTS` 에 있으면 뺀다. 부서 하나에 직원(tasks) 합계 6명 이하.

## 5. 비밀값·실행기

- 새 비밀값이 필요하면 사용자에게 **GitHub 저장소 Settings → Secrets and variables → Actions** 에 넣게 안내한다. 값은 채팅에 받지 않는다. 워크플로 `env:` 에 이름을 추가한다.
- 사무실 PC 실행기(`main-pc`, kr-office)는 등록돼 있다. 꺼져 있으면 실행이 대기 상태로 남고 화면에 🟡 배너가 뜬다. GitHub 서버 실행은 PC 상태와 무관하다.

## 6. 검증 (전부 통과해야 다음으로)

```bash
cd "/g/내 드라이브/dev/자동화"
python -m pytest -q automations
python automations/<id>/run_<id>.py --dry-run          # 상태 파일을 쓰지 않는 시험 실행
bash scripts/npm.sh test && bash scripts/npm.sh tsc && bash scripts/npm.sh build   # node_modules 는 드라이브 밖 로컬 작업 폴더
```

로컬 `--dry-run` 이 실제 데이터를 한 번 훑고 요약을 찍어야 한다. 실패하면 여기서 고친다.

## 7. 커밋·배포·실제 실행

1. `git add -A && git commit && git push origin main` (커밋 메시지 한국어, 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`).
2. 2~3분 뒤 사이트에 새 카드와 직원이 생겼는지 확인 (`curl https://ai-office.smartjohn-d34.workers.dev/api/status?ws=<사무실>`).
3. 사이트의 **▶ 시작** 과 같은 요청으로 1회 실행하고 끝까지 본다:
   ```bash
   curl -s -X POST https://ai-office.smartjohn-d34.workers.dev/api/run -H "Content-Type: application/json" -H "Origin: https://ai-office.smartjohn-d34.workers.dev" -d '{"ws":"<사무실>","automation":"<id>","requestId":"req-<YYYYMMDDHHmmss>-test"}'
   ```
   run 이 `completed/success` 가 되고 `files.<id>.request_id` 가 같은 값으로 올라오면 완료. 실패하면 `gh run view <id> --log-failed` 로 원인을 본다.
4. 첫 실행으로 결과 폴더가 생겼으면 `config.actions.yaml` 의 `result_link` 에 폴더 주소를 넣는다(카드의 "결과 폴더 열기" 버튼). 다음 실행부터 버튼이 보인다.
5. `automations/<id>/README.md` 를 실제 동작에 맞게 다듬고, `REPO/README.md` 사무실 표에 한 줄 추가.

## 완료 체크리스트 (모두 예여야 "완료")

- [ ] `pytest`·`npm test`·`tsc`·`build` 통과
- [ ] 로컬 `--dry-run` 이 실제 데이터로 요약을 출력
- [ ] 사이트 카드에 직원(tasks)이 보이고 상태가 "쉬는 중/끝남" 중 하나
- [ ] 시작 버튼(API) 으로 1회 실행 → 끝남 → 상태 파일에 `run_id`·`request_id`·`tasks[]` 기록
- [ ] 결과물이 있으면 `result_link` 가 채워져 카드에 "결과 폴더 열기" 버튼이 보임
- [ ] 비밀값이 코드·문서·커밋에 없음
- [ ] 메모리(`project-ai-office-dashboard`)에 새 자동화 한 줄 추가

## 이번에 겪은 함정 (다시 겪지 말 것)

- 국회 사이트는 해외 IP 차단 → GitHub 서버 실행기에서 타임아웃. 사무실 PC 실행기 사용.
- 사무실 PC 에 `pwsh` 없음 → 워크플로 셸은 Windows PowerShell.
- PC 의 PowerShell 프로필이 작업 위치를 다른 폴더로 옮김(`Set-Location`) → 상대 경로가 깨짐. 워크플로 `shell:` 의 `-NoProfile` 을 지우지 말 것.
- fine-grained 토큰의 Repository access 에 저장소가 없으면 GitHub 가 404 → 화면에 "토큰이 ai-office 저장소를 못 봐요" 배너.
- 예약(cron)은 UTC 로 적는다. KST 09:00 = `0 0 * * *`.
- Open API(열린국회정보)는 브라우저 User-Agent 가 없으면 400.
- 임시 회의록처럼 "나중에 바뀌는 결과물"은 manifest 에 상태를 두고 다음 실행에서 교체한다.
- 자동화마다 모듈 이름이 같으면(`store.py` 등) `pytest automations` 에서 서로 가린다 → 모듈 이름에 자동화 id 를 붙인다(예 `news_store.py`).
- 이 폴더는 구글 드라이브 가상 디스크라 `node_modules` 를 두지 않고 연결(junction)도 안 된다 → npm 은 `bash scripts/npm.sh …`.
- 사이트 화면은 JS 가 그린다 → 카드가 반영됐는지는 HTML 이 아니라 `/api/status?ws=<사무실>` 의 `files.<id>` 로 확인한다.
