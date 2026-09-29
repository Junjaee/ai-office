# 토스 실시간 녹음을 작업 스케줄러에 등록한다(사용자 확인 뒤 실행). kis_record\install_task.ps1 과 같은 방식.
#   Toss-record  평일 08:55  record_toss.py --auto --until 15:35 [--candidates <파일>]
# 사용: powershell -ExecutionPolicy Bypass -File automations\toss_record\install_task.ps1 [-Until 15:35] [-Candidates <파일>] [-Remove]
param([string]$Until = "15:35", [string]$Candidates = "", [switch]$Remove)
$name = "Toss-record"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "removed $name"; exit 0 }
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = (Get-Command python).Source
$runner = Join-Path $PSScriptRoot "run_task.cmd"
$logDir = Join-Path $env:LOCALAPPDATA "toss-record\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$jobArgs = "--auto --until $Until"
if ($Candidates) { $jobArgs += " --candidates $Candidates" }
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 8) -StartWhenAvailable -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$recArgs = "`"$runner`" `"$python`" `"$repo`" record_toss.py `"$jobArgs`" `"$logDir`""
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $recArgs" -WorkingDirectory $env:LOCALAPPDATA
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At "08:55"
Register-ScheduledTask -TaskName $name -Description "Toss orderbook/trade recording (weekdays 08:55)" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Registered '$name': weekdays 08:55 -> record_toss.py $jobArgs"
