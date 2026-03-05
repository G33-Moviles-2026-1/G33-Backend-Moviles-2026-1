from fastapi import FastAPI
from app.api.routes.health import router as health_router

app = FastAPI(title="AndeSpace Backend")

app.include_router(health_router, tags=["health"])
# TODO: include other routers as the team implements them