VERSION 5.00
Begin {C62A69F0-16DC-11CE-9E98-00AA00574A4F} UF 
   ClientHeight    =   6870
   ClientLeft      =   120
   ClientTop       =   465
   ClientWidth     =   7650
   OleObjectBlob   =   "UF.frx":0000
   StartUpPosition =   1  'オーナー フォームの中央
End
Attribute VB_Name = "UF"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Private Sub CommandButton1_Click()
Application.ScreenUpdating = False
Call Get_FileName
Application.ScreenUpdating = True
End Sub

Private Sub CommandButton2_Click()
If Me.T1.Text = "" Then Exit Sub
Dim WsName As String: WsName = Me.T1.Text
Dim SaveSh As Worksheet: Set SaveSh = ThisWorkbook.Sheets(WsName)
Dim f As String: f = ThisWorkbook.Path
Call PDFCREATE(f, SaveSh, WsName) 'ﾊﾟｽ,保存ｼｰﾄ,保存ﾌｧｲﾙ名
End Sub

Private Sub CommandButton3_Click()

'DebugSpecificFilesDetailed

'Debug.Print "T2の内容: [" & Me.T2.Text & "]"
'Debug.Print "ThisWorkbook.Path: [" & ThisWorkbook.Path & "]"
'
'Dim fso As Object
'Set fso = CreateObject("Scripting.FileSystemObject")
'Debug.Print "T2のフォルダ存在確認: " & fso.FolderExists(Me.T2.Text)
'Debug.Print "ThisWorkbookのフォルダ存在確認: " & fso.FolderExists(ThisWorkbook.Path)


'C:\Users\xfa-ngyinazawa\Desktop\ファイル名一覧取得  直接実際のパスを入力してください
Call ExecuteRenameBasicErrorHandling

'' フォルダ内のファイルを一括リネーム
'RenameFilesZenkakuToHankaku "C:\MyFolder", False
'' サブフォルダも含めて一括リネーム
'RenameFilesZenkakuToHankaku "C:\MyFolder", True
'' 単一ファイルのリネーム
'RenameSingleFileZenkakuToHankaku "C:\MyFolder\テストファイル.txt"
End Sub
