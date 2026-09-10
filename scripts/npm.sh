#!/usr/bin/env bash
# npm 명령(검사·빌드·개발 서버)을 드라이브 밖 로컬 작업 폴더에서 돌린다.
#
# 이 저장소는 구글 드라이브 폴더다. 여기에 node_modules(파일 수만 개)를 두면 클라우드로 올라가고,
# 드라이브 가상 디스크는 연결(junction)도 안 된다. 그래서 소스만 이 PC 의 로컬 작업 폴더
# (%LOCALAPPDATA%\ai-office-node)로 복사해 거기서 npm 을 돌린다.
# node_modules 는 package-lock.json 이 바뀔 때만 다시 설치한다.
#
# 사용 (Git Bash, 저장소 폴더에서):
#   bash scripts/npm.sh test              # tests/*.test.mjs
#   bash scripts/npm.sh tsc               # 타입 검사
#   bash scripts/npm.sh build
#   bash scripts/npm.sh dev --port 3011   # 파일을 고치면 다시 실행해야 반영된다
#   bash scripts/npm.sh lint
#   bash scripts/npm.sh ci                # node_modules 강제 재설치
#   bash scripts/npm.sh where             # 로컬 작업 폴더 위치
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL="$(cygpath -u "${LOCALAPPDATA:?LOCALAPPDATA 가 없습니다. Windows 의 Git Bash 에서 실행하세요}")"
WORK="$LOCAL/ai-office-node"

# Windows ARM PC 는 x64 Node 를 쓴다(workerd 등 arm64 빌드가 없는 모듈 때문). 없으면 기본 Node.
X64="$LOCAL/node-x64/node"
if [ -x "$X64/node.exe" ]; then export PATH="$X64:$PATH"; fi

sync_sources() {
  mkdir -p "$WORK"
  # /MIR: 바뀐 파일만 복사하고, 저장소에서 지운 파일은 작업 폴더에서도 지운다.
  # /XD·/XF 로 뺀 것은 복사도 삭제도 하지 않는다(그래서 작업 폴더의 node_modules 는 남는다).
  local rc=0
  MSYS_NO_PATHCONV=1 robocopy "$(cygpath -w "$REPO")" "$(cygpath -w "$WORK")" /MIR \
    /XD node_modules .git ai-assembly ai-home ai-stock dist .wrangler .vinext .next __pycache__ .pytest_cache \
    /XF tsconfig.tsbuildinfo token.json client_secret.json seen_msgs.json \
    /NFL /NDL /NJH /NJS /NP /R:1 /W:1 >/dev/null || rc=$?
  if [ "$rc" -ge 8 ]; then echo "소스 복사 실패 (robocopy 코드 $rc)" >&2; exit "$rc"; fi
}

install_deps() {
  local stamp="$WORK/node_modules/.lock-stamp"
  if [ "${1:-}" = force ] || [ ! -f "$stamp" ] || ! cmp -s "$WORK/package-lock.json" "$stamp"; then
    echo "  · node_modules 설치 중 (로컬 작업 폴더, 처음 한 번은 몇 분 걸림)"
    (cd "$WORK" && npm ci --no-audit --no-fund --loglevel=error)
    cp "$WORK/package-lock.json" "$stamp"
  fi
}

cmd="${1:-}"
[ $# -gt 0 ] && shift
case "$cmd" in
  where) echo "$WORK"; exit 0 ;;
  test|tsc|build|dev|lint|ci) ;;
  *) echo "사용: bash scripts/npm.sh test|tsc|build|dev|lint|ci|where [추가 인자]" >&2; exit 2 ;;
esac

sync_sources
if [ "$cmd" = ci ]; then install_deps force; exit 0; fi
install_deps
cd "$WORK"
case "$cmd" in
  tsc) npx tsc --noEmit "$@" ;;
  *)   npm run "$cmd" -- "$@" ;;
esac
