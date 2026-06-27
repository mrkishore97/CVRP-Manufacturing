$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project environment not found. Follow the Local setup steps in README.md first."
}

$backendArguments = @(
    "-m",
    "uvicorn",
    "backend.app.api.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8000"
)

$backend = Start-Process `
    -FilePath $python `
    -ArgumentList $backendArguments `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

try {
    & $python -m streamlit run frontend/streamlit_app.py `
        --server.address 127.0.0.1 `
        --server.port 8501
}
finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force
    }
}

