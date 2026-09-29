# 토스 백필 묶음(분봉 목표 목록 → 수급 전 종목)을 숨긴 창으로. 사용: powershell -ExecutionPolicy Bypass -File automations\toss_record\start_backfill.ps1 [-Targets <csv>] [-SkipFlows]
param([string]$Targets = "", [switch]$SkipFlows, [switch]$SkipCandles)
$base = Join-Path $env:USERPROFILE "ai-office-data\toss-record"
if (-not $Targets) { $Targets = Join-Path $env:USERPROFILE "ai-office-data\kis-record\minutes\targets_A_2025Q4_2026Q3.csv" }
$logDir = Join-Path $base "logs"; New-Item -ItemType Directory -Force $logDir | Out-Null
$python = (Get-Command python).Source
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$jobs = @()
if (-not $SkipCandles) { $jobs += "toss_candles.py --targets $Targets" }
if (-not $SkipFlows) { $jobs += "toss_flows.py --universe" }
$argList = @("`"" + (Join-Path $PSScriptRoot "run_chain.py") + "`"") + ($jobs | ForEach-Object { "`"$_`"" })
$p = Start-Process -FilePath $python -ArgumentList $argList -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "backfill_$stamp.log") -RedirectStandardError (Join-Path $logDir "backfill_$stamp.err.log")
Write-Output ("started PID " + $p.Id + " -> " + (Join-Path $logDir "backfill_$stamp.log"))
