@echo off
rem 시간제보육 예약용 크롬 띄우기.
rem 매크로가 이 크롬에 붙어서(9222 포트) 사람이 로그인해 둔 상태를 그대로 이어받는다.
rem 평소 쓰는 크롬과 따로 노는 전용 프로필이라, 여기서 한 번 로그인해 두면 계속 남는다.

set "PROFILE=%LOCALAPPDATA%\childcare-chrome"

set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo 크롬을 못 찾았어요. chrome.exe 위치를 이 파일에 적어 주세요.
  pause
  exit /b 1
)

start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" "https://www.childcare.go.kr/?menuno=242"
