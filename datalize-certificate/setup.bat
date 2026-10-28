@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\datalize-cert\venv"
echo Cai dat moi truong cho Datalize Certificate (chi can chay 1 lan tren moi may)...
echo.
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
if not exist "%VENV%\Scripts\python.exe" (
  %PY% -m venv "%VENV%" || goto :fail
)
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip -q
"%VENV%\Scripts\python.exe" -m pip install -r requirements.txt -q || goto :fail
"%VENV%\Scripts\python.exe" -m playwright install chromium || goto :fail
echo.
if not exist "data\service-account.json" (
  echo [!] Chua co file data\service-account.json. Xin file nay tu admin roi chep vao thu muc data\ - xem README, muc Google Sheet.
)
echo Xong. Tu gio bam dup issue.bat de cap certificate.
pause
exit /b 0

:fail
echo.
echo [LOI] Cai dat that bai. Kiem tra da cai Python 3.10 tro len (python.org, nho tick "Add python.exe to PATH") roi chay lai setup.bat.
pause
exit /b 1
