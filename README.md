# AI 오피스 (자동화 실행·상태 대시보드)

픽셀 사무실 형태의 자동화 대시보드입니다. **한 사이트 안에 사무실 여러 개**가 있고, 상단 탭으로 오갑니다. 화면의 **시작** 버튼이 실제로 자동화(GitHub Actions)를 실행하고, 직원(=자동화의 하위 작업)이 **쉬는 중 · 일하는 중 · 끝남 · 오류** 중 어디에 있는지 보여 줍니다.

| 사무실 | 주소 | 용도 | 팔레트 |
|---|---|---|---|
| 국회 | `/assembly` | 의원실 자동화 (국회회의록 수집 등) | 국회 CI (네이비·블루·틸) |
| 홈 | `/home` | 가정 자동화 (지출·정산 등, 준비 중) | 블루·화이트·그레이 |
| 주식 | `/stock` (예정) | 주식 자동화 | 미정 |

루트 `/` 는 국회 사무실로 이동합니다.

## 화면 구성

1. 헤더: 사무실 탭, 마지막 확인 시각, **▶ 전체 시작**
2. 배너(있을 때만): 🔴 실패·실행 연결 끊김 / 🟡 실행기 꺼짐·예약 밀림 / ⚪ 최신 상태 못 가져옴
3. 요약 4칸: 일하는 중 · 끝남 · 쉬는 중 · 오류 (직원 수)
4. 픽셀 사무실: 자동화가 붙은 부서만 그림. 직원은 상태가 바뀔 때만 라운지↔책상을 오감. 직원을 누르면 아래 카드의 해당 업무로 이동
5. 자동화 카드: 상태·**▶ 시작**·부제·업무별 상태·마지막/다음 실행·결과 폴더·자세히(최근 기록, GitHub 실행 페이지)

## 실행 경로

```
[시작] ─ POST /api/run ─▶ Cloudflare Worker ─ workflow_dispatch ─▶ GitHub Actions ─▶ 실행기(runs-on 라벨) ─▶ 파이썬
                                                                                        └─ public/status/<사무실>/<id>.json 커밋
화면 ◀─ GET /api/status (10초/60초 폴링) ◀─ Worker ◀─ runs API + Contents API   (Worker 가 죽으면 정적 파일 폴백)
```

- 중복 실행 방지(이미 queued/in_progress 면 skipped), 같은 요청 30초 내 재요청 무시, 사무실별 하루 50회 상한(429).
- 버튼 보호는 없습니다. 사이트 주소는 비공개로 유지하세요.
- 상태 규칙(`app/status-rules.ts`): run 이 queued 90초 넘으면 "실행기 기다리는 중", 성공 run 뒤 5분 안에 결과 파일이 없으면 오류, 36시간 넘게 실행 없으면 쉬는 중, 예약이 있는데 밀리면 🟡 배너.

## 처음 한 번 설정 (사용자)

1. **실행기 등록** — 국회 사이트가 해외 IP 를 막으므로 사무실 PC 또는 국내 서버를 GitHub 자체 실행기로 등록합니다. `automations/runner/README.md` (라벨 `kr-office`).
2. **GitHub 토큰** — fine-grained PAT (저장소 `ai-office` 하나, Actions: Read and write, Contents: Read). Cloudflare 대시보드 → Workers & Pages → `ai-office` → Settings → Variables and Secrets → `GITHUB_TOKEN`(Secret). 없으면 화면에 🔴 "실행 연결이 끊겼어요"가 뜨고 시작 버튼이 사라집니다.
3. 저장소 Secrets(`OPEN_API_KEY`, `GOOGLE_*`)는 이미 있습니다.

## 사무실 추가하기

1. `app/workspaces/<id>.ts` 를 기존 파일을 복사해 만든다 (부서 12개 id 는 그대로, `AUTOMATIONS`·`HIDDEN_DEPARTMENTS`·회사 정보만 수정).
2. `app/workspaces/index.ts` 의 `WORKSPACES` 와 `WORKSPACE_LIST` 에 넣는다.
3. 팔레트가 다르면 `app/globals.css` 끝에 `html[data-ws="<id>"] { … }` 블록으로 토큰(`--c-*`)을 덮어쓴다.
4. `public/status/<id>/index.json` 을 만든다 (`{ "automations": [] }`).

## 자동화 추가하기

`CLAUDE.md` 의 "새 자동화 붙이기" 참고. 요약: 파이썬 + `config.actions.yaml`(`tasks:`) → `.github/workflows/<id>.yml`(`request_id` 입력) → 사무실 설정 `AUTOMATIONS` 에 등록.

## 구조

- `app/workspaces/` 사무실별 설정과 목록. `company.config.ts` 는 현재 사무실 값을 내보내는 얇은 파일.
- `app/[workspace]/page.tsx` → `app/office/WorkspaceLoader.tsx` 가 사무실을 정한 뒤 `app/office/OfficeApp.tsx`(단일 페이지 화면)를 불러옴.
- `app/status-rules.ts` 상태 규칙(순수), `app/status.ts` 조회·폴링 훅.
- `app/game/` 픽셀 사무실: `world.ts`(4열 가변 배치·라운지) `pathfinding.ts` `staff.ts` `office-model.ts`(상태→자리·자세) `engine.ts` `OfficeWorld.tsx`.
- `worker/` Cloudflare Worker (`/api/run`, `/api/status`, GitHub 클라이언트).
- `automations/` 자동화 코드(`minutes` 국회회의록, `common` 상태 보고·오류 문구·Drive), `automations/runner` 실행기 설치.
- `public/status/<사무실>/` 자동화가 커밋하는 상태 파일(v2: `run_id`·`request_id`·`tasks[]` 포함).

## 이 PC에서 실행 (Windows ARM)

workerd 는 ARM 빌드가 없어 x64 Node 로 실행합니다.

```bash
export PATH="/c/Users/smart/AppData/Local/node-x64/node:$PATH"
npm run dev -- --port 3011
```

화면 확인용 가짜 상태: `/assembly?mock=running` (`done`, `error`, `idle`, `queued`, `runner_waiting`, `finishing`, `schedule_missed`, `static`, `no_token`).

## 테스트

```bash
npm test              # tests/*.test.mjs (상태 규칙·Worker API·엔진·사무실 설정)
npx tsc --noEmit
python -m pytest -q automations
```

## 배포

GitHub 저장소를 Cloudflare Workers Builds 에 연결해 두었으므로 `main` 에 push 하면 자동 배포됩니다 (빌드 `npm run build`, 배포 `npx wrangler deploy`). 로컬 비밀값은 `.dev.vars.example` 를 복사해 `.dev.vars` 로 만듭니다(커밋 금지).
