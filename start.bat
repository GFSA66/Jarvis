@echo off
cd /d "%~dp0"

rem Pick a tested Python (3.13 -> 3.10). The newest (3.14) often has no wheels for PyAudioWPatch/pywin32.
set "PY="
for %%V in (3.13 3.12 3.11 3.10) do if not defined PY (py -%%V -c "" >nul 2>&1 && set "PY=py -%%V")
if not defined PY (where python >nul 2>&1 && set "PY=python")
if not defined PY goto :fail
echo [Jarvis] Python: %PY%

if not exist ".venv\Scripts\python.exe" (
    echo [Jarvis] First run: creating environment and installing dependencies...
    %PY% -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

".venv\Scripts\python.exe" jarvis.py %*
goto :end

:fail
echo.
echo [Jarvis] Could not prepare the environment. Python 3.10-3.13 is required (3.14 is not supported yet).
echo If this window closes by itself, run the .bat from cmd.

:end
pause
