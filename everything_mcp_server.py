import os
import re
import urllib.parse
from datetime import datetime, timedelta

import requests
from mcp.server.mcpserver import MCPServer

# Initialize MCPServer (mcp SDK 2.x; was FastMCP in 1.x)
mcp = MCPServer("EverythingSearch")

# Конфигурация (можно переопределить переменными окружения)
EVERYTHING_URL = os.environ.get("EVERYTHING_URL", "http://127.0.0.1:8888/")
REQUEST_TIMEOUT = float(os.environ.get("EVERYTHING_TIMEOUT", "5"))

# КОНСТАНТЫ БЕЗОПАСНОСТИ
MAX_RESULTS_DEFAULT = 50  # Максимум файлов за один запрос по умолчанию
MAX_QUERY_LENGTH = 100    # Максимальная длина запроса в символах
MAX_RESULTS_HARD_LIMIT = 100  # Абсолютный потолок

# Windows FILETIME: интервалы по 100 нс с 1601-01-01 UTC
_FILETIME_EPOCH = datetime(1601, 1, 1)


def _format_size(size_bytes) -> str:
    """Convert raw bytes to human-readable string."""
    if size_bytes is None:
        return "unknown size"
    try:
        size_bytes = int(size_bytes)
    except (ValueError, TypeError):
        return "unknown size"
    if size_bytes < 0:
        return "unknown size"
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    value = float(size_bytes)
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    return f"{value:.2f} {units[idx]}"


