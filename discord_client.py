import re
import httpx

_URL_PATTERN = re.compile(
    r"https?://(?:[\w-]+\.)?discord\.com/channels/(\d+)/(\d+)/(\d+)"
)

BASE_URL = "https://discord.com/api/v10"


class DiscordError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def parse_message_url(url: str) -> tuple[str, str, str]:
    match = _URL_PATTERN.fullmatch(url.strip())
    if not match:
        raise DiscordError("invalid_url", f"Not a valid Discord message URL: {url}")
    return match.group(1), match.group(2), match.group(3)


class DiscordClient:
    def __init__(self, token: str):
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": token},
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._http.aclose()

    def _check(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise DiscordError("unauthorized", f"401 Unauthorized — {response.text}")
        if response.status_code == 403:
            raise DiscordError("forbidden", f"403 Forbidden — {response.text}")
        if response.status_code == 404:
            raise DiscordError("not_found", f"404 Not Found — {response.text}")
        if response.status_code == 429:
            raise DiscordError("rate_limited", f"429 Rate Limited — {response.text}")
        response.raise_for_status()

    def _format(self, raw: dict, *, is_anchor: bool = False) -> dict:
        author = raw.get("author", {})
        return {
            "id": raw["id"],
            "author": author.get("global_name") or author.get("username", "Unknown"),
            "timestamp": raw["timestamp"],
            "content": raw["content"],
            "is_anchor": is_anchor,
        }

    async def _fetch_message(self, channel_id: str, message_id: str) -> dict:
        r = await self._http.get(
            f"/channels/{channel_id}/messages",
            params={"around": message_id, "limit": 1},
        )
        self._check(r)
        for msg in r.json():
            if msg["id"] == message_id:
                return msg
        raise DiscordError("not_found", f"Message {message_id} not found")

    async def _fetch_after(self, channel_id: str, after_id: str, limit: int) -> list[dict]:
        r = await self._http.get(
            f"/channels/{channel_id}/messages",
            params={"after": after_id, "limit": limit},
        )
        self._check(r)
        return r.json()

    async def read_thread(
        self,
        message_url: str,
        after_id: str | None = None,
        batch_size: int = 50,
    ) -> dict:
        _, channel_id, message_id = parse_message_url(message_url)

        messages: list[dict] = []
        cursor = after_id if after_id is not None else message_id

        if after_id is None:
            anchor_raw = await self._fetch_message(channel_id, message_id)
            if anchor_raw.get("content"):
                messages.append(self._format(anchor_raw, is_anchor=True))

        raw_batch = await self._fetch_after(channel_id, cursor, batch_size)

        for raw in raw_batch:
            if raw.get("content"):
                messages.append(self._format(raw))

        has_more = len(raw_batch) == batch_size
        last_id = raw_batch[-1]["id"] if raw_batch else message_id

        return {"messages": messages, "has_more": has_more, "last_id": last_id}
