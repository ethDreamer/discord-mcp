import pytest
import respx
import httpx

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


def mock_batch(msgs, status=200):
    """Register the after-endpoint mock for batch fetch."""
    return respx.get(f"{BASE}/channels/222/messages").mock(
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
        mock_batch([make_msg("334"), make_msg("335")])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL)

        ids = [m["id"] for m in result["messages"]]
        assert ids == ["333", "334", "335"]

    @respx.mock
    async def test_has_more_true_when_batch_equals_batch_size(self):
        batch = [make_msg(str(i)) for i in range(10)]
        mock_anchor(make_msg("333"))
        mock_batch(batch)

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
        mock_batch([make_msg("444")])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL, after_id="400")

        assert not anchor_route.called
        assert result["messages"][0]["id"] == "444"

    @respx.mock
    async def test_after_id_messages_are_not_marked_anchor(self):
        mock_batch([make_msg("444")])

        async with DiscordClient(TOKEN) as client:
            result = await client.read_thread(VALID_URL, after_id="400")

        assert result["messages"][0]["is_anchor"] is False

    @respx.mock
    async def test_last_id_is_last_message_in_raw_batch(self):
        mock_anchor(make_msg("333"))
        mock_batch([make_msg("334"), make_msg("335")])

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


# --- content filtering ---

class TestContentFiltering:
    @respx.mock
    async def test_skips_empty_content_in_batch(self):
        mock_anchor(make_msg("333"))
        mock_batch([
            make_msg("334", content=""),   # system/embed — skip
            make_msg("335", content="Real message"),
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
        respx.get(f"{BASE}/channels/222/messages").mock(return_value=httpx.Response(403))

        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL)

        assert exc_info.value.code == "forbidden"

    @respx.mock
    async def test_404_raises_not_found(self):
        respx.get(f"{BASE}/channels/222/messages").mock(return_value=httpx.Response(404))

        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL)

        assert exc_info.value.code == "not_found"

    @respx.mock
    async def test_429_raises_rate_limited(self):
        respx.get(f"{BASE}/channels/222/messages").mock(return_value=httpx.Response(429))

        async with DiscordClient(TOKEN) as client:
            with pytest.raises(DiscordError) as exc_info:
                await client.read_thread(VALID_URL)

        assert exc_info.value.code == "rate_limited"

    def test_invalid_url_raises_before_any_network_call(self):
        with pytest.raises(DiscordError) as exc_info:
            parse_message_url("not-a-url-at-all")
        assert exc_info.value.code == "invalid_url"
