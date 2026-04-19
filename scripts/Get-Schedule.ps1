$baseUrl = "http://localhost:8000"

Write-Host "Authenticating with backend..." -ForegroundColor Yellow
$loginBody = @{ email = "@uniandes.edu.co"; password = "123" } | ConvertTo-Json

try {
    Invoke-RestMethod -Uri "$baseUrl/login/" -Method Post -Body $loginBody -ContentType "application/json" -SessionVariable mySession | Out-Null
    Write-Host "Login Successful! Session cookie saved.`n" -ForegroundColor Green
} catch {
    Write-Host "Login Failed! Please check if the backend is running." -ForegroundColor Red
    Write-Host $_.Exception.Message
    exit
}

while ($true) {
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan
    # FIXED THE PROMPT TO MATCH YOUR BACKEND:
    $rawInput = Read-Host "Enter a date (DD-MM-YYYY), press Enter for CURRENT week, or type 'exit' to quit"
    
    $cleanInput = $rawInput.Trim()

    if ($cleanInput.ToLower() -eq 'exit' -or $cleanInput.ToLower() -eq 'q') {
        Write-Host "Closing schedule fetcher. Goodbye!" -ForegroundColor Green
        break
    }

    if ([string]::IsNullOrEmpty($cleanInput)) {
        $targetUrl = "$baseUrl/schedule/week"
        Write-Host "Fetching schedule for the CURRENT week..." -ForegroundColor Yellow
    } else {
        $targetUrl = "$baseUrl/schedule/week?date=$cleanInput"
        Write-Host "Fetching schedule for: $cleanInput..." -ForegroundColor Yellow
    }

    try {
        $scheduleResponse = Invoke-RestMethod -Uri $targetUrl -Method Get -WebSession $mySession
        $scheduleResponse | ConvertTo-Json -Depth 10
    } catch {
        Write-Host "`n[ERROR] Could not fetch schedule!" -ForegroundColor Red
        Write-Host $_.Exception.Message
    }
    
    Write-Host "`n"
}