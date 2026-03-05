from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from app.api.routes.health import router as health_router
from app.api.routes import auth

app = FastAPI(title="AndeSpace Backend")

app.add_middleware(
    SessionMiddleware, 
    secret_key="una_clave_muy_secreta_y_larga_12345",
    session_cookie="session", 
    max_age=1296000,      
    same_site="lax",         
    https_only=False        
)

app.include_router(health_router, tags=["health"])
app.include_router(auth.router)