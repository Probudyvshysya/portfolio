@echo off
chcp 65001 >nul
rem HR-помощник: запускает модель (Ollama) и страницу. Всё работает только на этом компьютере.
cd /d "%~dp0"
title HR-помощник
set OLLAMA_FLASH_ATTENTION=1
set OLLAMA_KV_CACHE_TYPE=q8_0
set OLLAMA_KEEP_ALIVE=30m
set OLLAMA_MAX_LOADED_MODELS=1
rem Без интернета: проверка фактов только по базе знаний
set HR_INTERNET=0
set PYTHONUTF8=1
set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA_EXE%" (
  echo Не найдена модель Ollama: %OLLAMA_EXE%
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Не найдено окружение .venv. Запустите установку заново.
  pause
  exit /b 1
)
curl -s -m 2 http://127.0.0.1:11434/api/version >nul 2>&1
if errorlevel 1 (
  echo Запускаю модель...
  start "Ollama" /min "%OLLAMA_EXE%" serve
)
curl -s -m 2 http://127.0.0.1:8790/api/sostoyanie 2>nul | find "hr-pomoshchnik" >nul
if not errorlevel 1 (
  start "" http://127.0.0.1:8790
  exit /b 0
)
echo Запускаю HR-помощника. Это окно не закрывайте, пока работаете.
echo Страница откроется в браузере через несколько секунд.
start "" cmd /c "timeout /t 6 >nul & start http://127.0.0.1:8790"
".venv\Scripts\python.exe" -m hr.server
echo.
echo HR-помощник остановился. Если это ошибка, сфотографируйте окно.
pause
