@echo off
setlocal

rem 1. Check if standard python works
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY_EXE=python"
    goto :run_py
)

rem 2. Check python3
python3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY_EXE=python3"
    goto :run_py
)

rem 3. Check user local python install
if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Python\bin\python.exe"
    goto :run_py
)

rem 4. Check standard Python versions
for %%P in (315 314 313 312 311 310 39) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%P\python.exe" (
        set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python%%P\python.exe"
        goto :run_py
    )
    if exist "%ProgramFiles%\Python%%P\python.exe" (
        set "PY_EXE=%ProgramFiles%\Python%%P\python.exe"
        goto :run_py
    )
)

echo ERROR: Python 3 is required to run sdlc. Please install Python or ensure it is in your PATH. >&2
exit /b 1

:run_py
endlocal & "%PY_EXE%" "%~dp0sdlc.py" %*
exit /b %ERRORLEVEL%
