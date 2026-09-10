# AI 오피스 (자동화 대시보드 허브)

픽셀 사무실 형태의 자동화 대시보드입니다. **한 사이트 안에 사무실 여러 개**가 있고, 상단 탭으로 오갑니다.

| 사무실 | 주소 | 용도 | 팔레트 |
|---|---|---|---|
| 국회 | `/assembly` | 의원실 자동화 (국회회의록 수집 등) | 국회 CI (네이비·블루·틸) |
| 홈 | `/home` | 가정 자동화 (지출·정산 등) | 블루·화이트·그레이 |
| 주식 | `/stock` (예정) | 주식 자동화 | 미정 |

루트 `/` 는 국회 사무실로 이동합니다.

## 사무실 추가하기

1. `app/workspaces/<id>.ts` 를 기존 파일을 복사해 만든다 (부서 12개 id 는 그대로, 이름·직원·숨김 목록만 수정).
2. `app/workspaces/index.ts` 의 `WORKSPACES` 와 `WORKSPACE_LIST` 에 넣는다.
3. 팔레트가 다르면 `app/globals.css` 끝에 `html[data-ws="<id>"] { … }` 블록으로 토큰(`--c-*`, `--pink*`)을 덮어쓴다.
4. `public/status/<id>/index.json` 을 만든다 (`{ "automations": [] }`).

## 실제 상태 연결

- 자동화가 `public/status/<사무실 id>/<자동화 id>.json` 을 쓰고 같은 폴더의 `index.json` 에 id 를 등록한 뒤 커밋·push 하면, 그 사무실의 해당 부서가 실제 상태(완료 / 진행 중 / 오류 / 대기)로 바뀝니다.
- 파일을 쓰는 쪽은 `automations/common/report_status.py` 의 `report(..., workspace="assembly")` 입니다. 국회회의록 수집기(`automations/minutes`)가 호출합니다.
- 규칙: `running` → 진행 중, `ok=false` → 오류, 36시간 넘게 갱신 없음 → 대기, 그 외 → 완료 (`app/status-rules.ts`).
- `자동화 운영팀`·`비서실`은 그 사무실 상태 파일의 집계이고, 실제 연결이 없는 부서는 사무실 설정의 `PENDING_INTEGRATIONS`에 따라 "연동 대기"(자동화 준비 중)로, `HIDDEN_DEPARTMENTS` 에 있으면 빈 사무실로 표시됩니다.

## 구조

- `app/workspaces/` 사무실별 설정 (`assembly.ts`, `home.ts`) 과 목록 (`index.ts`)
- `company.config.ts` 엔진이 읽는 "현재 사무실" 값 (사무실 파일을 그대로 내보냄)
- `app/[workspace]/page.tsx` → `app/office/WorkspaceLoader.tsx` 가 사무실을 정한 뒤 `app/office/OfficeApp.tsx`(화면)와 엔진을 불러옴. 사무실 전환은 전체 페이지 이동.
- `app/game/` 픽셀 사무실 시뮬레이션 엔진 (부서 12개 id 고정)
- `automations/` 자동화 코드와 GitHub Actions (`.github/workflows/`)

## 이 PC에서 실행 (Windows ARM)

workerd는 ARM 빌드가 없어 x64 Node로 실행합니다.

```powershell
$env:PATH = "C:\Users\smart\AppData\Local\node-x64\node;" + $env:PATH
npm run dev -- --port 3210
```

## 테스트

```bash
node --test tests/status-rules.test.mjs
npx tsc --noEmit    # db/index.ts, worker/index.ts 의 Cloudflare 타입 오류 3개는 원래 있는 것
```

## 배포

GitHub 저장소를 Cloudflare Workers Builds에 연결하면 push 마다 자동 배포됩니다 (빌드 `npm run build`, 배포 `npx wrangler deploy`).

## 구조

- `company.config.ts` 회사·부서 12개·직원 설정. 부서 `id`와 12개 수는 엔진(`app/game/sim.ts`)이 의존하므로 바꾸지 않는다.
- `app/game/` 픽셀 사무실 시뮬레이션 엔진 (`sim.ts`, `world.ts`, `staff.ts`, `OfficeWorld.tsx`, `pathfinding.ts`)
- `app/status-rules.ts`, `app/status.ts` 실제 상태 규칙과 조회
- `worker/` Cloudflare Worker 진입점과 Notion·Discord 보고(미설정 시 비활성)

## 자주 막히는 곳

- 직원이 안 움직이면 화면 위쪽 **"오늘 업무 시작하기"** 를 누른다.
- 3000/3210 포트가 쓰이고 있으면 `npx vinext dev --port 3211` 처럼 다른 포트로 띄운다.
- 부서를 지우면 화면이 깨진다. 12개를 유지하고 이름만 바꾼다.
