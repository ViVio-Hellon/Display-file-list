@echo off
rem  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
rem  Keep everything above the chcp line ASCII; see start.bat for why.
chcp 932 >nul 2>&1
rem ===================================================================
rem  ファイル名一覧取得 停止
rem
rem  このアプリだけを止めます。同じPCで動く別の Python アプリには
rem  影響しません(基盤仕様書 2.8)。
rem
rem  戻り値: 0 = 止めた・動いていない / 1 = 止められなかった
rem          2 = リネームの途中なので止めなかった(stop.bat --force で止める)
rem ===================================================================
setlocal
pushd "%~dp0" || (
    echo [エラー] このフォルダに移動できませんでした: %~dp0
    pause
    exit /b 1
)
title ファイル名一覧取得 - 停止

set "RC=1"
python --version >nul 2>&1
if errorlevel 1 (
    echo [エラー] Python が見つかりません。
    goto :failed
)

python process_manager.py %*
set "RC=%errorlevel%"
if not "%RC%"=="0" goto :failed
popd
endlocal
exit /b 0

:failed
pause
popd
endlocal & exit /b %RC%
