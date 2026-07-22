import pytest
import respx
import httpx
from unittest.mock import patch, AsyncMock

from discord_client import DiscordClient, DiscordError, parse_message_url

VALID_URL = "https://discord.com/channels/111/222/333"
TOKEN = "test-token"

BASE = "https://discord.com/api/v10"


# --- helpers ---

def make_msg(id, content="Hello", global_name="Alice", username="alice123"):
    return {
        "id": id,
        "author": {"global_name": global_name, "username": username},
        "timestamp": "2024-01-15T10:00:00+00:00",
        "content": content,
    }


def mock_anchor(msg, status=200):
    """Register the around-endpoint mock for anchor fetch. Must be called before mock_batch."""
    return respx.get(f"{BASE}/channels/222/messages", params={"around": "333"}).mock(
        return_value=httpx.Response(status, json=[msg] if status == 200 else {})
    )


def mock_batch(msgs, status=200, after="333", limit=50):
    """Register the after-endpoint mock for batch fetch."""
    return respx.get(f"{BASE}/channels/222/messages", params={"after": after, "limit": limit}).mock(
        return_value=httpx.Response(status, json=msgs if status == 200 else {})
    )


# --- URL parsing ---

class TestParseMessageUrl:
    def test_valid_url_returns_ids(self):
        server_id, channel_id, message_id = parse_message_url(VALID_URL)
        assert server_id == "111"
        assert channel_id == "222"
        assert message_id == "333"

    def test_invalid_url_raises_discord_error(self):
        with pytest.raises(DiscordError) as exc_info:
            parse_message_url("https://not-discord.com/link")
        assert exc_info.value.code == "invalid_url"

    def test_non_message_path_raises_discord_error(self):
        with pytest.raises(DiscordError) as exc_info:
            parse_message_url("https://discord.com/channels/111/222")
        assert exc_info.value.code == "invalid_url"

    def test_ptb_url_works(self):
        url = "https://ptb.discord.com/channels/111/222/333"
        server_id, channel_id, message_id = parse_message_url(url)
        assert server_id == "111"
        assert channel_id == "222"
        assert message_id == "333"


# --- anchor fetch ---

class TestAnchorFetch:
    @respx.mock
    async def test_fetches_anchor_via_around_endpoint(self):
        mock_anchor(make_msg("333"))
        mock_batch([])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL)

        assert result["messages"][0]["id"] == "333"
        assert result["messages"][0]["is_anchor"] is True

    @respx.mock
    async def test_uses_global_name(self):
        mock_anchor(make_msg("333", global_name="Alice"))
        mock_batch([])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL)

        assert result["messages"][0]["author"] == "Alice"

    @respx.mock
    async def test_falls_back_to_username_when_global_name_none(self):
        mock_anchor(make_msg("333", global_name=None, username="bob456"))
        mock_batch([])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL)

        assert result["messages"][0]["author"] == "bob456"

    @respx.mock
    async def test_skips_empty_anchor_content(self):
        mock_anchor(make_msg("333", content=""))
        mock_batch([make_msg("334")])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL)

        assert all(m["id"] != "333" for m in result["messages"])


# --- pagination ---

class TestPagination:
    @respx.mock
    async def test_first_call_returns_anchor_plus_batch(self):
        mock_anchor(make_msg("333"))
        mock_batch([make_msg("335"), make_msg("334")])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL)

        ids = [m["id"] for m in result["messages"]]
        assert ids == ["333", "334", "335"]

    @respx.mock
    async def test_has_more_true_when_batch_equals_batch_size(self):
        batch = [make_msg(str(i)) for i in range(10)]
        mock_anchor(make_msg("333"))
        mock_batch(batch, limit=10)

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL, batch_size=10)

        assert result["has_more"] is True

    @respx.mock
    async def test_has_more_false_when_batch_smaller_than_batch_size(self):
        mock_anchor(make_msg("333"))
        mock_batch([make_msg("334")])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL, batch_size=50)

        assert result["has_more"] is False

    @respx.mock
    async def test_after_id_skips_anchor_fetch(self):
        anchor_route = mock_anchor(make_msg("333"))
        mock_batch([make_msg("444")], after="400")

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL, after_id="400")

        assert not anchor_route.called
        assert result["messages"][0]["id"] == "444"

    @respx.mock
    async def test_after_id_messages_are_not_marked_anchor(self):
        mock_batch([make_msg("444")], after="400")

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL, after_id="400")

        assert result["messages"][0]["is_anchor"] is False

    @respx.mock
    async def test_last_id_is_last_message_in_raw_batch(self):
        mock_anchor(make_msg("333"))
        mock_batch([make_msg("335"), make_msg("334")])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL)

        assert result["last_id"] == "335"

    @respx.mock
    async def test_last_id_is_anchor_when_no_batch(self):
        mock_anchor(make_msg("333"))
        mock_batch([])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL)

        assert result["last_id"] == "333"

    @respx.mock
    async def test_last_id_is_after_id_when_batch_empty(self):
        mock_batch([], after="900")

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL, after_id="900")

        assert result["last_id"] == "900"


