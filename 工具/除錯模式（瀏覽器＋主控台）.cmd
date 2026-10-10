@echo off
chcp 65001 >nul
rem 除錯用：有主控台視窗、改用瀏覽器開啟，錯誤訊息會直接顯示
set PYTHONDONTWRITEBYTECODE=1
title 律法夕惕者 Xitilex（除錯模式）
where py >nul 2>nul && (py -3 "%~dp0..\run.py" --browser) || (python "%~dp0..\run.py" --browser)
pause
