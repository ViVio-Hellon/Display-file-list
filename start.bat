@echo off
rem  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
rem  Everything above the chcp line must stay ASCII: cmd.exe parses a .bat
rem  with the console code page, so the page has to be set before the
rem  first non-ASCII byte. tests/test_launch_files.py enforces this.
chcp 932 >nul 2>&1
rem ===================================================================
rem  ファイル名一覧取得 診断起動
rem
rem  ふだんは Start.vbs を使ってください。こちらは「起動しないとき」に
rem  原因を見るためのもので、コンソールを開いたまま経過を表示します。
rem
rem      start.bat              起動する
rem      start.bat --check      環境の確認だけして終わる
rem ===================================================================
setlocal

rem  共有フォルダ(\\サーバ\...)は現在地にできないので pushd を使う
pushd "%~dp0" || (
    echo [エラー] このフォルダに移動できませんでした: %~dp0
    pause
    exit /b 1
)
title ファイル名一覧取得 - 診断起動 (この窓は閉じないでください)

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [エラー] Python が見つかりません。
    echo   https://www.python.org/downloads/ からインストールし、
    echo   最初の画面で「Add python.exe to PATH」にチェックを入れてください。
    echo.
    goto :failed
)

echo === 実行環境の確認 ===
python start_app.py --check
if errorlevel 1 (
    echo.
    echo 上のメッセージを確認してください。
    goto :failed
)

echo.
echo === 起動 ===
echo この窓を閉じるとアプリが終了します。
echo 終了するときは stop.bat を実行するか、画面の「終了」を押してください。
echo.
python start_app.py %*
if errorlevel 1 (
    echo.
    echo [エラー] 起動に失敗しました。上のメッセージを確認してください。
    echo          ログ: %LOCALAPPDATA%\FileListTool\logs
    echo.
    goto :failed
)

echo.
echo 終了しました。この窓は閉じてかまいません。
pause
popd
endlocal
exit /b 0

:failed
pause
popd
endlocal
exit /b 1
