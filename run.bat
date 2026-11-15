@echo off
rem Marswalk Planner - one-command start for Windows.
rem
rem What it does: finds Python 3.10+, creates .venv on the first run, installs
rem requirements.txt (again only when it changed), starts the planner and
rem opens it in your browser.
rem
rem Usage (double-click this file, or from cmd / PowerShell):
rem   run.bat                      start on port 8000
rem   run.bat 8001                 start on port 8001
rem   run.bat --reload             restart the server when code changes
rem   run.bat 8001 --no-browser
rem
rem Flags:
rem   PORT          a number sets the port (default 8000, or env PORT)
rem   --reload      passed to uvicorn, for developers
rem   --no-browser  do not open the browser
rem   --help        show this help
rem
rem Environment variables:
rem   PORT               port to use when none is given on the command line
rem   MARSWALK_PYTHON    path to an existing python.exe that already has the
rem                      requirements; skips .venv and installs (CI / testing)
rem   MARSWALK_NO_PAUSE  set to 1 to skip "press any key" after an error
rem
rem Stop the server with Ctrl+C.

setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "RELOAD="
set "NOBROWSER="
if not defined PORT set "PORT=8000"

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--reload" (set "RELOAD=--reload" & goto next)
if /i "%~1"=="--no-browser" (set "NOBROWSER=1" & goto next)
if /i "%~1"=="--help" goto usage
if /i "%~1"=="-h" goto usage
if /i "%~1"=="/?" goto usage
set "PORT=%~1"
:next
shift
goto parse
:parsed

