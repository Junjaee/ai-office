# 토스 실시간 녹음·백필을 작업 스케줄러에 등록한다(사용자 확인 뒤 실행).
#   Toss-record    평일 08:55  start_record.ps1 -Until 15:35 (숨긴 창, 끝날 때까지 대기)
#   Toss-backfill  평일 15:40  start_backfill.ps1 (분봉 목표 목록 → 수급 전 종목, 08:40 전에 멈춤)
#   Toss-record-logon  로그온할 때  start_record.ps1 — 08:55 에 PC 가 꺼져 있었으면(2026-09-30 실측: 08:54 부팅, 로그온 전이라 08:55 작업이 안 뜸)
#                      켜서 로그인하는 순간 대신 시작한다. 장 시간(평일 08:40~15:20) 밖이면 start_record.ps1 이 바로 끝난다.
# 사용: powershell -ExecutionPolicy Bypass -File automations\toss_record\install_task.ps1 [-Until 15:35] [-Candidates <파일>] [-Only Toss-record-logon] [-Remove]
# cmd 콘솔 창으로 띄우지 않는 이유는 start_record.ps1 머리말 참고(창을 닫으면 녹음이 죽는다, 2026-09-29 실측).
param([string]$Until = "15:35", [string]$Candidates = "", [string[]]$Only = @(), [switch]$Remove)
$names = @("Toss-record", "Toss-backfill", "Toss-record-logon")
if ($Remove) { foreach ($n in $names) { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "removed $n" }; exit 0 }
$ps = (Get-Command powershell.exe).Source
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 18) -StartWhenAvailable -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
# 스크립트가 구글 드라이브(G:) 안에 있어 "-File G:\..." 로 부르면 드라이브가 붙기 전에는 파일이 없어 바로 죽는다
# (2026-10-01 실측: 08:55:14 로그온 → 08:55:45 작업 시작 → 드라이브는 08:56:29 에 붙음, 종료 코드 -196608).
# 그래서 작업 명령 안에서 스크립트가 보일 때까지 최대 10분 기다린 뒤 부른다.
$wait = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "& {{ $s = ''{0}''; $n = 0; while (-not (Test-Path -LiteralPath $s) -and $n -lt 60) {{ Start-Sleep -Seconds 10; $n++ }}; & $s {1}; exit $LASTEXITCODE }}"'
$recArgs = "-Until $Until"
if ($Candidates) { $recArgs += " -Candidates '$Candidates'" }
$rec = $wait -f (Join-Path $PSScriptRoot 'start_record.ps1'), $recArgs
$bf = $wait -f (Join-Path $PSScriptRoot 'start_backfill.ps1'), ""
$jobs = @(
    @{ Name = "Toss-record";   At = "08:55"; Args = $rec; Desc = "Toss orderbook/trade recording (weekdays 08:55)" },
    @{ Name = "Toss-backfill"; At = "15:40"; Args = $bf;  Desc = "Toss minutes/flows backfill after close (weekdays 15:40)" },
    @{ Name = "Toss-record-logon"; At = "logon"; Args = $rec; Desc = "Toss recording fallback: start at logon if the 08:55 run was missed (market hours only)" }
)
foreach ($j in $jobs) {
    if ($Only.Count -gt 0 -and $Only -notcontains $j.Name) { continue }
    $action = New-ScheduledTaskAction -Execute $ps -Argument $j.Args -WorkingDirectory $env:USERPROFILE
    if ($j.At -eq "logon") { $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; $trigger.Delay = "PT30S" }
    else { $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $j.At }
    Register-ScheduledTask -TaskName $j.Name -Description $j.Desc -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Registered '$($j.Name)': $($j.At)"
}
Get-ScheduledTask -TaskName "Toss-*" | Select-Object TaskName, State | Format-Table -AutoSize
