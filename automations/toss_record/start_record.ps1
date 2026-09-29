# 토스 실시간 녹음을 숨긴 창으로 띄우고 끝날 때까지 기다린다(작업 스케줄러 작업 Toss-record 가 이 스크립트를 부른다).
# 사용: powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File automations\toss_record\start_record.ps1 [-Until 15:35] [-Candidates <파일>] [-NoWait]
# 왜 cmd 창이 아니라 이것인가(2026-09-29): 스케줄러가 cmd.exe 로 띄우면 검은 콘솔 창이 화면에 뜨고, 그 창을 닫으면 녹음이 죽는다(종료 코드 0xC000013A = 콘솔 닫힘/Ctrl+C, 15:29 실측).
param([string]$Until = "15:35", [string]$Candidates = "", [switch]$NoWait)
$base = Join-Path $env:USERPROFILE "ai-office-data\toss-record"
$logDir = Join-Path $base "logs"; New-Item -ItemType Directory -Force $logDir | Out-Null
$script = Join-Path $PSScriptRoot "record_toss.py"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = Join-Path $logDir "record_$stamp.log"
# 드라이브(G:)가 늦게 붙으면 최대 10분 기다린다
$tries = 0
while (-not (Test-Path $script) -and $tries -lt 20) { Start-Sleep -Seconds 30; $tries++ }
if (-not (Test-Path $script)) { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] script not found: $script" | Out-File $log -Append; exit 6 }
$python = (Get-Command python).Source
$argList = @("`"$script`"", "--auto", "--until", $Until)
if ($Candidates) { $argList += @("--candidates", "`"$Candidates`"") }
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] start record_toss.py $($argList[1..($argList.Count-1)] -join ' ')" | Out-File $log -Append
$p = Start-Process -FilePath $python -ArgumentList $argList -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "record_$stamp.out.log") -RedirectStandardError (Join-Path $logDir "record_$stamp.err.log")
Write-Output ("started PID " + $p.Id + " -> " + (Join-Path $logDir "record_$stamp.out.log"))
if (-not $NoWait) {
    $p.WaitForExit()
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] exit $($p.ExitCode)" | Out-File $log -Append
    exit $p.ExitCode
}
