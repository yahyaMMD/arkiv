$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

python -m pip install --upgrade pip
python -m pip install -r requirements-windows.txt
python -m PyInstaller --noconfirm --clean arkiv.spec

$dist = Join-Path (Get-Location) "dist\Arkiv"
$readme = @"
Arkiv for Windows
=================

1. Keep this whole Arkiv folder together.
2. Double-click Arkiv.exe
3. In Settings, paste your OpenRouter API key
4. Choose the folder Arkiv should organize

Requirements:
- Windows 10 or Windows 11 (64-bit)
- Microsoft Edge WebView2 (usually already installed)

If Windows blocks the app the first time:
- Click More info → Run anyway
"@
Set-Content -Path (Join-Path $dist "README.txt") -Value $readme -Encoding UTF8

$zipPath = Join-Path (Get-Location) "dist\Arkiv-Windows.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $dist -DestinationPath $zipPath -Force
Write-Host "Built: $zipPath"
