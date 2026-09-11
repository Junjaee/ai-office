# AI 오피스 — 작업 지침 (AI 코딩 도구용)

이 저장소는 **자동화를 실행하고 상태를 보여 주는 픽셀 사무실 대시보드**다. 한 사이트에 사무실(`/assembly`, `/home`, `/side`)이 여럿 있고, 각 사무실은 `app/workspaces/<id>.ts` 한 파일로 정의된다.

- **한국어로 대화한다.** 사용자는 개발자가 아니므로 전문용어 대신 쉬운 말로 안내한다.
- 대시보드: https://ai-office.smartjohn-d34.workers.dev — `/assembly`(국회) `/home`(홈) `/side`(부업). 주소는 비공개 취급(주소를 아는 사람은 누구나 시작 버튼을 누를 수 있다).
- 부업 사무실(`/side`, 2026-09-11)은 **팀 = 플랫폼(인스타 게시글·릴스·쇼츠·블로그), 자동화 = 계정**. 계정별 자동화 id 는 `insta_<계정>` 처럼 짓고, 코드는 플랫폼당 한 벌(`automations/insta/`)에 워크플로 입력값 `account` 와 계정별 비밀값으로 구분한다. 한 팀에 계정 3개(직원 6명)까지, 넘으면 같은 플랫폼 2팀을 연다. 새 사무실 추가 절차는 `new-automation` 스킬 부록.
- 설계 문서: `docs\superpowers\specs\2026-09-10-오피스-실행구조-재설계-design.md` (상태 규칙·실행 경로·화면 구성의 근거). 계획: `docs\superpowers\plans\`.

> **이 폴더 = 저장소 (사용자 결정 2026-09-10).** 이 폴더(`G:\내 드라이브\dev\자동화`) 자체가 git 저장소(GitHub `Junjaee/ai-office`, 비공개)이자 **구글 드라이브 동기화 폴더**다. 코드·워크플로·대시보드·문서·템플릿이 전부 여기 있고, 커밋·푸시하면 GitHub Actions·대시보드에 반영된다. 다른 곳에 복사본을 두고 작업하지 않는다.
> - 코드는 `automations/<id>/`, 개인 설정·메모는 `ai-<사무실>/NN_<이름>/`(예 `ai-assembly/01_국회회의록/`, `ai-home/01_가계부/`, `ai-side/01_인스타게시글_<계정>/`). 개인 폴더는 `.gitignore` 로 제외돼 GitHub 에 올라가지 않는다.
> - **비밀값 파일(`config.yaml`·`token.json`·`client_secret.json` 등)은 개인 폴더에 둬도 된다** — 드라이브에 올라가는 것은 괜찮다(사용자 결정 2026-09-10). 단 **커밋·코드·문서·채팅에는 절대 적지 않는다.** 자동화 실행용 값은 GitHub Secrets, 대시보드용은 Cloudflare Worker 비밀값·`.dev.vars`(gitignore). 코드는 `os.environ` 으로만 읽는다.
> - 비밀값 파일은 열어 보지 않는다. 필요하면 키 이름만 확인한다.
> - 새 자동화는 `/new-automation <이름>` 스킬(`.claude/skills/`)로 시작하고, 뼈대는 `templates/automation/` 을 복사한다.
> - **드라이브 폴더라서 생기는 제약**: `node_modules` 는 이 폴더에 설치하지 않는다(파일 수만 개가 클라우드로 올라가고, 드라이브 가상 디스크는 연결(junction)도 안 된다). npm 명령은 `bash scripts/npm.sh …` 로 돌린다 — 소스를 이 PC 의 로컬 작업 폴더(`%LOCALAPPDATA%\ai-office-node`)로 복사해 거기서 실행한다. git 작업 중 이상한 충돌이 나면 드라이브 동기화를 잠시 멈춘다.

---

## 화면이 보여 주는 것 (바꾸지 말 것)

- 직원 = 자동화의 하위 작업(`automations[].tasks[]`). 이름은 사람 이름이 아니라 **업무명**.
- 직원 상태는 네 가지뿐: **쉬는 중 · 일하는 중 · 끝남 · 오류** (+ 아직 자동화 안 된 업무는 "준비 중"). 각본·타이머·랜덤 행동은 없고, 상태가 바뀔 때만 자리를 옮긴다(쉬는 중=라운지 소파, 일하는 중·끝남=책상, 오류=책상 옆).
- 그려지는 부서 = 워크플로가 있는 자동화가 붙은 부서만(4열, 행 수 가변). 회의실·대표실 없음. 라운지는 항상 있음.
- 요약 줄의 **전체 시작**, 카드마다 **시작** 버튼이 실제로 GitHub Actions 를 실행한다(`POST /api/run`). **전체 시작은 따라다니는 머리글(sticky nav)에 두지 않는다** — 스크롤하면 카드의 ▶ 시작 자리와 겹쳐 개별 시작 대신 전체가 눌렸다(2026-09-10). 버튼 보호는 없다(사이트 주소를 아는 사람은 누구나 실행 가능). 중복 실행 방지·하루 50회 상한은 Worker 가 지킨다.
- **사이트 변경은 모든 사무실에 함께 적용한다.** 사무실 하나만 고치는 요청이라도 나머지 사무실에서 깨지지 않는지 본다.
- **검토 칸**: 사무실 설정의 자동화에 `review: { kind: "topics" }` 를 주면 카드 안에 후보 목록(체크 → 만들기)이 붙는다. 자동화는 `public/review/<사무실>/<id>.json` 에 후보·예약을 쓰고, Worker `/api/review` 가 읽고, `/api/run` 의 `inputs`(허용 목록: `mode`·`picks`)로 워크플로에 전달한다. 표준 구현은 `automations/insta/`(README "주제 검토 방식"). 인스타는 06:30 후보 → 07:30 에 아무도 안 골랐으면 1순위 자동 게시(사용자 결정 2026-09-12).

## 새 자동화 붙이기

1. **먼저 `/new-automation <이름>` 스킬을 부른다.** 질문 3개 → 템플릿 복사 → 등록 → 검증 → 배포 순서를 안내한다.
2. 파이썬: `automations/<id>/` 에 코드와 `config.actions.yaml`(`tasks:` 목록 포함). 끝나면 `automations/common/report_status.py` 의 `report(..., workspace="<사무실>", tasks=[...])` 로 상태 파일을 커밋한다. 모듈 이름은 다른 자동화와 겹치지 않게 짓는다(예 `news_store.py`).
3. 워크플로: `.github/workflows/<id>.yml` — `workflow_dispatch` 에 `request_id` 입력, `run-name` 에 그 값을 넣는다(`templates/automation/workflow.yml`).
4. 사무실 설정: `app/workspaces/<사무실>.ts` 의 `AUTOMATIONS` 에 `{ id, dept, name, workflow: "<id>.yml", schedule?, tasks[] }`. `tasks[].id` 는 yaml 의 `tasks:` 와 같아야 한다(`tests/workspaces.test.mjs` 가 검사).
5. 실행기: 워크플로의 `runs-on` 라벨이 맞는 실행기가 켜져 있어야 한다(아래 "실행 위치", `automations/runner/README.md`).
6. **끝났다고 말하기 전에** 스킬의 완료 체크리스트를 전부 통과시킨다(테스트, 로컬 1회 실행, 사이트에서 시작 버튼 1회).

## 절대 규칙

- 부서 `id` 12개(`research brand strategy1 qa strategy2 reels carousel partner finance review ops secretary`)는 바꾸지 않는다. 안 쓰는 부서는 `HIDDEN_DEPARTMENTS` 로 숨긴다.
- 상태 판정 규칙은 `app/status-rules.ts` 한 곳에만 둔다(`import type` 만 허용, `node --test` 가 직접 실행). 화면·엔진에서 규칙을 다시 만들지 않는다.
- 비밀값(`GITHUB_TOKEN`, Google 토큰, Open API 키)은 코드·문서·채팅·커밋에 적지 않는다. 배포용은 Cloudflare 대시보드의 Worker 비밀값, 로컬은 `.dev.vars`(gitignore).
- `.dev.vars` 와 개인 폴더(`ai-*/`)의 설정 파일은 커밋 금지(`.gitignore` 로 막혀 있다).
- **실행 위치의 기본은 GitHub 서버(`ubuntu-latest`).** 국회 사이트(assembly.go.kr)처럼 해외 IP 를 막는 곳을 쓰거나 이 PC 에만 있는 것이 필요할 때만 사무실 PC 실행기(`runs-on: [self-hosted, windows, kr-office]`)를 쓴다. (사용자 결정 2026-09-10)

## 이 PC 환경

- Windows 11 ARM. arm64 빌드가 없는 모듈(workerd 등) 때문에 npm 은 x64 Node 로 돌린다 — `scripts/npm.sh` 가 `%LOCALAPPDATA%\node-x64\node` 를 찾아 알아서 쓴다.
- Python 3.13(requests, bs4, lxml, PyYAML, pytest, google-api-python-client) 있음. `pwsh` 없음(Windows PowerShell 5.1).

## 확인 명령 (저장소 폴더에서, Git Bash)

```bash
bash scripts/npm.sh tsc      # 타입 검사, 오류 0
bash scripts/npm.sh test     # tests/*.test.mjs
bash scripts/npm.sh build
bash scripts/npm.sh dev --port 3011   # 화면 확인: /assembly?mock=running|done|error|idle|queued|runner_waiting|finishing|schedule_missed|static|no_token
python -m pytest -q automations
```

## 구조

- `app/workspaces/` 사무실 설정(`types.ts`, `assembly.ts`, `home.ts`, `index.ts`). `company.config.ts` 는 현재 사무실을 내보내는 한 줄짜리 파일.
- `app/status-rules.ts` 상태 파일 v2 + GitHub run + 로컬 요청 → 화면 상태(순수). `app/status.ts` 조회·폴링 훅(`/api/status` → 정적 파일 폴백). `app/history.ts`·`app/history-rules.ts` 실행 이력(날짜별) 조회 훅·순수 규칙.
- `app/office/OfficeApp.tsx` 단일 페이지 화면. `app/game/` 월드(`world.ts`)·경로(`pathfinding.ts`)·직원(`staff.ts`)·상태→자리 번역(`office-model.ts`)·엔진(`engine.ts`)·렌더러(`OfficeWorld.tsx`).
- `worker/` Cloudflare Worker: `index.ts`(라우팅) `run-api.ts`(`/api/run`, `/api/status`, `/api/history`) `github.ts`(dispatch·runs·Contents) `config.ts`.
- `automations/insta/` 인스타 게시글(콘텐츠 제작·게시형의 표준 구현: 소재→글→카드→업로드, 주제 프로필·계정별 자동화). 새 계정·새 플랫폼은 `automations/insta/README.md` 참고.
- `automations/` 파이썬 자동화와 공통 모듈, `.github/workflows/` 실행 워크플로, `public/status/<사무실>/` 상태 파일. `history/<사무실>/<자동화>/<YYYY-MM>.jsonl` 실행 일지(영구 기록) — `report()` 가 실행마다 한 줄씩 더하고, 지난 기록 복원은 `python automations/common/history_log.py --backfill`(여러 번 돌려도 같은 결과). 화면의 실행 이력은 이 일지와 GitHub 날짜별 실행 목록을 합쳐 보여 준다(`/api/history`).
- `scripts/npm.sh` npm 명령을 드라이브 밖 로컬 작업 폴더에서 돌리는 도구. `scripts/npm.cmd` 는 명령 프롬프트·미리보기 도구(`.claude/launch.json`)용 — 그냥 `bash` 라고 부르면 WSL 이 잡히므로 Git Bash 를 찾아 npm.sh 를 부른다. `templates/automation/` 새 자동화 뼈대. `.claude/skills/new-automation/` 새 자동화 절차.
