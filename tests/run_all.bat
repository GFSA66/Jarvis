@echo off
rem Полный прогон тестов Джарвиса (регрессионная матрица). Запускай из корня проекта.
rem Использование: tests\run_all.bat   (или двойным щелчком)
cd /d "%~dp0\.."

rem Берём протестированный Python (3.13 -> 3.10; 3.14 пока без колёс pywin32).
set "PY="
for %%V in (3.13 3.12 3.11 3.10) do if not defined PY (py -%%V -c "" >nul 2>&1 && set "PY=py -%%V")
if not defined PY (where python >nul 2>&1 && set "PY=python")
if not defined PY (
    echo [FAIL] Не найден Python 3.10-3.13. Установи Python и повтори.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo [i] Создаю виртуальное окружение .venv...
    %PY% -m venv .venv || goto :fail
)

rem Быстрая проверка, что все модули хотя бы компилируются.
echo [1/2] Проверка синтаксиса модулей...
".venv\Scripts\python.exe" -m py_compile ^
    jarvis.py jarvis_ai.py jarvis_settings.py jarvis_utils.py jarvis_system.py ^
    jarvis_stt.py jarvis_intents.py jarvis_routing.py jarvis_history.py ^
    jarvis_timers.py jarvis_integrations.py jarvis_voice_piper.py jarvis_dictation.py ^
    tools\eval_stt.py || goto :fail
echo [ok] Все модули компилируются.

rem Полный набор pytest.
echo [2/2] Прогон тестов...
".venv\Scripts\python.exe" -m pytest tests -q -p no:cacheprovider || goto :fail

echo.
echo [DONE] Все тесты пройдены.
exit /b 0

:fail
echo.
echo [FAIL] Тесты не пройдены. Смотри вывод выше.
pause
exit /b 1
