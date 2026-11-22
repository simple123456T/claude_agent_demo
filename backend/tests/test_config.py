from app.core.config import Settings


def _settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql://localhost/db",
        "redis_url": "redis://localhost/0",
        **overrides,
    }
    return Settings(_env_file=None, **values)


def test_secret_connection_strings_are_masked_in_repr():
    settings = _settings(
        database_url="postgresql://user:secret-password@localhost/db",
        redis_url="redis://:secret-password@localhost/0",
    )

    assert "secret-password" not in repr(settings)
    assert settings.sqlalchemy_database_url.startswith("postgresql+psycopg://")


def test_model_is_not_configured_by_default():
    assert not _settings().model_configured


def test_blank_optional_values_are_treated_as_unset():
    settings = _settings(oidc_issuer="", oidc_client_id="  ", model_base_url="")

    assert settings.oidc_issuer is None
    assert not settings.oidc_configured
    assert not settings.model_configured


def test_oidc_audience_falls_back_to_client_id():
    settings = _settings(oidc_issuer="https://sso.internal/realms/x", oidc_client_id="datagent")

    assert settings.oidc_configured
    assert settings.effective_oidc_audience == "datagent"


def test_bootstrap_admin_subjects_are_parsed():
    settings = _settings(oidc_bootstrap_admin_subjects=" alice , ,bob ")

    assert settings.bootstrap_admin_subjects == frozenset({"alice", "bob"})


def test_control_plane_schema_must_be_a_safe_identifier():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _settings(control_plane_schema='datagent"; DROP SCHEMA public; --')
