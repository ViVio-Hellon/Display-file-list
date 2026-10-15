Attribute VB_Name = "ExportForCompare"
Option Explicit
'*********************************************************
'  照合用: シート「一覧」を UTF-8 の CSV にして、ブックと同じフォルダへ書き出す
'  (Python 版 scripts/compare_with_vba.py が読む)
'
'  使い方: VBE の「ファイルのインポート」でこのファイルを取り込み、
'          「一覧取得」を押したあとで ExportListToCsv を実行する
'  一覧の中身は変えません。書き出すのは 一覧_照合用.csv だけです。
'*********************************************************
Public Sub ExportListToCsv()
    Dim ws As Worksheet: Set ws = ThisWorkbook.Sheets("一覧")
    Dim lastR As Long
    lastR = ws.UsedRange.Row + ws.UsedRange.Rows.Count - 1

    Dim st As Object: Set st = CreateObject("ADODB.Stream")
    st.Type = 2
    st.Charset = "UTF-8"
    st.Open
    st.WriteText "行,文書番号,名称,更新日時,拡張子" & vbCrLf

    Dim r As Long, d As String, v As Variant
    For r = 1 To lastR
        v = ws.Cells(r, 3).Value
        If IsEmpty(v) Then
            d = ""
        ElseIf IsDate(v) Then
            d = Format(v, "yyyy/mm/dd hh:nn:ss")
        Else
            d = CStr(v)
        End If
        st.WriteText r & "," & Q(ws.Cells(r, 1).Value) & "," & Q(ws.Cells(r, 2).Value) & "," & _
                     Q(d) & "," & Q(ws.Cells(r, 4).Value) & vbCrLf
    Next r

    Dim f As String: f = ThisWorkbook.Path & "\一覧_照合用.csv"
    st.SaveToFile f, 2   ' adSaveCreateOverWrite
    st.Close
    MsgBox "書き出しました: " & f, vbInformation
End Sub

Private Function Q(ByVal v As Variant) As String
    Q = """" & Replace(CStr(v), """", """""") & """"
End Function