# --- content filtering ---

class TestContentFiltering:
    @respx.mock
    async def test_skips_empty_content_in_batch(self):
        mock_anchor(make_msg("333"))
        mock_batch([
            make_msg("335", content="Real message"),
            make_msg("334", content=""),   # system/embed — skip
        ])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL)

        ids = [m["id"] for m in result["messages"]]
        assert "334" not in ids
        assert "335" in ids


# --- error handling ---

class TestErrorHandling:
    @respx.mock
    async def test_401_raises_unauthorized(self):
        respx.get(f"{BASE}/channels/222/messages").mock(return_value=httpx.Response(401))

        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL)

        assert exc_info.value.code == "unauthorized"

    @respx.mock
    async def test_403_raises_forbidden(self):
        respx.get(f"{BASE}/channels/222/messages").mock(return_value=httpx.Response(403, json={}))

        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL)

        assert exc_info.value.code == "forbidden"

    @respx.mock
    async def test_404_raises_not_found(self):
        respx.get(f"{BASE}/channels/222/messages").mock(return_value=httpx.Response(404, json={}))

        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL)

        assert exc_info.value.code == "not_found"

    @respx.mock
    async def test_429_raises_rate_limited(self):
        # retry_after above _RETRY_CAP so no sleep/retry occurs
        respx.get(f"{BASE}/channels/222/messages").mock(
            return_value=httpx.Response(429, json={"retry_after": 60.0, "global": False})
        )

        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL)

        assert exc_info.value.code == "rate_limited"
        assert exc_info.value.retry_after == 60.0

    @respx.mock
    async def test_429_retries_and_succeeds(self):
        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, json={"retry_after": 0.5, "global": False})
            return httpx.Response(200, json=[make_msg("333")])

        respx.get(f"{BASE}/channels/222/messages").mock(side_effect=side_effect)

        with patch("discord_client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            async with DiscordClient(TOKEN) as client:
                # only anchor fetch; batch fetch is mocked separately below
                anchor_raw = await client._fetch_message("222", "333")

        assert anchor_raw["id"] == "333"
        mock_sleep.assert_awaited_once_with(0.5)

    @respx.mock
    async def test_429_above_cap_raises_immediately_without_retry(self):
        respx.get(f"{BASE}/channels/222/messages").mock(
            return_value=httpx.Response(429, json={"retry_after": 6.0, "global": False})
        )

        with patch("discord_client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            async with DiscordClient(TOKEN) as client:
                with pytest.raises(DiscordError) as exc_info:
                    await client._fetch_message("222", "333")

        assert exc_info.value.code == "rate_limited"
        assert exc_info.value.retry_after == 6.0
        mock_sleep.assert_not_awaited()

    @respx.mock
    async def test_requests_include_browser_user_agent(self):
        captured = []

        def capture(request):
            captured.append(request.headers.get("user-agent", ""))
            return httpx.Response(200, json=[make_msg("333")])

        respx.get(f"{BASE}/channels/222/messages").mock(side_effect=capture)

        async with DiscordClient(TOKEN) as client:
            await client._fetch_message("222", "333")

        assert captured, "no request was made"
        assert captured[0].startswith("Mozilla/"), f"unexpected User-Agent: {captured[0]!r}"

    def test_invalid_url_raises_before_any_network_call(self):
        with pytest.raises(DiscordError) as exc_info:
            parse_message_url("not-a-url-at-all")
        assert exc_info.value.code == "invalid_url"

    async def test_batch_size_zero_raises(self):
        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL, batch_size=0)
        assert exc_info.value.code == "invalid_batch_size"

    async def test_batch_size_over_100_raises(self):
        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL, batch_size=101)
        assert exc_info.value.code == "invalid_batch_size"

    async def test_non_numeric_after_id_raises(self):
        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL, after_id="not-a-snowflake")
        assert exc_info.value.code == "invalid_after_id"

    async def test_unicode_digits_in_after_id_raise(self):
        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL, after_id="²³⁴")
        assert exc_info.value.code == "invalid_after_id"
