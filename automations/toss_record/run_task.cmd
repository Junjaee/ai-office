@echo off
rem run_task.cmd <python> <repo> <script.py> "<args>" <logdir> - wait up to 10 min for the drive (G:) then run the script. Monthly log files.
set PY=%~1
set REPO=%~2
set SCRIPT=%REPO%\automations\toss_record\%~3
set ARGS=%~4
set LOGDIR=%~5
set LOG=%LOGDIR%\%~n3_%date:~0,4%%date:~5,2%.log
set /a tries=0
:wait
if exist "%SCRIPT%" goto run
set /a tries+=1
if %tries% geq 20 (echo [%date% %time%] script not found: %SCRIPT% >> "%LOG%" & exit /b 6)
timeout /t 30 /nobreak > nul
goto wait
:run
echo [%date% %time%] start %~3 %ARGS% >> "%LOG%"
"%PY%" "%SCRIPT%" %ARGS% >> "%LOG%" 2>&1
echo [%date% %time%] exit %errorlevel% >> "%LOG%"
