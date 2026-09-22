#!/usr/bin/env bash
# 안드로이드 앱(android/cardsms) 의 Gradle 명령을 드라이브 밖 로컬 작업 폴더에서 돌린다.
# 이유는 scripts/npm.sh 와 같다 — build/·.gradle/ 수천 파일이 드라이브로 올라가는 것을 막는다.
#
#   bash scripts/gradle.sh test            # core 단위 테스트
#   bash scripts/gradle.sh assembleDebug   # 이 PC 에서 APK(debug 서명) 만들기
#   bash scripts/gradle.sh where
# 필요: JDK 17(JAVA_HOME), 안드로이드 SDK(ANDROID_HOME, platforms;android-34 + build-tools;34.0.0).
# Gradle 8.9 는 없으면 %LOCALAPPDATA%\gradle-8.9 에 내려받는다(1회, 약 130MB).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL="$(cygpath -u "${LOCALAPPDATA:?LOCALAPPDATA 가 없습니다. Windows 의 Git Bash 에서 실행하세요}")"
WORK="$LOCAL/ai-office-android/cardsms"
GRADLE_HOME="$LOCAL/gradle-8.9"
: "${ANDROID_HOME:?ANDROID_HOME 이 없습니다 (안드로이드 SDK 위치)}"

cmd="${1:-}"
[ $# -gt 0 ] && shift
[ "$cmd" = where ] && { echo "$WORK"; exit 0; }
[ -z "$cmd" ] && { echo "사용: bash scripts/gradle.sh test|assembleDebug|assembleRelease|where [추가 인자]" >&2; exit 2; }

if [ ! -x "$GRADLE_HOME/bin/gradle" ]; then
  echo "  · Gradle 8.9 내려받는 중 (처음 한 번)"
  curl -fsSL -o "$LOCAL/gradle-8.9.zip" https://services.gradle.org/distributions/gradle-8.9-bin.zip
  (cd "$LOCAL" && unzip -q -o gradle-8.9.zip && rm gradle-8.9.zip)
fi

mkdir -p "$WORK"
rc=0
MSYS_NO_PATHCONV=1 robocopy "$(cygpath -w "$REPO/android/cardsms")" "$(cygpath -w "$WORK")" /MIR \
  /XD build .gradle .kotlin /XF local.properties /NFL /NDL /NJH /NJS /NP /R:1 /W:1 >/dev/null || rc=$?
if [ "$rc" -ge 8 ]; then echo "소스 복사 실패 (robocopy 코드 $rc)" >&2; exit "$rc"; fi
printf 'sdk.dir=%s\n' "$(cygpath -m "$ANDROID_HOME")" > "$WORK/local.properties"

cd "$WORK"
exec "$GRADLE_HOME/bin/gradle" --no-daemon -q --console=plain "$cmd" "$@"
