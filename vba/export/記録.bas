Attribute VB_Name = "記録"
'*********************************************************
' 　　指定フォルダ内のファイル名一覧を取得
'*********************************************************
Public Sub Get_FileName()
    Const cnsTitle = "ファイル名一覧取得"
    Const cnsDIR = "\*.*"
    Dim xlAPP As Application
    Dim strPath As String
    Dim strFilename As String, strF As String
    Dim GYO As Long

    Dim fileName As String
    Dim fileExt As String
    Dim fileDate As Date
    
    Set xlAPP = Application
    ' フォルダの場所を指定する
    Dim flag As Boolean: flag = False
    Select Case True
    Case UF.OBA:    strF = "A班"
    Case UF.OBB:    strF = "B班"
    Case UF.OBC:    strF = "C班"
    Case UF.OBD:    strF = "D班"
    Case UF.OBHIRU: strF = "日勤"
    Case Else:      flag = True
    End Select
    strPath = ThisWorkbook.Path & "\" & strF 'OBのどれかがtrue
    If flag Then strPath = ThisWorkbook.Path 'trueなし

    ' フォルダの存在確認 --- 必要な場合のみ記述 ---
    If Dir(strPath, vbDirectory) = "" Then
        MsgBox "指定のフォルダは存在しません。", vbExclamation, cnsTitle
        Exit Sub
    End If
    
    If WsCheck("一覧") = False Then
      Call AddWS("一覧")
    End If
    
    Dim WS As Worksheet: Set WS = ThisWorkbook.Sheets("一覧")
    Dim LastR As Long: LastR = WS.Cells(Rows.Count, 3).End(xlUp).Row
    
    Dim Temp, LongT
 
    WS.Cells.ClearContents 'クリア
 
    ' 先頭のファイル名の取得
    strFilename = Dir(strPath & cnsDIR, vbNormal)
    Dim Buf
    ' ファイルが見つからなくなるまで繰り返す
    '6-4-2-3_新５点バキューム作業***************文書番号_作業名
    
    ' フォルダ内のファイルを取得_2023.10.31＊修正
    Dim fso As Object
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set folder = fso.GetFolder(strPath)
    GYO = 1
    For Each file In folder.Files
        fileName = file.Name
        fileDate = file.DateLastModified
        Temp = Split(fileName, "_")
        Dim Cont As Long: Cont = UBound(Temp)
        
        If Cont = 1 Then '_の有無対策
          LongT = Split(Temp(0), "-")
          If (Temp(0) <> "") And (Not IsEmpty(LongT)) Then WS.Cells(GYO, 1) = Val(LongT(0)) '配列がある　かつ　空欄でない
          WS.Cells(GYO, 2).Value = "'" & Temp(0)
          Buf = Split(Temp(1), ".")
          If (Buf(0) <> "") And (Not IsEmpty(Buf)) Then WS.Cells(GYO, 3) = Buf(0)
          If (Buf(0) <> "") And (Not IsEmpty(Buf)) Then WS.Cells(GYO, 5) = Buf(UBound(Buf))
          WS.Cells(GYO, 4) = fileDate 'FileDateTime(strPath & "\" & strFilename)
          If WS.Cells(GYO, 1) = 0 Then WS.Cells(GYO, 1).Value = "" 'ファイル名に_の使用があるが数字ではない場合
        ElseIf Cont = 0 Then
          Dim LenCount As Long:   LenCount = Len(fileName)
          Dim InStrCount As Long: InStrCount = InStrRev(fileName, ".") '最後の文字位置から検索
          fileExt = Right(fileName, LenCount - InStrCount)
          Dim strC As String:     strC = Replace(fileName, "." & fileExt, "") '拡張子をファイル名から取り除く
          
          WS.Cells(GYO, 3) = strC
          WS.Cells(GYO, 5) = fileExt
          WS.Cells(GYO, 4) = fileDate
        End If
        GYO = GYO + 1 ' 行を加算
    Next file
 'こちらのコード使用時　_や.をファイル名に多用しているとファイル名がすべて表示できない
