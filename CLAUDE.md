# AI 오피스 — 작업 지침 (AI 코딩 도구용)

이 저장소는 **자동화를 실행하고 상태를 보여 주는 픽셀 사무실 대시보드**다. 한 사이트에 사무실(`/assembly`, `/home`)이 여럿 있고, 각 사무실은 `app/workspaces/<id>.ts` 한 파일로 정의된다. 사용자는 개발자가 아니므로 전문용어 대신 쉬운 말로 안내한다.

설계 문서: `docs\superpowers\specs\2026-09-10-오피스-실행구조-재설계-design.md` (상태 규칙·실행 경로·화면 구성의 근거).

> **이 폴더 = 저장소 (사용자 결정 2026-09-10).** 이 폴더 자체가 git 저장소(GitHub `Junjaee/ai-office`)이자 **구글 드라이브 동기화 폴더**다. 코드·워크플로·대시보드·문서·템플릿이 전부 여기 있고, 커밋·푸시하면 GitHub Actions·대시보드에 반영된다.
> - **비밀값(토큰·키·OAuth `token.json`·`client_secret.json`)은 이 폴더 어떤 파일에도 두지 않는다** — git+드라이브라 커밋되거나 클라우드에 올라간다. 자동화용은 **GitHub Secrets**, 대시보드용은 Cloudflare Worker 비밀값·`.dev.vars`(gitignore). 코드는 `os.environ` 으로만 읽는다.
> - 개인 설정·메모는 `ai-<사무실>/NN_<이름>/`(예 `ai-home/01_가계부/`)에 두고 **`.gitignore` 로 제외**한다(공유 안 함). 코드는 `automations/<id>/` 에 둔다.
> - 새 자동화는 `/new-automation <이름>` 스킬(`.claude/skills/`)로 시작하고, 뼈대는 `templates/automation/` 을 복사한다.
> - **주의(드라이브+git)**: `.git`·`node_modules` 를 드라이브가 동기화하다 충돌시킬 수 있다. git 작업 중 문제가 나면 드라이브 동기화를 잠시 멈춘다.

---

## 화면이 보여 주는 것 (바꾸지 말 것)

- 직원 = 자동화의 하위 작업(`automations[].tasks[]`). 이름은 사람 이름이 아니라 **업무명**.
- 직원 상태는 네 가지뿐: **쉬는 중 · 일하는 중 · 끝남 · 오류** (+ 아직 자동화 안 된 업무는 "준비 중"). 각본·타이머·랜덤 행동은 없고, 상태가 바뀔 때만 자리를 옮긴다(쉬는 중=라운지 소파, 일하는 중·끝남=책상, 오류=책상 옆).
- 그려지는 부서 = 워크플로가 있는 자동화가 붙은 부서만(4열, 행 수 가변). 회의실·대표실 없음. 라운지는 항상 있음.
- 상단 **전체 시작**, 카드마다 **시작** 버튼이 실제로 GitHub Actions 를 실행한다(`POST /api/run`). 버튼 보호는 없다(사이트 주소를 아는 사람은 누구나 실행 가능). 중복 실행 방지·하루 50회 상한은 Worker 가 지킨다.
- **사이트 변경은 모든 사무실에 함께 적용한다.** 사무실 하나만 고치는 요청이라도 나머지 사무실에서 깨지지 않는지 본다.

## 새 자동화 붙이기

1. 파이썬: `automations/<id>/` 에 코드와 `config.actions.yaml`(`tasks:` 목록 포함). 끝나면 `automations/common/report_status.py` 의 `report(..., workspace="<사무실>", tasks=[...])` 로 상태 파일을 커밋한다.
2. 워크플로: `.github/workflows/<id>.yml` — `workflow_dispatch` 에 `request_id` 입력, `run-name` 에 그 값을 넣는다(`minutes.yml` 복사).
3. 사무실 설정: `app/workspaces/<사무실>.ts` 의 `AUTOMATIONS` 에 `{ id, dept, name, workflow: "<id>.yml", schedule?, tasks[] }`. `tasks[].id` 는 yaml 의 `tasks:` 와 같아야 한다(`tests/workspaces.test.mjs` 가 검사).
4. 실행기: 워크플로의 `runs-on` 라벨이 맞는 실행기(사무실 PC 또는 국내 서버)가 켜져 있어야 한다. `automations/runner/README.md`.

## 절대 규칙

- 부서 `id` 12개(`research brand strategy1 qa strategy2 reels carousel partner finance review ops secretary`)는 바꾸지 않는다. 안 쓰는 부서는 `HIDDEN_DEPARTMENTS` 로 숨긴다.
- 상태 판정 규칙은 `app/status-rules.ts` 한 곳에만 둔다(`import type` 만 허용, `node --test` 가 직접 실행). 화면·엔진에서 규칙을 다시 만들지 않는다.
- 비밀값(`GITHUB_TOKEN`, Google 토큰, Open API 키)은 코드·문서·채팅에 적지 않는다. 배포용은 Cloudflare 대시보드의 Worker 비밀값, 로컬은 `.dev.vars`(gitignore).
- `.dev.vars` 와 `automations/*/config.yaml` 은 공유·커밋 금지.

## 확인 명령 (이 PC 는 x64 Node 사용)

```bash
export PATH="/c/Users/smart/AppData/Local/node-x64/node:$PATH"
npx tsc --noEmit          # 오류 0
npm test                  # tests/*.test.mjs
npm run build
npm run dev -- --port 3011   # 화면 확인: /assembly?mock=running|done|error|idle|queued|runner_waiting|finishing|schedule_missed|static|no_token
python -m pytest -q automations
```

## 구조

- `app/workspaces/` 사무실 설정(`types.ts`, `assembly.ts`, `home.ts`, `index.ts`). `company.config.ts` 는 현재 사무실을 내보내는 한 줄짜리 파일.
- `app/status-rules.ts` 상태 파일 v2 + GitHub run + 로컬 요청 → 화면 상태(순수). `app/status.ts` 조회·폴링 훅(`/api/status` → 정적 파일 폴백).
- `app/office/OfficeApp.tsx` 단일 페이지 화면. `app/game/` 월드(`world.ts`)·경로(`pathfinding.ts`)·직원(`staff.ts`)·상태→자리 번역(`office-model.ts`)·엔진(`engine.ts`)·렌더러(`OfficeWorld.tsx`).
- `worker/` Cloudflare Worker: `index.ts`(라우팅) `run-api.ts`(`/api/run`, `/api/status`) `github.ts`(dispatch·runs·Contents) `config.ts`.
- `automations/` 파이썬 자동화와 공통 모듈, `.github/workflows/` 실행 워크플로, `public/status/<사무실>/` 상태 파일.
