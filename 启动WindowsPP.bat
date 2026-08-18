@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 WindowsPP.py %*
  goto :end
)
where python >nul 2>nul
if %errorlevel%==0 (
  python WindowsPP.py %*
  goto :end
)
echo [Windows++] Python not found. Please install Python 3 from https://python.org
pause
:end
