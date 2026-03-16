from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.health import router as health_router
from app.api.routes import auth
from app.api.routes.ingest import router as ingest_router
from app.api.routes.rooms import router as rooms_router
from app.api.routes.bookings import router as bookings_router
from app.api.routes.analytics import router as analytics_router

app = FastAPI(title="AndeSpace Backend")

app.add_middleware(
    SessionMiddleware,
    secret_key="una_clave_muy_secreta_y_larga_12345",
    session_cookie="session",
    max_age=1296000,
    same_site="lax",
    https_only=False,
)

app.include_router(health_router, tags=["health"])
app.include_router(auth.router)
app.include_router(ingest_router)
app.include_router(rooms_router)
app.include_router(bookings_router)
app.include_router(analytics_router)