'    Do While strFilename <> ""
'        Temp = Split(strFilename, "_") '_でわける
'        Dim Cont As Long: Cont = UBound(Temp)
'          If Cont = 1 Then '_の有無対策
'            LongT = Split(Temp(0), "-")
'            GYO = GYO + 1 ' 行を加算
'            If (Temp(0) <> "") And (Not IsEmpty(LongT)) Then WS.Cells(GYO, 1).Value = Val(LongT(0)) '配列がある　かつ　空欄でない
'            WS.Cells(GYO, 2).Value = "'" & Temp(0)
'            Buf = Split(Temp(1), ".")
'            If (Buf(0) <> "") And (Not IsEmpty(Buf)) Then WS.Cells(GYO, 3).Value = Buf(0)
'            If (Buf(0) <> "") And (Not IsEmpty(Buf)) Then WS.Cells(GYO, 5).Value = Buf(UBound(Buf))
'            WS.Cells(GYO, 4).Value = FileDateTime(strPath & "\" & strFilename)
'            If WS.Cells(GYO, 1) = 0 Then WS.Cells(GYO, 1).Value = "" 'ファイル名に_の使用があるが数字ではない場合
'          ElseIf Cont = 0 Then
'            GYO = GYO + 1 ' 行を加算
'            Buf = Split(strFilename, ".")
'            If (Buf(0) <> "") And (Not IsEmpty(Buf)) Then WS.Cells(GYO, 3).Value = Buf(0)
'            If (Buf(0) <> "") And (Not IsEmpty(Buf)) Then WS.Cells(GYO, 5).Value = Buf(UBound(Buf))
'            WS.Cells(GYO, 4).Value = FileDateTime(strPath & "\" & strFilename)
'          End If
'        ' 次のファイル名を取得
'        strFilename = Dir()
'    Loop
    WS.Columns("A:A").NumberFormatLocal = "0_ "
    WS.Columns("B:B").NumberFormatLocal = "@"
    WS.Columns("C:C").NumberFormatLocal = "@"
    WS.Cells.EntireColumn.AutoFit
    
    WS.Range("A1:E300").Sort Key1:=WS.Range("A1"), order1:=xlAscending

    WS.Columns("A:A").Delete Shift:=xlToLeft
    
End Sub
'-----------------<< End of Source >>-----------------
Public Sub UFOP()
UF.Show vbModeless
End Sub

'任意のﾜｰｸｼｰﾄの存在ﾁｪｯｸ
Public Function WsCheck(ByRef WsName As String) As Boolean
Dim WS As Worksheet 'ﾜｰｸｼｰﾄ
WsCheck = False
For Each WS In ThisWorkbook.Worksheets
  If WS.Name = WsName Then
    WsCheck = True
    Exit For
  End If
Next WS
Set WS = Nothing
End Function
'指定の名前のワークシートを追加
Sub AddWS(ByRef WsName As String)
Application.DisplayAlerts = False
Dim WS As Worksheet 'ﾜｰｸｼｰﾄ
For Each WS In ThisWorkbook.Worksheets
  If WS.Name = WsName Then
    Worksheets(WsName).Delete
    Exit For
  End If
Next WS
ThisWorkbook.Worksheets.Add(before:=Worksheets(1)).Name = WsName '右端に追加
Set WS = Nothing 'ｵﾌﾞｼﾞｪｸﾄの解放
Application.DisplayAlerts = True
End Sub

'PDFファイルを作成する ｼｰﾄの印刷範囲設定が反映される
Public Sub PDFCREATE(PDFFileName As String, sh1 As Worksheet, Fname As String) 'パス,保存シート,保存ファイル名
Dim fileName As String '保存先フォルダパス＆ファイル名
fileName = PDFFileName & "\" & Fname & ".pdf"
sh1.ExportAsFixedFormat Type:=xlTypePDF, fileName:=fileName, Quality:=xlQualityStandard, From:=1, To:=1
'MsgBox ThisWorkbook.Path & vbCrLf & "PDFファイルに保存しました。", vbInformation
End Sub
'
'Dim f As String: f = SaveDateLocate(KouPath, Ln)   'ﾊﾟｽ,ﾌｧｲﾙﾗｲﾝ名_必要ﾌｫﾙﾀﾞ生成とﾌｧｲﾙﾊﾟｽ
'Call PDFCREATE(f, SaveSh, SaveSh.Cells(2, 3)) 'ﾊﾟｽ,保存ｼｰﾄ,保存ﾌｧｲﾙ名




