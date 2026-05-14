from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.health import router as health_router
from app.api.routes import auth
from app.api.routes.ingest import router as ingest_router
from app.api.routes.rooms import router as rooms_router
from app.api.routes.bookings import router as bookings_router
from app.api.routes.favorites import router as favorites_router
from app.api.routes.friendships import router as friendships_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.schedule import router as schedule_router
from app.api.routes.navigation import router as navigation_router
from app.api.routes.recommendations import router as recommendations_router
from app.api.routes.notifications import router as notifications_router

app = FastAPI(title="AndeSpace Backend")

app.add_middleware(
    SessionMiddleware,
    secret_key="una_clave_muy_secreta_y_larga_12345",
    session_cookie="session",
    max_age=60*60*5,
    same_site="lax",
    https_only=False,
)

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    print(f"❌ ERROR {exc.status_code} en {request.url.path}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

app.include_router(health_router, tags=["health"])
app.include_router(recommendations_router)
app.include_router(auth.router)
app.include_router(ingest_router)
app.include_router(rooms_router)
app.include_router(bookings_router)
app.include_router(favorites_router)
app.include_router(friendships_router)
app.include_router(analytics_router)
app.include_router(schedule_router)
app.include_router(navigation_router)
app.include_router(notifications_router)