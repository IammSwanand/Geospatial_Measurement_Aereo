from fastapi import APIRouter
from app.api.endpoints import files, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(files.router)