echo(%PORT%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 goto bad_port
set "PORTNUM="
for /f "tokens=* delims=0" %%a in ("%PORT%") do set "PORTNUM=%%a"
if not defined PORTNUM goto bad_port
if not "%PORTNUM:~5%"=="" goto bad_port
if %PORTNUM% GTR 65535 goto bad_port
set "PORT=%PORTNUM%"

rem ---- pick the Python to use ----
if defined MARSWALK_PYTHON goto given_python

set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto have_venv
call :find_python
if not defined PYBASE goto no_python
echo Creating .venv with: !PYBASE!
!PYBASE! -m venv .venv
if errorlevel 1 goto venv_failed
if not exist "%PY%" goto venv_failed

:have_venv
"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 goto broken_venv

rem ---- install requirements only when requirements.txt changed ----
"%PY%" -c "import hashlib,os,sys;h=hashlib.sha256(open('requirements.txt','rb').read()).hexdigest();s=os.path.join('.venv','.requirements.sha256');sys.exit(0 if os.path.isfile(s) and open(s).read().strip()==h else 1)"
if not errorlevel 1 goto deps_ok

echo Installing dependencies (the first run can take a few minutes)...
"%PY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%PY%" -m pip install --disable-pip-version-check -r requirements.txt
if not errorlevel 1 goto write_stamp

echo.
echo Full install failed. Retrying without rasterio...
set "REQTMP=%TEMP%\marswalk-requirements-no-rasterio.txt"
"%PY%" -c "import re,sys;open(sys.argv[1],'w').writelines(l for l in open('requirements.txt') if not re.match(r'\s*rasterio\b',l,re.I))" "%REQTMP%"
if errorlevel 1 goto install_failed
"%PY%" -m pip install --disable-pip-version-check -r "%REQTMP%"
if errorlevel 1 goto install_failed
del "%REQTMP%" >nul 2>&1
echo Note: installed without rasterio; it is only needed to rebuild map data (build_cube.py).

:write_stamp
"%PY%" -c "import hashlib,os;open(os.path.join('.venv','.requirements.sha256'),'w').write(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())"
goto deps_ok

:given_python
set "PY=%MARSWALK_PYTHON%"
if not exist "%PY%" goto given_missing
echo Using MARSWALK_PYTHON=%PY% (no .venv, no installs)
"%PY%" -c "import fastapi,uvicorn" >nul 2>&1
if errorlevel 1 goto given_no_deps

:deps_ok

rem ---- check the port: exit 0 free, 1 busy (prints a free port), 2 invalid ----
set "PORTFILE=%TEMP%\marswalk-port-%RANDOM%.txt"
"%PY%" -c "import socket,sys;u=lambda q:(lambda c:(c.settimeout(0.3),c.connect_ex(('127.0.0.1',q)),c.close())[1])(socket.socket())==0;p=int(sys.argv[1]);0<p<65536 or sys.exit(2);b=u(p);b and print(next((q for q in range(p+1,min(p+50,65536)) if not u(q)),p+1));sys.exit(1 if b else 0)" %PORT% >"%PORTFILE%" 2>nul
if errorlevel 2 (del "%PORTFILE%" >nul 2>&1 & goto bad_port)
if errorlevel 1 goto port_busy
del "%PORTFILE%" >nul 2>&1

echo.
echo   Marswalk Planner
echo   Planner:   http://localhost:%PORT%/
echo   Gear page: http://localhost:%PORT%/kit.html
echo   Stop:      press Ctrl+C in this window
echo.

if not defined NOBROWSER start "" /b powershell -NoProfile -NonInteractive -Command "for ($i=0; $i -lt 240; $i++) { try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri 'http://127.0.0.1:%PORT%/api/regions' | Out-Null; Start-Process 'http://localhost:%PORT%/'; break } catch { Start-Sleep -Milliseconds 500 } }"

"%PY%" -m uvicorn app:app --host 127.0.0.1 --port %PORT% %RELOAD%
exit /b %ERRORLEVEL%

rem ---- helpers ----
:find_python
set "PYBASE="
call :try_python py -3.12
if not defined PYBASE call :try_python py -3
if not defined PYBASE call :try_python python
if not defined PYBASE call :try_python python3
exit /b 0

:try_python
%* -c "import sys;sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "PYBASE=%*"
exit /b 0

rem ---- messages ----
:usage
echo Usage: run.bat [PORT] [--reload] [--no-browser]
echo   PORT          port to serve on (default 8000, or env PORT)
echo   --reload      restart the server when code changes
echo   --no-browser  do not open the browser
echo Env: PORT, MARSWALK_PYTHON (use this python, skip .venv), MARSWALK_NO_PAUSE=1
exit /b 0

:bad_port
echo Error: "%PORT%" is not a valid port. Use a number from 1 to 65535, e.g. run.bat 8001
goto fail

:port_busy
set "SUGGEST="
set /p SUGGEST=<"%PORTFILE%"
del "%PORTFILE%" >nul 2>&1
echo Error: port %PORT% is already in use (maybe the planner is already running?).
echo   Try another port:     run.bat !SUGGEST!
echo   See what is using it: netstat -ano ^| findstr :%PORT%
goto fail

:no_python
echo Error: Python 3.10 or newer was not found (tried py -3.12, py -3, python, python3).
echo   Install it from https://www.python.org/downloads/
echo   (tick "Add python.exe to PATH" in the installer), then run this again.
goto fail

:venv_failed
if exist .venv rmdir /s /q .venv
echo Error: could not create .venv with !PYBASE! (is the disk full?).
goto fail

:broken_venv
echo Error: .venv exists but its Python does not start (was Python moved or removed?).
echo   Delete the .venv folder and run this again.
goto fail

:install_failed
del "%REQTMP%" >nul 2>&1
echo Error: installing dependencies failed. Check your internet connection and the messages above.
goto fail

:given_missing
echo Error: MARSWALK_PYTHON points to "%PY%", which does not exist.
goto fail

:given_no_deps
echo Error: MARSWALK_PYTHON cannot import fastapi and uvicorn.
echo   Install them first: "%PY%" -m pip install -r requirements.txt
goto fail

:fail
if not defined MARSWALK_NO_PAUSE pause
exit /b 1
