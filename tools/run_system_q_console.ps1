$env:PYGAME_HIDE_SUPPORT_PROMPT = "1"
$env:PYTHONWARNINGS = "ignore"
Start-Process -FilePath "py" -ArgumentList @("-3", "Development\software\system_q_console.py") -WorkingDirectory "C:\Users\racin\Desktop\recording-environment"
