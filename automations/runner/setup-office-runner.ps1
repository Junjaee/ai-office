<#
.SYNOPSIS
  사무실 PC를 GitHub Actions 자체 실행기(self-hosted runner)로 등록한다.

.DESCRIPTION
  1) Git, Python 3.12 설치 (없을 때만)  2) 실행기 다운로드·설치  3) Windows 서비스로 등록
  4) 절전·최대 절전 끄기  5) 등록 확인
  관리자 PowerShell에서 실행한다. 등록 토큰은 1시간만 유효하다.

.EXAMPLE
  Set-ExecutionPolicy Bypass -Scope Process -Force
  .\setup-office-runner.ps1 -Token "AXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
#>
param(
  [Parameter(Mandatory = $true)][string]$Token,          # GitHub 실행기 등록 토큰
  [string]$Repo = "https://github.com/Junjaee/ai-office",
  [string]$RunnerName = "office-pc",
  [string]$Labels = "kr-office",
  [string]$RunnerDir = "C:\actions-runner"
)

$ErrorActionPreference = "Stop"
function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "관리자 PowerShell에서 실행해 주세요 (시작 메뉴 → PowerShell 우클릭 → 관리자 권한으로 실행)."
}

Step "1/5 Git·Python 확인"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  winget install --id Git.Git -e --scope machine --accept-source-agreements --accept-package-agreements --silent
}
if (-not (Get-Command python -ErrorAction SilentlyContinue) -or -not ((python --version 2>&1) -match "3\.1[0-9]")) {
  winget install --id Python.Python.3.12 -e --scope machine --accept-source-agreements --accept-package-agreements --silent
}
$env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH", "User")
Write-Host ("git:    " + (git --version))
Write-Host ("python: " + (python --version 2>&1))

Step "2/5 실행기 다운로드"
New-Item -ItemType Directory -Force $RunnerDir | Out-Null
Set-Location $RunnerDir
if (-not (Test-Path ".\config.cmd")) {
  $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
  $rel = Invoke-RestMethod "https://api.github.com/repos/actions/runner/releases/latest" -Headers @{ "User-Agent" = "setup-office-runner" }
  $asset = $rel.assets | Where-Object { $_.name -like "actions-runner-win-$arch-*.zip" } | Select-Object -First 1
  Write-Host ("받는 파일: " + $asset.name)
  Invoke-WebRequest -Uri $asset.browser_download_url -OutFile "runner.zip"
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [System.IO.Compression.ZipFile]::ExtractToDirectory("$RunnerDir\runner.zip", $RunnerDir)
  Remove-Item "runner.zip"
} else {
  Write-Host "이미 내려받은 실행기가 있어 건너뜁니다."
}

Step "3/5 실행기 등록 (Windows 서비스)"
if (Test-Path ".\.runner") {
  Write-Host "이미 등록돼 있습니다. 다시 등록하려면 먼저 .\config.cmd remove --token <토큰> 을 실행하세요."
} else {
  .\config.cmd --url $Repo --token $Token --name $RunnerName --labels $Labels --work "_work" --runasservice --unattended --replace
  if ($LASTEXITCODE -ne 0) { throw "실행기 등록 실패 (토큰이 만료됐으면 새 토큰으로 다시 실행)" }
}

Step "4/5 절전 끄기 (전원 연결 시 절대 잠들지 않음)"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 20
Write-Host "완료. 노트북이면 덮개를 닫아도 계속 켜지도록 전원 옵션에서 '덮개를 닫을 때: 아무 것도 안 함'으로 바꿔 주세요."

Step "5/5 서비스 상태 확인"
Get-Service | Where-Object { $_.Name -like "actions.runner.*" } | Format-Table Name, Status -AutoSize
Write-Host "`nGitHub 저장소 → Settings → Actions → Runners 에 '$RunnerName' 이 Idle(초록)로 보이면 성공입니다." -ForegroundColor Green
