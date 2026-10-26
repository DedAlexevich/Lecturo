from fastapi import APIRouter

from app.api import (
    auth,
    billing,
    courses,
    exports,
    health,
    lectures,
    legal,
    local_results,
    search,
    shares,
    telegram,
    uploads,
)

api_router = APIRouter(prefix="/api/v1")

for module in (
    health,
    auth,
    telegram,
    courses,
    lectures,
    uploads,
    exports,
    search,
    shares,
    billing,
    legal,
    local_results,
):
    api_router.include_router(module.router)
