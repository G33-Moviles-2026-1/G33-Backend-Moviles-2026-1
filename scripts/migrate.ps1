$migrationsDir = "$PSScriptRoot\migrations"

Write-Host "Running all migrations in $migrationsDir..."

Get-ChildItem "$migrationsDir\*.sql" | Sort-Object Name | ForEach-Object {
    Write-Host "  -> $($_.Name)"
    Get-Content $_.FullName | docker compose exec -T db psql -U andespace -d andespace
}

Write-Host "Done."
