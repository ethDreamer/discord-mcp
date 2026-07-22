import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from discord_client import DiscordClient

load_dotenv(Path(__file__).parent / ".env")

mcp = FastMCP("discord-thread-reader")


@mcp.tool()
async def read_discord_thread(
    message_url: str,
    after_id: str | None = None,
    batch_size: int = 50,
) -> dict:
    """Fetch Discord messages starting from a given message URL.

    Args:
        message_url: Standard Discord message link (always required).
        after_id: If set, fetch messages after this ID instead of after the anchor.
                  Pass last_id from the previous call to paginate forward.
        batch_size: Messages to fetch per call (1-100). Default 50.

    Returns a dict with `messages`, `has_more`, and `last_id`.
    """
    token = os.environ.get("DISCORD_USER_TOKEN", "")
    if not token:
        raise RuntimeError("DISCORD_USER_TOKEN is not set")

    async with DiscordClient(token) as client:
        return await client.read_thread(message_url, after_id=after_id, batch_size=batch_size)


if __name__ == "__main__":
    mcp.run(transport="stdio")
