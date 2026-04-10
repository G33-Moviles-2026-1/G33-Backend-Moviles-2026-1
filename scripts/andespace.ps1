# 1. Move to the project directory
Set-Location -Path "C:\Users\mateo\Documents\Repositories\G33-Backend-Moviles-2026-1"

# 2. Check if Docker is running; if not, start it
if (!(Get-Process "Docker Desktop" -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not running. Launching Docker Desktop..." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    
    # Wait for Docker to fully initialize
    Write-Host "Waiting for Docker Engine to start..." -ForegroundColor Gray
    while (!(docker info -f '{{.ServerVersion}}' 2>$null)) {
        Start-Sleep -Seconds 2
    }
    Write-Host "Docker is up and running!" -ForegroundColor Cyan
}

# 3. Start Docker containers
Write-Host "Starting Docker containers..." -ForegroundColor Cyan
docker-compose up -d

# 4. Improved Uvicorn Execution
Write-Host "Starting Uvicorn server..." -ForegroundColor Green

# Ensure no old Python processes are hanging
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Run uvicorn
. .\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --log-level debug