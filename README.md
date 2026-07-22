# discord-mcp

A personal MCP (Model Context Protocol) server that lets Claude read Discord message threads. Give Claude a Discord message URL and it can fetch the thread content directly.

## What it does

Exposes a single `read_discord_thread` tool to Claude that:

- Fetches the anchor message and all subsequent messages in a channel thread
- Supports pagination for long threads via `after_id` and `batch_size`
- Skips system messages and embeds (empty-content messages)
- Returns structured data: author, timestamp, content, and pagination state

This uses your personal Discord account token, so it can read any server you're a member of — no bot invite required.

## Obtaining your Discord auth token

> **Warning:** Your user token is equivalent to your Discord password. Never share it or commit it to version control.

1. Open Discord in your browser (discord.com)
2. Open DevTools (`F12` or `Ctrl+Shift+I`)
3. Go to the **Network** tab
4. In Discord, navigate to any channel or send any message to trigger a network request
5. Filter requests by `XHR` or search for `messages`
6. Click any request to `discord.com/api/v9/` or `discord.com/api/v10/`
7. In the **Request Headers** section, find the `Authorization` header — its value is your token

Alternatively, in the **Console** tab you can run:
```js
webpackChunkdiscord_app.push([[Math.random()],{},r=>{m=[];for(let c in r.c)m.push(r.c[c])}]);
m.find(m=>m?.exports?.default?.getToken).exports.default.getToken()
```

Copy the token value (no `Bot ` prefix — that's only for bot accounts).

## Setup

**Prerequisites:** Python 3.10+, `uv`

```bash
cd /path/to/discord-mcp
uv venv
uv pip install -r requirements.txt
```

Create a `.env` file (see `.env.example`):

```bash
DISCORD_USER_TOKEN=your_token_here
```

## Testing

Run the unit tests:

```bash
.venv/bin/pytest
```

Run the smoke test with a real Discord URL:

```bash
.venv/bin/python smoke_test.py
```

## Registering with Claude Code

Register the server globally so it's available in all your Claude Code sessions:

```bash
claude mcp add --scope user discord \
  /path/to/discord-mcp/.venv/bin/python \
  /path/to/discord-mcp/server.py
```

Verify it's connected:

```bash
claude mcp get discord
```

You should see `Status ✔ Connected`.

## Registering with Codex

Register the server with Codex as a local stdio MCP server:

```bash
codex mcp add discord -- \
  /path/to/discord-mcp/.venv/bin/python \
  /path/to/discord-mcp/server.py
```

Verify that it is configured:

```bash
codex mcp get discord
codex mcp list
```

Restart Codex or open a new session after adding the server. In the Codex
terminal UI, run `/mcp` to confirm that `discord` and its
`read_discord_thread` tool are available.

## Usage

Once registered, ask Claude or Codex things like:

> "Read this Discord thread: https://discord.com/channels/123/456/789"

> "Summarize the conversation starting at this message: https://discord.com/channels/..."

The assistant will call `read_discord_thread` and have access to the message content. For long threads, it can paginate by passing the returned `last_id` as `after_id` in subsequent calls.

## How it works

- Uses Discord's REST API v10 with your user token
- Fetches the anchor message via `?around=<id>&limit=1` (the direct endpoint is bot-only)
- Paginates forward with `?after=<id>&limit=<batch_size>`
- Runs as a stdio MCP server — Claude Code or Codex spawns it as a subprocess when needed
