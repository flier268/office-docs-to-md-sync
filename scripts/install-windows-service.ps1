param(
  [string]$AppDir = (Get-Location).Path,
  [string]$ServiceName = "OfficeDocsToMdSync"
)

$python = Join-Path $AppDir ".venv\\Scripts\\python.exe"
$script = "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8080)"
$binPath = "`"$python`" -c `"$script`""

New-Service -Name $ServiceName -BinaryPathName $binPath -DisplayName $ServiceName -StartupType Automatic
Start-Service -Name $ServiceName
Write-Host "Installed $ServiceName"
