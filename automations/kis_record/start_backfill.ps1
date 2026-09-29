# 밤새 1분봉 백필을 숨긴 창으로 띄운다. 사용: powershell -ExecutionPolicy Bypass -File automations\kis_record\start_backfill.ps1 [-Targets <csv>] [-StopAt 08:30]
param([string]$Targets = "", [string]$StopAt = "08:30", [string]$Interval = "1.5")
$base = Join-Path $env:USERPROFILE "ai-office-data\kis-record"
if (-not $Targets) { $Targets = Join-Path $base "minutes\targets_A_2025Q4_2026Q3.csv" }
$logDir = Join-Path $base "logs"; New-Item -ItemType Directory -Force $logDir | Out-Null
$script = Join-Path $PSScriptRoot "kis_minutes.py"
$python = (Get-Command python).Source
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$p = Start-Process -FilePath $python -ArgumentList @("`"$script`"", "--targets", "`"$Targets`"", "--stop-at", $StopAt, "--interval", $Interval) -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "minutes_backfill_$stamp.log") -RedirectStandardError (Join-Path $logDir "minutes_backfill_$stamp.err.log")
Write-Output ("started PID " + $p.Id + " -> " + (Join-Path $logDir "minutes_backfill_$stamp.log"))
