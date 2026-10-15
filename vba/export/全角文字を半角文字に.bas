Attribute VB_Name = "全角文字を半角文字に"
Option Explicit

' * 指定フォルダ内のすべてのファイルの全角文字を半角文字に変換してリネームする
' * @param folderPath リネーム対象のフォルダパス
' * @param recursive サブフォルダも処理する場合はTrue（デフォルト：False）
' * @return 処理結果（成功した場合True、失敗した場合False）
Public Function RenameFilesZenkakuToHankaku(folderPath As String, Optional recursive As Boolean = False, Optional renameFolders As Boolean = False) As Boolean
Dim fso As Object
Dim folder As Object
Dim file As Object
Dim subFolder As Object
Dim originalName As String
Dim newName As String
Dim renameCount As Long
Dim errorCount As Long
Dim subFolders As Collection
Dim sf As Variant

' FileSystemObjectを初期化
Set fso = CreateObject("Scripting.FileSystemObject")

' フォルダの存在確認
If Not fso.FolderExists(folderPath) Then
    Debug.Print "エラー: 指定されたフォルダが存在しません - " & folderPath
    RenameFilesZenkakuToHankaku = False
    Exit Function
End If

On Error GoTo ErrorHandler

Set folder = fso.GetFolder(folderPath)
renameCount = 0
errorCount = 0

Debug.Print "処理開始: " & folderPath

' フォルダ内のファイルを処理
For Each file In folder.Files
    originalName = file.Name
    newName = ConvertZenkakuToHankaku(originalName)
    
    Debug.Print "チェック中: " & originalName & " → " & newName & " (変更必要: " & (originalName <> newName) & ")"
    
    ' ファイル名に変更がある場合のみリネーム実行
    If originalName <> newName Then
        If RenameFile(file.Path, fso.BuildPath(file.parentFolder.Path, newName)) Then
            Debug.Print "リネーム成功: " & originalName & " → " & newName
            renameCount = renameCount + 1
        Else
            Debug.Print "リネーム失敗: " & originalName
            errorCount = errorCount + 1
        End If
    End If
Next file

' 直下のサブフォルダ名のリネーム処理（renameFolders = Trueの場合）
If renameFolders Then
    Set subFolders = New Collection
    
    ' サブフォルダ名とパスを記録
    For Each subFolder In folder.subFolders
        subFolders.Add Array(subFolder.Name, subFolder.Path)
    Next subFolder
    
    ' フォルダ名をリネーム
    For Each sf In subFolders
        originalName = sf(0)
        newName = ConvertZenkakuToHankaku(originalName)
        
        If originalName <> newName Then
            Dim oldPath As String
            Dim newPath As String
            oldPath = sf(1)
            newPath = fso.BuildPath(fso.GetParentFolderName(oldPath), newName)
            
            If RenameFolder(oldPath, newPath, fso) Then
                Debug.Print "フォルダリネーム成功: " & originalName & " → " & newName
                renameCount = renameCount + 1
            Else
                Debug.Print "フォルダリネーム失敗: " & originalName
                errorCount = errorCount + 1
            End If
        End If
    Next sf
End If

' サブフォルダの再帰処理（recursive = Trueの場合）
If recursive Then
    ' 更新されたフォルダ情報を再取得
    Set folder = fso.GetFolder(folderPath)
    Set subFolders = New Collection
    For Each subFolder In folder.subFolders
        subFolders.Add subFolder.Path
    Next subFolder
    
    ' 各サブフォルダを再帰的に処理
    For Each sf In subFolders
        If fso.FolderExists(sf) Then
            If Not RenameFilesZenkakuToHankaku(CStr(sf), True, renameFolders) Then
                errorCount = errorCount + 1
            End If
        End If
    Next sf
End If

Debug.Print "処理完了: リネーム成功 " & renameCount & " 件, エラー " & errorCount & " 件"

RenameFilesZenkakuToHankaku = (errorCount = 0)
Exit Function

ErrorHandler:
Debug.Print "エラーが発生しました: " & Err.Description
RenameFilesZenkakuToHankaku = False
End Function

' フォルダリネーム用のヘルパー関数
Private Function RenameFolder(oldPath As String, newPath As String, fso As Object) As Boolean
On Error GoTo ErrorHandler

If fso.FolderExists(newPath) Then
    Debug.Print "リネーム先フォルダが既に存在します: " & newPath
    RenameFolder = False
    Exit Function
End If

fso.GetFolder(oldPath).Name = fso.GetFileName(newPath)
RenameFolder = True
Exit Function

