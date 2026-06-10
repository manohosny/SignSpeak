import warnings

import pytest

from app.core.config import Settings


def _make_settings(**overrides):
    base = {
        "PROJECT_NAME": "SignSpeak",
        "POSTGRES_SERVER": "localhost",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
        "POSTGRES_DB": "signspeak",
        "FIRST_SUPERUSER": "admin@example.com",
        "FIRST_SUPERUSER_PASSWORD": "supersecret",
        "SECRET_KEY": "supersecret",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@pytest.mark.parametrize("env", ["staging", "production"])
def test_default_secret_key_rejected_outside_local(env: str) -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        _make_settings(ENVIRONMENT=env, SECRET_KEY="changethis")


@pytest.mark.parametrize("env", ["staging", "production"])
def test_default_first_superuser_password_rejected_outside_local(env: str) -> None:
    with pytest.raises(ValueError, match="FIRST_SUPERUSER_PASSWORD"):
        _make_settings(ENVIRONMENT=env, FIRST_SUPERUSER_PASSWORD="changethis")


def test_default_secret_key_warns_in_local() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _make_settings(ENVIRONMENT="local", SECRET_KEY="changethis")
    assert any("SECRET_KEY" in str(w.message) for w in caught)


def test_real_secret_passes_in_production() -> None:
    settings = _make_settings(ENVIRONMENT="production", SECRET_KEY="z" * 64)
    assert settings.ENVIRONMENT == "production"


def test_rest_pose_segmentation_defaults():
    from app.core.config import settings
    assert settings.SIGN_TO_TEXT_REST_DROP_MARGIN == 0.15
    assert settings.SIGN_TO_TEXT_REST_HAND_CONF == 0.3
    assert settings.SIGN_TO_TEXT_REST_DEBOUNCE_MS == 250
    assert settings.SIGN_TO_TEXT_MIN_FRAMES == 18
    # Motion-pause segmentation (sign ends on a still pause, hands kept in frame).
    assert settings.SIGN_TO_TEXT_PAUSE_MS == 500
    assert settings.SIGN_TO_TEXT_MOTION_THRESHOLD == 0.012
