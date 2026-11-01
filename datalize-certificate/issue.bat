@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\datalize-cert\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [LOI] Chua cai dat tren may nay. Bam dup setup.bat truoc.
  echo.
  pause
  exit /b 1
)

set PYTHONIOENCODING=utf-8
echo ============================================================
echo   DATALIZE CERTIFICATE - CAP CERT VA TU DONG DEPLOY GIT
echo ============================================================
echo.
echo [1/3] Dang cap certificate cho cac dong Ready trong Google Sheet...
echo.

if "%~1"=="" (
  "%PY%" gen.py --sheet
) else (
  "%PY%" gen.py %*
)

if errorlevel 1 (
  echo.
  echo [LOI] Co loi xay ra khi chay gen.py. Sheet chua bi thay doi.
  echo Qua trinh bi dung, khong thuc hien commit hoac deploy len Git.
  echo.
  pause
  exit /b 1
)

echo.
echo [2/3] Sinh certificate thanh cong!
echo.
echo [3/3] Dang dong bo va day len Git (main ^& deploy)...

REM Ve thu muc goc cua Git repository
cd /d "%~dp0.."

REM Fetch de dong bo cac nhanh tu remote
git fetch origin main deploy >nul 2>&1

REM Dong bo truoc neu nhanh main tren remote co commit moi
git merge-base --is-ancestor origin/main HEAD >nul 2>&1
if errorlevel 1 (
  echo   - Dang cap nhat commit moi tu origin/main...
  git pull --rebase origin main >nul 2>&1
)

REM Xu ly bo dem so lan cap certificate (+1 moi lan chay)
set "COUNT_FILE=%~dp0.issue_count"
set ISSUE_COUNT=0
if exist "%COUNT_FILE%" (
  set /p ISSUE_COUNT=<"%COUNT_FILE%"
)
set /a ISSUE_COUNT=ISSUE_COUNT+1
(echo !ISSUE_COUNT!)>"%COUNT_FILE%"

echo   - So thu tu phien cap cert / deploy: #!ISSUE_COUNT!

REM Stage toan bo thay doi
git add -A

REM Kiem tra xem co thay doi nao duoc stage tren main khong
git diff --cached --quiet
if errorlevel 1 (
  echo   - Dang commit vao nhanh main...
  git commit -m "Issue certificates #!ISSUE_COUNT!"
  if errorlevel 1 (
    echo [CANH BAO] Khong the commit vao nhanh main.
  ) else (
    echo   - Dang push len origin/main...
    git push origin main
    if errorlevel 1 (
      echo [LOI] Push origin main that bai. Kiem tra ket noi mang hoac quyen Git.
    ) else (
      echo   [OK] Da push thanh cong len branch main!
    )
  )
) else (
  echo   - Khong co thay doi tren main de commit.
)

REM Xu ly branch deploy (day toan bo thu muc site/ len root cua branch deploy)
set "SITE_TREE="
for /f "tokens=*" %%i in ('git rev-parse HEAD:datalize-certificate/site 2^>nul') do set "SITE_TREE=%%i"

set "DEPLOY_PARENT="
for /f "tokens=*" %%i in ('git rev-parse origin/deploy 2^>nul') do set "DEPLOY_PARENT=%%i"

set "SHORT_SHA="
for /f "tokens=*" %%i in ('git rev-parse --short HEAD 2^>nul') do set "SHORT_SHA=%%i"

if defined SITE_TREE (
  if defined DEPLOY_PARENT (
    echo   - Dang tao commit deploy cho branch deploy...
    set "NEW_DEPLOY_COMMIT="
    for /f "tokens=*" %%c in ('git commit-tree !SITE_TREE! -p !DEPLOY_PARENT! -m "Deploy site #!ISSUE_COUNT! from main !SHORT_SHA!"') do set "NEW_DEPLOY_COMMIT=%%c"
    
    if defined NEW_DEPLOY_COMMIT (
      git update-ref refs/heads/deploy !NEW_DEPLOY_COMMIT!
      echo   - Dang push len origin/deploy...
      git push origin deploy
      if errorlevel 1 (
        echo [LOI] Push origin deploy that bai. Kiem tra ket noi mang hoac quyen Git.
      ) else (
        echo   [OK] Da push thanh cong len branch deploy!
      )
    ) else (
      echo [LOI] Khong the tao commit-tree cho deploy.
    )
  ) else (
    echo [CANH BAO] Khong tim thay origin/deploy tren remote.
  )
) else (
  echo [CANH BAO] Khong tim thay thu muc datalize-certificate/site tren Git.
)

echo.
echo ============================================================
echo   HOAN TAT!
echo   - Phien cap #!ISSUE_COUNT! da hoan tat.
echo   - Da cap nhat va day len GitHub ca 2 nhanh:
echo       * main   : Ma nguon va du lieu portal
echo       * deploy : Toan bo noi dung site de hosting tu dong phat hanh
echo ============================================================
echo.
pause
