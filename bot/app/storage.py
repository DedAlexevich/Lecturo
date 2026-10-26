import asyncpg

SAVE_CHAT_ID = """
UPDATE users SET telegram_chat_id = $1
WHERE id IN (
    SELECT user_id FROM auth_identities
    WHERE provider = 'telegram' AND provider_user_id = $2
)
"""


async def save_chat_id(pool: asyncpg.Pool, telegram_id: int, chat_id: int) -> bool:
    status = await pool.execute(SAVE_CHAT_ID, chat_id, str(telegram_id))
    return status != "UPDATE 0"
