Set-Location $PSScriptRoot

if (Test-Path ".venv\Scripts\pythonw.exe") {
    $python = ".venv\Scripts\pythonw.exe"
} elseif (Test-Path ".venv\Scripts\python.exe") {
    $python = ".venv\Scripts\python.exe"
} else {
    $python = "pythonw"
}

Start-Process $python -ArgumentList "launch.py" -WindowStyle Hidden
