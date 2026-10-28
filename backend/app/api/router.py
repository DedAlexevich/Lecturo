from fastapi import APIRouter

from app.api import (
    admin,
    admin_backups,
    admin_logs,
    auth,
    billing,
    courses,
    exam,
    exam_exports,
    exports,
    health,
    lecture_chat,
    lectures,
    legal,
    local_results,
    maintenance,
    me,
    public_copy,
    public_exports,
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
    exam_exports,
    lectures,
    lecture_chat,
    uploads,
    exports,
    search,
    shares,
    public_copy,
    public_exports,
    billing,
    legal,
    local_results,
    admin,
    admin_logs,
    admin_backups,
    maintenance,
):
    api_router.include_router(module.router)
