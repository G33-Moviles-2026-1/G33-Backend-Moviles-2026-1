# ==============================================================
#  test_api.ps1  -  Prueba de sesiones/cookies en FastAPI
# ==============================================================

$BASE_URL     = "http://localhost:8000"
$EMAIL        = "test_usuario@uniandes.edu.co"
$PASSWORD     = "password123"
$SEMESTRE     = "2025-10"
$SESSION_FILE = "$env:TEMP\fastapi_cookies.txt"

function Ok($m)   { Write-Host "[OK]   $m" -ForegroundColor Green  }
function Warn($m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Err($m)  { Write-Host "[ERR]  $m" -ForegroundColor Red    }
function Info($m) { Write-Host "[INFO] $m" -ForegroundColor Cyan   }
function Sep()    { Write-Host ("=" * 60) -ForegroundColor DarkGray }

function Show-Cookies($Label) {
    Info "Cookies guardadas ($Label):"
    if (Test-Path $SESSION_FILE) {
        $cookies = Get-Content $SESSION_FILE
        if ($cookies) {
            $cookies | ForEach-Object { Write-Host "  $_" -ForegroundColor Magenta }
        } else {
            Warn "  (archivo vacio)"
        }
    } else {
        Warn "  (no existe archivo de cookies todavia)"
    }
}

# ------------------------------------------------------------------
# 1. SIGNUP
# ------------------------------------------------------------------
Sep
Info "PASO 1 - POST /signup/ ($EMAIL)"

$body      = @{ email = $EMAIL; password = $PASSWORD; first_semester = $SEMESTRE } | ConvertTo-Json
$loginBody = @{ email = $EMAIL; password = $PASSWORD } | ConvertTo-Json

try {
    $resp = Invoke-WebRequest -Uri "$BASE_URL/signup/" -Method POST -ContentType "application/json" -Body $body -SessionVariable "webSession"
    Ok "Usuario creado - HTTP $($resp.StatusCode)"
    $resp.Content | ConvertFrom-Json | Format-List
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 400) {
        Warn "El usuario ya existia (400). Haciendo login para obtener sesion..."
        $resp = Invoke-WebRequest -Uri "$BASE_URL/login/" -Method POST -ContentType "application/json" -Body $loginBody -SessionVariable "webSession"
        Ok "Login inicial correcto - HTTP $($resp.StatusCode)"
    } else {
        Err "Error inesperado: $_"
        exit 1
    }
}

$webSession.Cookies.GetCookies($BASE_URL) | ForEach-Object { "$($_.Name) = $($_.Value)" } | Set-Content $SESSION_FILE
Show-Cookies "tras signup"

# ------------------------------------------------------------------
# 2. /me/ - debe tener sesion activa
# ------------------------------------------------------------------
Sep
Info "PASO 2 - GET /me/ (sesion post-signup)"

try {
    $resp = Invoke-WebRequest -Uri "$BASE_URL/me/" -Method GET -WebSession $webSession
    Ok "Sesion activa - HTTP $($resp.StatusCode)"
    $resp.Content | ConvertFrom-Json | Format-List
} catch {
    Err "Sin sesion activa: $($_.Exception.Response.StatusCode.value__)"
}

# ------------------------------------------------------------------
# 3. LOGOUT
# ------------------------------------------------------------------
Sep
Info "PASO 3 - POST /logout/"

try {
    $resp = Invoke-WebRequest -Uri "$BASE_URL/logout/" -Method POST -WebSession $webSession
    Ok "Logout correcto - HTTP $($resp.StatusCode)"
    $resp.Content | ConvertFrom-Json | Format-List
} catch {
    Err "Logout fallido: $($_.Exception.Response.StatusCode.value__)"
    exit 1
}

# ------------------------------------------------------------------
# 4. /me/ - debe dar 401 tras logout
# ------------------------------------------------------------------
Sep
Info "PASO 4 - GET /me/ (debe dar 401 tras logout)"

try {
    $resp = Invoke-WebRequest -Uri "$BASE_URL/me/" -Method GET -WebSession $webSession
    Warn "Inesperado: sesion sigue activa - HTTP $($resp.StatusCode)"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 401) {
        Ok "Correcto: sesion invalida tras logout (401)"
    } else {
        Err "Error inesperado: $code"
    }
}

# ------------------------------------------------------------------
# 5. LOGIN
# ------------------------------------------------------------------
Sep
Info "PASO 5 - POST /login/"

try {
    $resp = Invoke-WebRequest -Uri "$BASE_URL/login/" -Method POST -ContentType "application/json" -Body $loginBody -WebSession $webSession
    Ok "Login correcto - HTTP $($resp.StatusCode)"
    $resp.Content | ConvertFrom-Json | Format-List
} catch {
    Err "Login fallido: $($_.Exception.Response.StatusCode.value__)"
    exit 1
}

$webSession.Cookies.GetCookies($BASE_URL) | ForEach-Object { "$($_.Name) = $($_.Value)" } | Set-Content $SESSION_FILE
Show-Cookies "tras login"

# ------------------------------------------------------------------
# 6. /me/ - debe tener sesion activa de nuevo
# ------------------------------------------------------------------
Sep
Info "PASO 6 - GET /me/ (sesion post-login)"

try {
    $resp = Invoke-WebRequest -Uri "$BASE_URL/me/" -Method GET -WebSession $webSession
    Ok "Sesion activa - HTTP $($resp.StatusCode)"
    $resp.Content | ConvertFrom-Json | Format-List
} catch {
    Err "Sin sesion activa: $($_.Exception.Response.StatusCode.value__)"
}

Sep
Info "Fin del test. Cookies en: $SESSION_FILE"