# 사무실 PC 자체 실행기 설치

국회 사이트가 해외 IP를 차단해 GitHub 기본 서버에서는 수집이 안 된다. 사무실 PC를 GitHub Actions 자체 실행기(self-hosted runner)로 등록해 그 PC에서 실행한다. 예약·수동 실행·Secrets·로그는 GitHub에서 그대로 관리한다.

## 준비물

- Windows 10/11 PC, 관리자 계정, 인터넷(브라우저로 github.com, drive.google.com, record.assembly.go.kr 열려야 함)
- 이 폴더의 `setup-office-runner.ps1`
- 등록 토큰 (1시간 유효). 두 방법 중 하나:
  - GitHub 저장소 → **Settings → Actions → Runners → New self-hosted runner → Windows** 화면의 `--token` 뒤 값
  - 또는 Claude에게 "실행기 토큰 만들어줘"라고 요청

## 설치 (10분)

1. 사무실 PC에서 GitHub에 로그인해 이 파일을 내려받는다: `automations/runner/setup-office-runner.ps1` (Raw → 저장)
2. **관리자 권한 PowerShell**을 열고 파일이 있는 폴더로 이동
3. 실행:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\setup-office-runner.ps1 -Token "<등록 토큰>"
```

4. GitHub 저장소 → Settings → Actions → Runners 에 `office-pc`가 **Idle**(초록)로 보이면 완료
5. GitHub → Actions → "진단 (네트워크)" → Run workflow 로 사무실 PC에서 국회 사이트가 열리는지 확인
6. Actions → "국회회의록 수집" → Run workflow 로 첫 실행

## 운영

- 실행기는 Windows 서비스로 돌아 재부팅 후 자동 시작된다. 로그인은 필요 없다.
- 절전은 스크립트가 끈다. 노트북이면 덮개 닫힘 동작을 "아무 것도 안 함"으로 바꾼다.
- 실행기가 오프라인이면 예약 실행이 대기 상태로 남고, 대시보드는 36시간 뒤 "대기"로 표시된다.
- PC를 폐기·이관할 때는 `C:\actions-runner` 에서 `.\config.cmd remove --token <토큰>` 으로 등록을 해제한다.

## 문제 해결

- `python` 이 없다고 나오면 PowerShell을 새로 열어 다시 실행 (PATH 갱신)
- 등록 실패: 토큰 만료 → 새 토큰으로 재실행
- 서비스가 Running인데 GitHub에서 Offline: 사내 방화벽이 github.com 아웃바운드를 막는지 확인
