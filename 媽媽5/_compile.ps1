$ErrorActionPreference = "Continue"
Set-Location "D:\采购管理\媽媽5\phone_proxy_app\native"
$output = & .\gradlew.bat assembleDebug --no-daemon 2>&1
$output | Out-File -FilePath "D:\采购管理\媽媽5\_compile_output.txt" -Encoding UTF8
Write-Output "DONE"
