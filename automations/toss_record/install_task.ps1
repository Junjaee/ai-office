# 토스 실시간 녹음·백필을 작업 스케줄러에 등록한다(사용자 확인 뒤 실행).
#   Toss-record    평일 08:55  start_record.ps1 -Until 15:35 (숨긴 창, 끝날 때까지 대기)
#   Toss-backfill  평일 15:40  start_backfill.ps1 (분봉 목표 목록 → 수급 전 종목, 08:40 전에 멈춤)
# 사용: powershell -ExecutionPolicy Bypass -File automations\toss_record\install_task.ps1 [-Until 15:35] [-Candidates <파일>] [-Remove]
# cmd 콘솔 창으로 띄우지 않는 이유는 start_record.ps1 머리말 참고(창을 닫으면 녹음이 죽는다, 2026-09-29 실측).
param([string]$Until = "15:35", [string]$Candidates = "", [switch]$Remove)
$names = @("Toss-record", "Toss-backfill")
if ($Remove) { foreach ($n in $names) { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "removed $n" }; exit 0 }
$ps = (Get-Command powershell.exe).Source
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 18) -StartWhenAvailable -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$rec = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_record.ps1')`" -Until $Until"
if ($Candidates) { $rec += " -Candidates `"$Candidates`"" }
$bf = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'start_backfill.ps1')`""
$jobs = @(
    @{ Name = "Toss-record";   At = "08:55"; Args = $rec; Desc = "Toss orderbook/trade recording (weekdays 08:55)" },
    @{ Name = "Toss-backfill"; At = "15:40"; Args = $bf;  Desc = "Toss minutes/flows backfill after close (weekdays 15:40)" }
)
foreach ($j in $jobs) {
    $action = New-ScheduledTaskAction -Execute $ps -Argument $j.Args -WorkingDirectory $env:USERPROFILE
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $j.At
    Register-ScheduledTask -TaskName $j.Name -Description $j.Desc -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Registered '$($j.Name)': weekdays $($j.At)"
}
Get-ScheduledTask -TaskName "Toss-*" | Select-Object TaskName, State | Format-Table -AutoSize
