@echo off
rem 시간제보육 예약기를 exe 하나로 묶는다.
rem 구글 드라이브 폴더에서 빌드하면 수만 개 임시 파일이 클라우드로 올라가므로
rem 작업은 드라이브 밖(%LOCALAPPDATA%)에서 하고 결과 exe 만 개인 폴더로 가져온다.

setlocal
set "SRC=%~dp0"
set "WORK=%LOCALAPPDATA%\childcare-build"
set "OUT=%SRC%..\..\ai-home\04_시간제보육"

if not exist "%WORK%" mkdir "%WORK%"

python -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name "시간제보육예약기" ^
  --paths "%SRC%" ^
  --hidden-import childcare_site ^
  --hidden-import launcher ^
  --collect-all playwright ^
  --distpath "%WORK%\dist" --workpath "%WORK%\build" --specpath "%WORK%" ^
  "%SRC%app.py"

if errorlevel 1 (
  echo.
  echo 빌드 실패.
  pause
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
copy /y "%WORK%\dist\시간제보육예약기.exe" "%OUT%\" >nul
echo.
echo 완성: %OUT%\시간제보육예약기.exe
pause
