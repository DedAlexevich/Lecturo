from fastapi import APIRouter

from app.api import (
    auth,
    billing,
    courses,
    exam,
    exports,
    health,
    lecture_chat,
    lectures,
    legal,
    local_results,
    me,
    search,
    shares,
    telegram,
    uploads,
)

api_router = APIRouter(prefix="/api/v1")

for module in (
    health,
    auth,
    me,
    telegram,
    courses,
    exam,
    lectures,
    lecture_chat,
    uploads,
    exports,
    search,
    shares,
    billing,
    legal,
    local_results,
):
    api_router.include_router(module.router)
