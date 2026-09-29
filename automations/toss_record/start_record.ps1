# 토스 실시간 녹음을 숨긴 창으로 띄운다. 사용: powershell -ExecutionPolicy Bypass -File automations\toss_record\start_record.ps1 [-Until 15:35] [-Candidates <파일>]
param([string]$Until = "15:35", [string]$Candidates = "")
$base = Join-Path $env:LOCALAPPDATA "toss-record"
$logDir = Join-Path $base "logs"; New-Item -ItemType Directory -Force $logDir | Out-Null
$python = (Get-Command python).Source
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$argList = @("`"" + (Join-Path $PSScriptRoot "record_toss.py") + "`"", "--auto", "--until", $Until)
if ($Candidates) { $argList += @("--candidates", "`"$Candidates`"") }
$p = Start-Process -FilePath $python -ArgumentList $argList -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "record_$stamp.log") -RedirectStandardError (Join-Path $logDir "record_$stamp.err.log")
Write-Output ("started PID " + $p.Id + " -> " + (Join-Path $logDir "record_$stamp.log"))