ErrorHandler:
Debug.Print "フォルダリネームエラー: " & Err.Description
RenameFolder = False
End Function

Public Sub ExecuteRenameBasicErrorHandling()
On Error GoTo ErrorHandler
Dim fso As Object
Set fso = CreateObject("Scripting.FileSystemObject")
' 入力チェック
If UF.T2.Text = "" Then Exit Sub
Dim folderPath As String
folderPath = Trim(UF.T2.Text)
' "ThisWorkbook.Path"文字列を実際のパスに置き換え
If folderPath = "ThisWorkbook.Path" Then
    folderPath = ThisWorkbook.Path
    Debug.Print "ThisWorkbook.Pathに置き換え: " & folderPath
End If
' フォルダの存在チェック
If Not fso.FolderExists(folderPath) Then
    Debug.Print "フォルダが存在しません: " & folderPath
    Exit Sub
End If
Dim parentFolder As Object
Set parentFolder = fso.GetFolder(folderPath)
Debug.Print "フォルダ名: " & parentFolder.Name
Debug.Print "フルパス: " & parentFolder.Path

' チェックボックスの状態を取得してフォルダリネームを制御
Dim shouldRenameFolders As Boolean
shouldRenameFolders = UF.FolderTrue.Value  ' チェックボックスの値を取得

' リネーム実行（recursive = Falseでも直下フォルダはリネーム可能）
RenameFilesZenkakuToHankaku folderPath, False, shouldRenameFolders
Exit Sub
ErrorHandler:
Debug.Print "エラー発生: " & Err.Description & " (パス: " & folderPath & ")"
On Error Resume Next
Set parentFolder = Nothing
Set fso = Nothing
End Sub



' * 全角文字を半角文字に変換する（修正版）
' * @param inputStr 変換対象の文字列
' * @return 変換後の文字列
Private Function ConvertZenkakuToHankaku(inputStr As String) As String
Dim result As String
Dim i As Long
Dim char As String
Dim asciiCode As Long

result = ""

For i = 1 To Len(inputStr)
    char = Mid(inputStr, i, 1)
    asciiCode = AscW(char)
    
    ' 負の値を正の値に変換 (Unicode文字で発生する場合がある)
    If asciiCode < 0 Then
        asciiCode = asciiCode + 65536
    End If
    
    Select Case asciiCode
        ' 全角英字大文字 (Ａ～Ｚ) → 半角 (A～Z)
        Case 65313 To 65338  ' &HFF21 To &HFF3A
            result = result & Chr(asciiCode - 65313 + 65) ' 65 = Asc("A")
        
        ' 全角英字小文字 (ａ～ｚ) → 半角 (a～z)
        Case 65345 To 65370  ' &HFF41 To &HFF5A
            result = result & Chr(asciiCode - 65345 + 97) ' 97 = Asc("a")
            
        ' 全角数字 (０～９) → 半角 (0～9)
        Case 65296 To 65305  ' &HFF10 To &HFF19
            result = result & Chr(asciiCode - 65296 + 48)  ' 48 = Asc("0")
        
        ' 全角スペース (　) → 半角 ( )
        Case 12288  ' &H3000
            result = result & " "
        
        ' その他の全角記号の変換
        Case 65281: result = result & "!"       ' ！ → !
        Case 65282: result = result & Chr(34)   ' " → "
        Case 65283: result = result & "#"       ' ＃ → #
        Case 65284: result = result & "$"       ' ＄ → $
        Case 65285: result = result & "%"       ' ％ → %
        Case 65286: result = result & "&"       ' ＆ → &
        Case 65287: result = result & "'"       ' ' → '
        Case 65288: result = result & "("       ' （ → (
        Case 65289: result = result & ")"       ' ） → )
        Case 65290: result = result & "*"       ' ＊ → *
        Case 65291: result = result & "+"       ' ＋ → +
        Case 65292: result = result & ","       ' ， → ,
        Case 65293: result = result & "-"       ' － → -
        Case 65294: result = result & "."       ' ． → .
        Case 65295: result = result & "/"       ' ／ → /
        Case 65306: result = result & ":"       ' ： → :
        Case 65307: result = result & ";"       ' ； → ;
        Case 65308: result = result & "<"       ' ＜ → <
        Case 65309: result = result & "="       ' ＝ → =
        Case 65310: result = result & ">"       ' ＞ → >
        Case 65311: result = result & "?"       ' ？ → ?
        Case 65312: result = result & "@"       ' ＠ → @
        Case 65339: result = result & "["       ' ［ → [
        Case 65340: result = result & "\"       ' ＼ → \
        Case 65341: result = result & "]"       ' ］ → ]
        Case 65342: result = result & "^"       ' ＾ → ^
        Case 65343: result = result & "_"       ' ＿ → _
        Case 65344: result = result & "`"       ' ｀ → `
        Case 65371: result = result & "{"       ' ｛ → {
        Case 65372: result = result & "|"       ' ｜ → |
        Case 65373: result = result & "}"       ' ｝ → }
        Case 65374: result = result & "~"       ' ～ → ~
        
        Case Else
            ' 変換対象外の文字はそのまま連結
            result = result & char
    End Select
