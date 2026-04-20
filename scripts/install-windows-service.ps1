param(
  [string]$AppDir = (Get-Location).Path,
  [string]$ServiceName = "OfficeDocsToMdSync"
)

$exe = Join-Path $AppDir "dist\\office-docs-to-md-sync\\office-docs-to-md-sync.exe"
$binPath = "`"$exe`""

New-Service -Name $ServiceName -BinaryPathName $binPath -DisplayName $ServiceName -StartupType Automatic
Start-Service -Name $ServiceName
Write-Host "Installed $ServiceName"
