# Everything Search MCP Server

MCP server that gives AI agents fast local file search via the [Everything](https://www.voidtools.com/) search engine on Windows.

## What it does

Exposes Everything's instant file search as MCP tools, so AI agents can find files on the local machine without shell commands or slow filesystem traversal.

## Tools

### `search_files(query, max_results=50, offset=0)`

Search for files and folders using Everything's indexed search.

```
query: filename or pattern (e.g. "report", "ext:py", "project AND config")
max_results: results per page, 1-100 (default 50)
offset: skip this many results to paginate further (default 0)
```

Returns: file name, full path, human-readable size, modification date,
and a `[showing N of M total]` header. If there are more matches, the output
includes the next `offset` value for pagination.

### `folder_sizes(path, max_results=20, exact=True)`

Rank direct subfolders of a folder by total size, computed from the Everything
index (in-memory; no filesystem traversal, no disk load). Use this instead of
`search_files` when the question is "which folders are big", not "where is this file".

```
path: root folder to analyze (e.g. "C:\\Users\\User")
max_results: largest subfolders to report, 1-50 (default 20)
exact: true (default) = every indexed file; false = only files >=1MB, one page per size category
```

`exact=true` is accurate: about 3-5 s for a normal folder, ~13 s and a few
hundred MB of localhost traffic for a whole drive. `exact=false` reads much
less but counts only files >=1MB from one page per size category, so sizes are
lower bounds (`>=`). Sizes are logical file sizes from the index, not physical
disk usage. The first output line names the mode, so the numbers always come
with their caveat attached.

### `get_search_tips()`

Returns advanced search syntax reference (extensions, dates, size filters,
folder scoping via `parent:`, boolean operators, regex).

## Configuration

Optional environment variables:

| Variable             | Default                    | Description                     |
|----------------------|----------------------------|---------------------------------|
| `EVERYTHING_URL`     | `http://127.0.0.1:8888/`   | Everything HTTP server endpoint |
| `EVERYTHING_TIMEOUT` | `5`                        | Request timeout in seconds      |

## Security

- Input validation on query length (max 100 chars) and result count/offset
- Blocks overly broad patterns (`*` alone, single-character queries) — queries need at least ~2 significant characters
- Requests are capped at 100 rows per page; use `offset` instead of huge dumps
- 5-second timeout on HTTP requests (configurable)
- Graceful error handling with actionable hints

## Requirements

- Windows with [Everything](https://www.voidtools.com/) installed
- Everything HTTP Server enabled (Tools → Options → HTTP Server, port 8888)
- Python 3.10+

> **SDK version note (2026-09-09):** requires `mcp` SDK **2.x** (`mcp.server.mcpserver.MCPServer`).
> If you installed an older copy of this server, run `pip install -U mcp` to get 2.x.
> Details of the v1→v2 migration: see `DEVLOG.md`.

## Install

```bash
pip install -r requirements.txt
```

## Configure in OpenClaw

Add to your `openclaw.json` MCP config:

```json
"mcp": {
  "servers": {
    "everything-search": {
      "command": "python",
      "args": [
        "path/to/everything_mcp_server.py"
      ]
    }
  }
}
```

**Note:** `command` and `args` are separate fields. Replace `path/to/` with the actual path on your machine.

## Why this exists

Everything Search indexes NTFS volumes in milliseconds, but has no native MCP integration. This server bridges that gap — agents get instant file search without shell access or slow `Get-ChildItem` traversal.

Built because no equivalent MCP server existed.