Next i

ConvertZenkakuToHankaku = result
End Function
' * ファイルのリネームを実行する（既存ファイル対応版）
' * @param oldPath 元のファイルパス
' * @param newPath 新しいファイルパス
' * @return 処理結果（成功した場合True、失敗した場合False）
Private Function RenameFile(oldPath As String, newPath As String) As Boolean
Dim fso As Object
Set fso = CreateObject("Scripting.FileSystemObject")

On Error GoTo ErrorHandler

' 新しいファイル名が既に存在する場合、番号を付ける
If fso.FileExists(newPath) Then
    Dim baseName As String
    Dim extension As String
    Dim folderPath As String
    Dim counter As Long  ' Integer → Long に変更
    Dim testPath As String
    
    baseName = fso.GetBaseName(newPath)
    extension = fso.GetExtensionName(newPath)
    folderPath = fso.GetParentFolderName(newPath)
    
    counter = 1
    Do
        If extension <> "" Then
            testPath = fso.BuildPath(folderPath, baseName & "_" & counter & "." & extension)
        Else
            testPath = fso.BuildPath(folderPath, baseName & "_" & counter)
        End If
        counter = counter + 1
    Loop While fso.FileExists(testPath)
    
    newPath = testPath
    Debug.Print "既存ファイルのため番号付き: " & fso.GetFileName(newPath)
End If

' ファイル名の変更を実行
fso.MoveFile oldPath, newPath
RenameFile = True
Exit Function

ErrorHandler:
Debug.Print "リネームエラー: " & Err.Description & " (" & oldPath & " → " & newPath & ")"
RenameFile = False
End Function
' * デバッグ用：特定ファイル名の変換確認（詳細版）
Public Sub DebugSpecificFilesDetailed()
Debug.Print "=== 詳細変換テスト ==="
Dim i As Long
Dim testFiles As Variant
testFiles = Array("ＧＧＬ9アｂｃｒ.txt", "＿  ＿～.txt")

Dim j As Long
For j = 0 To UBound(testFiles)
    Dim testStr As String
    testStr = testFiles(j)
    
    Debug.Print "=== テスト文字列: " & testStr & " ==="
    
    For i = 1 To Len(testStr)
        Dim char As String
        Dim rawCode As Long
        Dim adjustedCode As Long
        
        char = Mid(testStr, i, 1)
        rawCode = AscW(char)
        adjustedCode = rawCode
        
        ' 負の値を正の値に変換
        If adjustedCode < 0 Then
            adjustedCode = adjustedCode + 65536
        End If
        
        Debug.Print "文字[" & i & "]: " & char & " 生コード: " & rawCode & " 調整後: " & adjustedCode & " (16進: &H" & Hex(adjustedCode) & ")"
        
        ' 変換対象かチェック
        Dim isTarget As Boolean
        Dim convertedChar As String
        isTarget = False
        convertedChar = char
        
        Select Case adjustedCode
            Case 65296 To 65305  ' 全角数字
                isTarget = True
                convertedChar = Chr(adjustedCode - 65296 + 48)
            Case 65313 To 65338  ' 全角英大文字
                isTarget = True
                convertedChar = Chr(adjustedCode - 65313 + 65)
            Case 65345 To 65370  ' 全角英小文字
                isTarget = True
                convertedChar = Chr(adjustedCode - 65345 + 97)
            Case 12288  ' 全角スペース
                isTarget = True
                convertedChar = " "
            Case 65295: convertedChar = "_": isTarget = True  ' _
            Case 65374: convertedChar = "~": isTarget = True  ' ～
        End Select
        
        Debug.Print "  → 変換対象: " & isTarget & " 変換後文字: " & convertedChar
    Next i
    
    Debug.Print "変換結果: " & ConvertZenkakuToHankaku(testStr)
    Debug.Print "変換必要: " & (testStr <> ConvertZenkakuToHankaku(testStr))
    Debug.Print ""
Next j
End Sub
