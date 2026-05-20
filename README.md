# Everything Search MCP Server

MCP server that gives AI agents fast local file search via the [Everything](https://www.voidtools.com/) search engine on Windows.

## What it does

Exposes Everything's instant file search as MCP tools, so AI agents can find files on the local machine without shell commands or slow filesystem traversal.

## Tools

### `search_files(query, max_results=50)`

Search for files and folders using Everything's indexed search.

```
query: filename or pattern (e.g. "report", "ext:py", "project AND config")
max_results: 1-100 (default 50)
```

Returns: file name, full path, and human-readable size.

### `get_search_tips()`

Returns advanced search syntax reference (extensions, dates, size filters, boolean operators, regex).

## Security

- Input validation on query length (max 100 chars) and result count (max 100)
- Blocks overly broad patterns (e.g. `*` alone)
- 5-second timeout on HTTP requests
- Graceful error handling with actionable hints

## Requirements

- Windows with [Everything](https://www.voidtools.com/) installed
- Everything HTTP Server enabled (Tools → Options → HTTP Server, port 8888)
- Python 3.10+

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
