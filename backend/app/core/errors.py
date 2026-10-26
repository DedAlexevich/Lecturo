from typing import NoReturn

from fastapi import HTTPException, status


def not_ready() -> NoReturn:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Ещё не готово")
