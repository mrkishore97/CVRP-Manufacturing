"""Configuration safety tests."""

from backend.app.config import Settings


def test_default_settings_do_not_require_google_key() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.google_maps_api_key is None
    assert settings.backend_host == "127.0.0.1"
    assert settings.backend_port == 8000
    assert settings.plant_timezone == "America/Toronto"


def test_secret_is_excluded_from_settings_representation() -> None:
    settings = Settings(  # type: ignore[call-arg]
        google_maps_api_key="not-a-real-key",
        _env_file=None,
    )

    assert "not-a-real-key" not in repr(settings)
