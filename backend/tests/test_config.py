from app.core.config import Settings


def test_secret_connection_strings_are_masked_in_repr():
    settings = Settings(
        database_url="postgresql://user:secret-password@localhost/db",
        redis_url="redis://:secret-password@localhost/0",
    )

    assert "secret-password" not in repr(settings)
    assert settings.sqlalchemy_database_url.startswith("postgresql+psycopg://")


def test_model_is_not_configured_by_default():
    settings = Settings(
        database_url="postgresql://localhost/db",
        redis_url="redis://localhost/0",
    )

    assert not settings.model_configured
