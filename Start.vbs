' ===================================================================
'  ファイル名一覧取得 起動
'
'  ふだんはこのファイルをダブルクリックするだけです。
'  コンソールを出さずに起動し、画面はブラウザに出ます。
'  起動しないときは start.bat を使うと理由が表示されます。
'  (基盤仕様書 2.1「利用者向けの通常起動ファイルは1つに絞る」)
'
'  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
'  WSH reads a .vbs with the system ANSI code page (932 on Japanese
'  Windows). tests/test_launch_files.py checks it.
' ===================================================================
Option Explicit

Const APP_NAME = "ファイル名一覧取得"

Dim shell, fso, here, script, cmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(here, "start_app.py")

' このファイルだけをデスクトップへコピーすると、本体が見つからず黙って何も起きない。
' ここで気づけるようにする(ショートカットを作るのは大丈夫)
If Not fso.FileExists(script) Then
    MsgBox "start_app.py が見つかりません。" & vbCrLf & vbCrLf & _
           "探した場所: " & script & vbCrLf & vbCrLf & _
           "このファイルは、アプリ一式が入ったフォルダの中から" & vbCrLf & _
           "実行してください(ショートカットを作るのは大丈夫です)。", _
           vbCritical, APP_NAME
    WScript.Quit 1
End If

If shell.Run("cmd /c python --version", 0, True) <> 0 Then
    MsgBox "Python が見つかりません。" & vbCrLf & vbCrLf & _
           "詳しい理由を見るには start.bat を実行してください。", _
           vbCritical, APP_NAME
    WScript.Quit 1
End If

If shell.Run("cmd /c pythonw --version", 0, True) <> 0 Then
    MsgBox "pythonw が見つかりません。" & vbCrLf & vbCrLf & _
           "start.bat から起動してください(コンソールが開きます)。", _
           vbCritical, APP_NAME
    WScript.Quit 1
End If

' pythonw はコンソールを出さない。起動したら待たずに戻る(False)。
' 失敗は start_app.py が画面かメッセージで知らせる。パスは絶対パスで渡す
shell.CurrentDirectory = here
cmd = "pythonw " & Chr(34) & script & Chr(34)
shell.Run cmd, 0, False
