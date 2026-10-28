import argparse
import asyncio
import sys

from fastapi import HTTPException

from app.core.db import SessionLocal, engine
from app.services.admin import USER_NOT_FOUND, find_user, grant_admin, user_label


async def make_admin(identifier: str) -> int:
    try:
        async with SessionLocal() as session:
            user = await find_user(session, identifier)
            if user is None:
                print(f"{USER_NOT_FOUND}: {identifier}", file=sys.stderr)
                return 1
            try:
                await grant_admin(session, None, user, "cli")
            except HTTPException as error:
                print(f"{user_label(user)}: {error.detail}", file=sys.stderr)
                return 1
            print(f"{user_label(user)} теперь администратор")
            return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    make_admin_parser = commands.add_parser(
        "make-admin", help="выдать права администратора по почте или Telegram id"
    )
    make_admin_parser.add_argument("identifier", help="почта или числовой Telegram id")
    args = parser.parse_args(argv)
    return asyncio.run(make_admin(args.identifier))


if __name__ == "__main__":
    sys.exit(main())
