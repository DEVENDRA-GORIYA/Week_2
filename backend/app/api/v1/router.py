from fastapi import APIRouter

from app.api.v1 import auth, health, inference, prompts, usage

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(inference.router, tags=["inference"])
api_router.include_router(prompts.router, prefix="/prompts", tags=["prompts"])
api_router.include_router(usage.router, prefix="/usage", tags=["usage"])
