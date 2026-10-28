from redis.asyncio import Redis

clients: dict[str, Redis] = {}


def get_redis(url: str) -> Redis:
    client = clients.get(url)
    if client is None:
        client = clients[url] = Redis.from_url(url)
    return client


async def close_redis() -> None:
    opened = list(clients.values())
    clients.clear()
    for client in opened:
        await client.aclose()
