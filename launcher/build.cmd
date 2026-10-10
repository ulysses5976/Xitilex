@echo off
rem 重新編譯「律法夕惕者.exe」與「安裝.exe」（改了 Launcher.cs 或圖示後執行）
chcp 65001 >nul
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
set HERE=%~dp0
set OUT=%HERE%..
"%CSC%" /nologo /codepage:65001 /target:winexe /win32icon:"%OUT%\frontend\xitilex.ico" /r:System.Windows.Forms.dll /out:"%OUT%\律法夕惕者.exe" "%HERE%Launcher.cs" || goto :err
"%CSC%" /nologo /codepage:65001 /target:exe /define:INSTALLER /win32icon:"%OUT%\frontend\xitilex.ico" /r:System.Windows.Forms.dll /out:"%OUT%\安裝.exe" "%HERE%Launcher.cs" || goto :err
echo 編譯完成。
goto :eof
:err
echo 編譯失敗。
exit /b 1
