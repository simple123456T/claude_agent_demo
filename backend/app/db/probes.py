from pymilvus import MilvusClient
from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine


def probe_postgres() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


def probe_redis() -> None:
    settings = get_settings()
    client = Redis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=settings.redis_connect_timeout,
        socket_timeout=settings.redis_connect_timeout,
        decode_responses=True,
    )
    try:
        if not client.ping():
            raise ConnectionError("Redis PING returned false")
    finally:
        client.close()


def probe_milvus() -> None:
    settings = get_settings()
    token = settings.milvus_token.get_secret_value() if settings.milvus_token else ""
    client = MilvusClient(
        uri=settings.milvus_uri,
        token=token,
        timeout=settings.milvus_connect_timeout,
    )
    try:
        client.list_collections(timeout=settings.milvus_connect_timeout)
    finally:
        client.close()
