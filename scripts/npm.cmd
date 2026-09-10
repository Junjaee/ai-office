@echo off
rem Windows 명령 프롬프트·미리보기 도구에서 scripts/npm.sh 를 Git Bash 로 실행한다.
rem (그냥 bash 라고 부르면 WSL 의 bash 가 잡혀 드라이브 경로를 못 읽는다)
rem 사용: scripts\npm.cmd test ^| tsc ^| build ^| dev --port 3011
setlocal
set "GITBASH=%ProgramFiles%\Git\bin\bash.exe"
if not exist "%GITBASH%" for /f "delims=" %%G in ('where git 2^>nul') do set "GITBASH=%%~dpG..\bin\bash.exe"
if not exist "%GITBASH%" (echo Git Bash 를 찾지 못했습니다. Git for Windows 를 설치하세요.& exit /b 1)
cd /d "%~dp0.."
"%GITBASH%" scripts/npm.sh %*
