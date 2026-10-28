@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\datalize-cert\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Chua cai dat tren may nay. Bam dup setup.bat truoc.
  pause
  exit /b 1
)
set PYTHONIOENCODING=utf-8
echo Dang cap certificate cho cac dong Ready trong Google Sheet...
echo.
"%PY%" gen.py --sheet
if errorlevel 1 (
  echo.
  echo [LOI] Xem thong bao o tren. Sheet chua bi thay doi.
) else (
  echo.
  echo Xong. Cac dong Ready da chuyen sang Issued kem cert_link.
  echo Buoc tiep theo: upload thu muc site\ len hosting roi gui cert_link cho hoc vien.
)
pause
