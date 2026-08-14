@echo off
chcp 65001 >nul
title Лея — запуск бота
cd /d "%~dp0"

echo ============================================
echo   Запуск бота «Лея»
echo ============================================
echo.

rem --- 1. Проверяем Python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Python не найден.
    echo Установите его с сайта https://www.python.org/downloads/
    echo ВАЖНО: при установке поставьте галочку "Add Python to PATH".
    echo После установки запустите этот файл снова.
    pause
    exit /b 1
)

rem --- 2. Создаём окружение и ставим зависимости (первый раз ~3 минуты) ---
if not exist .venv (
    echo Шаг 1 из 3: готовим окружение... (первый запуск, подождите)
    python -m venv .venv
)
.venv\Scripts\python.exe -m pip install -q -e ".[dev]"

rem --- 3. Проверяем файл .env ---
if not exist .env (
    copy .env.example .env >nul
    echo.
    echo [ВАЖНО] Создан файл настроек .env, но он ещё пустой.
    echo.
    echo Сделайте 3 вещи:
    echo   1. Откройте папку с ботом в Проводнике
    echo      (эта папка, где лежит start_windows.bat)
    echo   2. Найдите файл .env - кликните по нему ПРАВОЙ кнопкой мыши,
    echo      выберите "Открыть с помощью" - "Блокнот"
    echo   3. Найдите строку TELEGRAM_TOKEN= и впишите после неё свой токен
    echo      от BotFather (без пробелов). Сохраните файл (Ctrl+S).
    echo.
    echo Потом запустите start_windows.bat ещё раз.
    pause
    exit /b 0
)

rem --- 4. Миграции базы данных ---
echo Шаг 2 из 3: настраиваем базу данных...
.venv\Scripts\python.exe -m alembic upgrade head

rem --- 5. Запуск ---
echo Шаг 3 из 3: запускаем бота...
echo.
echo Бот работает! Не закрывайте это окно.
echo Чтобы остановить бота - закройте окно.
echo.
.venv\Scripts\python.exe -m src.main
pause
