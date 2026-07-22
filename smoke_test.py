import asyncio
import os

from dotenv import load_dotenv

from discord_client import DiscordClient

load_dotenv()


async def main():
    url = input("Paste a Discord message URL: ").strip()
    async with DiscordClient(os.environ["DISCORD_USER_TOKEN"]) as client:
        result = await client.read_thread(url)

    for m in result["messages"]:
        anchor = " [anchor]" if m["is_anchor"] else ""
        print(f"{m['author']}{anchor}: {m['content'][:100]}")

    print(f"\nhas_more={result['has_more']}  last_id={result['last_id']}")


asyncio.run(main())
