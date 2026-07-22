import os
import pytest
from unittest.mock import AsyncMock, patch

from discord_client import DiscordError

VALID_URL = "https://discord.com/channels/111/222/333"

SAMPLE_RESULT = {
    "messages": [
        {
            "id": "333",
            "author": "Alice",
            "timestamp": "2024-01-15T10:00:00+00:00",
            "content": "Hello",
            "is_anchor": True,
        }
    ],
    "has_more": False,
    "last_id": "333",
}


def make_mock_client(return_value=None, side_effect=None):
    """Return a mock that behaves as `async with DiscordClient(token) as client:`."""
    instance = AsyncMock()
    if side_effect is not None:
        instance.read_thread.side_effect = side_effect
    else:
        instance.read_thread.return_value = return_value or SAMPLE_RESULT
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=False)
    return instance


@pytest.fixture(autouse=True)
def token_env():
    with patch.dict(os.environ, {"DISCORD_USER_TOKEN": "test-token"}):
        yield


# Import here so that a missing server.py causes collection to fail
# (proving the test is a genuine failing test before implementation).
from server import read_discord_thread  # noqa: E402


class TestReadDiscordThread:
    async def test_returns_result_from_discord_client(self):
        mock = make_mock_client(return_value=SAMPLE_RESULT)
        with patch("server.DiscordClient", return_value=mock):
            result = await read_discord_thread(VALID_URL)
        assert result == SAMPLE_RESULT

    async def test_passes_message_url(self):
        mock = make_mock_client()
        with patch("server.DiscordClient", return_value=mock):
            await read_discord_thread(VALID_URL)
        mock.read_thread.assert_called_once_with(VALID_URL, after_id=None, batch_size=50)

    async def test_passes_after_id_and_batch_size(self):
        mock = make_mock_client()
        with patch("server.DiscordClient", return_value=mock):
            await read_discord_thread(VALID_URL, after_id="400", batch_size=25)
        mock.read_thread.assert_called_once_with(VALID_URL, after_id="400", batch_size=25)

    async def test_discord_error_propagates(self):
        mock = make_mock_client(side_effect=DiscordError("not_found", "Not found"))
        with patch("server.DiscordClient", return_value=mock):
            with pytest.raises(DiscordError) as exc_info:
                await read_discord_thread(VALID_URL)
        assert exc_info.value.code == "not_found"

    async def test_uses_token_from_environment(self):
        mock = make_mock_client()
        with patch.dict(os.environ, {"DISCORD_USER_TOKEN": "my-secret-token"}):
            with patch("server.DiscordClient", return_value=mock) as MockClass:
                await read_discord_thread(VALID_URL)
            MockClass.assert_called_once_with("my-secret-token")

    async def test_raises_when_token_missing(self):
        env_without_token = {k: v for k, v in os.environ.items() if k != "DISCORD_USER_TOKEN"}
        with patch.dict(os.environ, env_without_token, clear=True):
            with pytest.raises(Exception):
                await read_discord_thread(VALID_URL)
