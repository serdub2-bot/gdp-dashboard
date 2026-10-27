@echo off
chcp 65001 >nul
title Поиск базы Football Manager 2008
echo.
echo   Ищу, где на дисках лежит база FM2008.
echo   Займёт минуту-две, окно закроется по нажатию клавиши.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find-db.ps1"
echo.
echo   Отчёт лежит рядом со скриптом: FM_found_databases.txt
echo   Пришлите его текст - по нему видно, куда смотрит игра.
echo.
pause