def _format_filetime(value) -> str:
    """Convert Windows FILETIME (100ns intervals since 1601-01-01) to readable date."""
    if value in (None, ""):
        return "unknown date"
    try:
        ticks = int(value)
    except (ValueError, TypeError):
        return "unknown date"
    if ticks <= 0:
        return "unknown date"
    try:
        dt = _FILETIME_EPOCH + timedelta(microseconds=ticks // 10)
    except OverflowError:
        return "unknown date"
    return dt.strftime("%Y-%m-%d %H:%M")


def _get_total_results(data) -> int | None:
    """Extract totalResults from the Everything JSON response, if present."""
    if not isinstance(data, dict):
        return None
    try:
        total = int(data.get("totalResults"))
    except (TypeError, ValueError):
        return None
    return total if total >= 0 else None


def _validate_query(query: str) -> str:
    """Return cleaned query or raise ValueError with a reason."""
    query = query.strip()
    if not query:
        raise ValueError(
            "Query cannot be empty. Provide a filename or pattern (e.g., 'report', 'ext:py')."
        )
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(
            f"Query is too long ({len(query)} chars). Max allowed is {MAX_QUERY_LENGTH}."
        )
    # Защита от широких поисков: нужны минимум ~2 значимых символа
    meaningful = re.sub(r"[\*\s]", "", query)
    if not re.search(r"[A-Za-zА-Яа-яЁё0-9]", meaningful) or len(meaningful) < 2:
        raise ValueError(
            "Query is too broad. Specify a filename, part of a name "
            "or a filter (e.g., 'ext:md', 'dm:today', 'size:gigantic')."
        )
    return query


@mcp.tool()
def search_files(query: str, max_results: int = MAX_RESULTS_DEFAULT, offset: int = 0) -> str:
    """
    Search for files and folders on the local machine using the Everything Search engine.

    IMPORTANT: Use only the filename or search pattern, NOT full paths.
    Queries need at least ~2 significant characters; overly broad patterns
    (single letters, bare '*') are rejected.

    Args:
        query: Search term or Everything filter (e.g., 'report', 'ext:py',
            'ext:md dm:today'). Do not use full paths. Combine filters to narrow results.
        max_results: Number of results per page (default: 50, hard cap: 100).
        offset: Skip this many results to paginate further (default: 0).

    Returns file names with full paths, sizes and modification dates,
    plus a '[showing N of M]' header indicating whether results were truncated.
    If unsure about Everything search syntax, call get_search_tips() first.
    """
    try:
        query = _validate_query(query)
    except ValueError as exc:
        return f"Error: {exc}"

    if max_results < 1:
        return "Error: max_results must be at least 1."
    max_results = min(max_results, MAX_RESULTS_HARD_LIMIT)
    if offset < 0:
        return "Error: offset must be >= 0."

    url = (
        f"{EVERYTHING_URL}?search={urllib.parse.quote(query)}"
        "&json=1&path_column=1&size_column=1&date_modified_column=1"
        f"&count={max_results}&offset={offset}"
    )

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.ConnectionError:
        return (
            "Error: Could not connect to Everything HTTP server. "
            "Ensure it is enabled on port 8888 (Tools -> Options -> HTTP Server)."
        )
    except requests.exceptions.Timeout:
        return "Error: Request timed out. The Everything server may be overloaded or unreachable."
    except requests.exceptions.RequestException as exc:
        return f"Error: Everything request failed: {exc}"
    except ValueError:
        return "Error: Everything returned a non-JSON response."

    if isinstance(data, dict):
        items = data.get("results", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []

    if not items:
        return _empty_result_hint(query)

    results = []
    for item in items[:max_results]:
        if not isinstance(item, dict):
            continue

        name = item.get("name", "Unknown")
        path = item.get("path", "Unknown")
        size = _format_size(item.get("size"))
        modified = _format_filetime(item.get("date_modified"))

        results.append(f"{name} -> {path} ({size}, {modified})")

    total = _get_total_results(data)
    header = f"[showing {len(results)} of {total} total]" if total is not None else f"[showing {len(results)}]"

    body = "\n".join(results)
    if total is not None and offset + len(results) < total:
        body += f"\n\nMore results available ({total - offset - len(results)} remaining). Call again with offset={offset + len(results)}."
        body += "\nTIP: Narrow the query instead (ext:, dm:, size:) if you don't need everything."

    return f"{header}\n{body}"


def _empty_result_hint(query: str) -> str:
    """Return a helpful hint when no results are found."""
    looks_like_path = bool(re.search(r'[\\/]', query))

    hint = f"No files found for query: {query}\n"
    if looks_like_path:
        hint += "\nHINT: Your query looks like a file path. Use only the filename, not the full path.\n"
        hint += "Example: instead of 'C:\\Users\\file.txt', use 'file.txt'\n"
    else:
        hint += "\nHINT: Try adding an extension filter (e.g., 'ext:md') or a folder name.\n"

    return hint


@mcp.tool()
def get_search_tips() -> str:
    """Provides comprehensive tips and advanced search syntax for the Everything Search engine.

    Call this before constructing complex queries (filters, dates, sizes,
    folder scoping, boolean operators, regex) or when a search returns
    unexpected results.
    """
    tips = (
        "Everything Search Advanced Syntax:\n"
        "------------------------------------------------------------------\n"
        "1. Extensions: 'ext:jpg;png;pdf' (Finds all JPG, PNG, and PDF files)\n"
        "2. Exact Match: '\"report 2024\"' (Finds only files matching this exact phrase)\n"
        "3. Dates: 'dm:today' (Modified today), 'dm:yesterday' (Modified yesterday)\n"
        "4. Size: 'size:tiny' (<10kb), 'size:small' (10-100kb), 'size:medium' (100kb-1mb),\n"
        "   'size:large' (1-16mb), 'size:huge' (16mb-1gb), 'size:gigantic' (>1gb)\n"
        "5. Scope to folder: 'parent:C:\\Projects\\myapp' (files directly inside it),\n"
        "   or simply include the folder name in the query ('myapp ext:py')\n"
        "6. Folders only: 'folder:backup' matches folders NAMED backup (NOT their contents!)\n"
        "7. Boolean: 'project AND config', 'project OR config', 'project NOT logs'\n"
        "8. Regex: 'regex:^test.*\\.py$'\n"
        "------------------------------------------------------------------\n"
        "Pro Tip: Combine filters to avoid context overflow: 'ext:md size:small dm:today'.\n"
        "If results are truncated, narrow the query or paginate with the offset parameter."
    )
    return tips


if __name__ == "__main__":
    mcp.run()
