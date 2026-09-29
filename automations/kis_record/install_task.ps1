# 윈도우 작업 스케줄러에 평일 작업 세 개를 등록한다 (Windows PowerShell 5.1, 파일은 UTF-8 BOM). 사용자 확인 뒤 실행.
#   KIS-record    08:50  웹소켓 녹음(record.py --picks auto --mode both --until 15:35)
#   KIS-snapshot  08:55  호가 스냅샷(kis_snapshot.py --n 150 --until 15:35)
#   KIS-minutes   15:45  오늘 전 종목 1분봉(kis_minutes.py --eod --stop-at 23:30)
# 사용: powershell -ExecutionPolicy Bypass -File automations\kis_record\install_task.ps1 [-Mode both|asp] [-Until 15:35] [-SnapshotN 150] [-Only record|snapshot|minutes]
# 확인: Get-ScheduledTask -TaskName KIS-* | Get-ScheduledTaskInfo
param(
    [string]$Mode = "both",
    [string]$Until = "15:35",
    [int]$SnapshotN = 150,
    [string]$Only = ""
)
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = (Get-Command python).Source
$runner = Join-Path $PSScriptRoot "run_task.cmd"
$logDir = Join-Path $env:USERPROFILE "ai-office-data\kis-record\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 9) -StartWhenAvailable -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$jobs = @(
    @{ Name = "KIS-record";   At = "08:50"; Script = "record.py";       Args = "--picks auto --mode $Mode --until $Until";  Desc = "KIS websocket recording (weekdays 08:50)" },
    @{ Name = "KIS-snapshot"; At = "08:55"; Script = "kis_snapshot.py"; Args = "--n $SnapshotN --until $Until";            Desc = "KIS orderbook snapshots (weekdays 08:55)" },
    @{ Name = "KIS-minutes";  At = "15:45"; Script = "kis_minutes.py";  Args = "--eod --stop-at 23:30";                    Desc = "KIS 1-minute bars for today (weekdays 15:45)" }
)
foreach ($j in $jobs) {
    if ($Only -and $j.Name -ne "KIS-$Only") { continue }
    $recArgs = "`"$runner`" `"$python`" `"$repo`" $($j.Script) `"$($j.Args)`" `"$logDir`""
    # cmd /c 는 첫 글자가 따옴표면 첫·끝 따옴표를 떼 버리므로 전체를 한 번 더 감싼다(2026-09-29 토스 작업에서 확인)
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$recArgs`"" -WorkingDirectory $env:USERPROFILE
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $j.At
    Register-ScheduledTask -TaskName $j.Name -Description $j.Desc -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Registered '$($j.Name)': weekdays $($j.At) -> $($j.Script) $($j.Args)"
}
Get-ScheduledTask -TaskName "KIS-*" | Select-Object TaskName, State | Format-Table -AutoSize
