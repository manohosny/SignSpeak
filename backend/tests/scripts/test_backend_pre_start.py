from unittest.mock import AsyncMock, MagicMock, patch

from app.backend_pre_start import init, logger


async def test_init_successful_connection() -> None:
    # Build the mock chain: engine.connect() -> async ctx mgr -> conn.execute()
    conn_mock = AsyncMock()
    ctx_mgr = AsyncMock()
    ctx_mgr.__aenter__.return_value = conn_mock
    ctx_mgr.__aexit__.return_value = False

    engine_mock = MagicMock()
    engine_mock.connect.return_value = ctx_mgr

    with (
        patch.object(logger, "info"),
        patch.object(logger, "error"),
        patch.object(logger, "warn"),
    ):
        try:
            await init(engine_mock)
            connection_successful = True
        except Exception:
            connection_successful = False

        assert connection_successful, (
            "The database connection should be successful and not raise an exception."
        )

        conn_mock.execute.assert_called_once()
