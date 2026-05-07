$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$env:PYGAME_HIDE_SUPPORT_PROMPT = "1"
$env:PYTHONWARNINGS = "ignore:pkg_resources is deprecated as an API"

$pythonw = "C:\Users\racin\AppData\Local\Programs\Python\Python313\pythonw.exe"

if (Test-Path $pythonw) {
    Start-Process -FilePath $pythonw -ArgumentList "..\Development\software\pol_visualizer.py" -WorkingDirectory $repoRoot
}
else {
    Start-Process -FilePath "py" -ArgumentList "-3", "..\Development\software\pol_visualizer.py" -WorkingDirectory $repoRoot
}
