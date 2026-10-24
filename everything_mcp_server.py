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


# ============================ FOLDER SIZES ============================
#
# Everything's 'sizebyfolder' keyword is GUI-only: the HTTP API returns 0
# results for it (verified 2026-10-10). So folder totals are computed here:
# 'parent:' lists direct children (1 request), then per child we page
# through its path prefix and sum file sizes from the in-memory index
# (no disk load). Exact mode reads every indexed file; fast mode reads one
# page per size: category (files >=1MB only) and reports lower bounds.
#
# Page size trade-off (measured 2026-10-25): 100k rows ~= 1M rows/s and
# ~100 MB/s of localhost JSON; 10k rows is ~30% slower and uses ~10x more
# requests. Everything reports totalResults, so a page is never assumed
# complete just because it looks short.

PAGE_SIZE = 50_000
PAGE_BUDGET = 400  # hard cap on HTTP pages per call: bounds worst-case latency
SIZE_CATEGORIES = ("size:large", "size:huge", "size:gigantic")  # covers all files >=1MB


def _size_bytes(value) -> int:
    """Parse an Everything 'size' field into int bytes (0 for folders/junk)."""
    if value in (None, ""):
        return 0
    try:
        n = int(value)
    except (ValueError, TypeError):
        return 0
    return max(n, 0)


def _normalize_folder_path(path: str) -> str:
    """Normalize a folder path: trim, drop quotes, unify to backslashes."""
    p = path.strip().strip('"')
    p = p.replace("/", "\\")
    while len(p) > 2 and p.endswith("\\"):
        p = p[:-1]
    return p


def _quoted_path_prefix(path: str) -> str:
    """Everything query term for a path: quoted, with a trailing backslash.

    Quotes keep spaces inside a single term ('C:\\Program Files' otherwise
    splits into two AND-ed terms). The trailing backslash stops a folder from
    absorbing sibling prefixes ('C:\\Program Files' would also match
    'C:\\Program Files (x86)').
    """
    return '"' + path.rstrip("\\") + '\\"'


def _http_get(params: dict) -> dict | list:
    """GET the Everything HTTP server with params; returns parsed JSON."""
    url = EVERYTHING_URL + "?" + urllib.parse.urlencode(params)
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _scan(search: str, budget: list[int], max_pages: int | None = None) -> tuple[int, int, int, bool]:
    """Page through one Everything query and sum file sizes.

    Returns (bytes, files_counted, items_total, complete). items_total is the
    server's totalResults (files and folders alike), or the rows seen when the
    server does not report it. complete is False when the page budget ran out
    or a page failed -- callers must then print a lower bound.
    """
    size_sum = files = offset = pages = 0
    items_total = None
    complete = True
    while True:
        if budget[0] <= 0:
            complete = False
            break
        try:
            data = _http_get({
                "search": search,
                "json": "1",
                "count": str(PAGE_SIZE),
                "offset": str(offset),
                "size_column": "1",
                "type_column": "1",
            })
        except (requests.exceptions.RequestException, ValueError):
            complete = False
            break
        budget[0] -= 1
        pages += 1
        if items_total is None:
            items_total = _get_total_results(data)
        rows = data.get("results", []) if isinstance(data, dict) else []
        for it in rows:
            if isinstance(it, dict) and it.get("type") != "folder":
                files += 1
                size_sum += _size_bytes(it.get("size"))
        offset += len(rows)
        done = (
            not rows
            or (items_total is not None and offset >= items_total)
            or (items_total is None and len(rows) < PAGE_SIZE)
        )
        if done:
            break
        if max_pages is not None and pages >= max_pages:
            complete = False
            break
    if items_total is None:
        items_total = offset
    return size_sum, files, items_total, complete


@mcp.tool()
def folder_sizes(path: str, max_results: int = 20, exact: bool = True) -> str:
    """
    Rank the direct subfolders of a folder by total size, using the
    Everything index (in-memory; no filesystem traversal, no disk load).

    Use this (not search_files) to answer "which folders have grown large"
    under a root like 'C:\\Users\\User' or 'C:\\ProgramData'.
    Takes a full folder path; search_files takes filenames/patterns.

    Args:
        path: Root folder to analyze (e.g. 'C:\\Users\\User').
        max_results: How many largest subfolders to report (default 20, cap 50).
        exact: True (default) sums every indexed file under each subfolder.
            Accurate, but a whole drive costs ~10 s and a few hundred MB of
            local HTTP traffic. False sums only files >=1MB from one page per
            size category: much less traffic, but numbers are lower bounds.

    Returns subfolders sorted by size. Sizes are logical file sizes from the
    Everything index, not physical disk usage. The first line names the mode;
    '>=' marks a lower bound when the page budget cut counting short.
    """
    root = _normalize_folder_path(path)
    if not (root.startswith("\\\\") or re.match(r"^[A-Za-z]:(($|\\))", root)):
        return "Error: path must be a folder like 'C:\\Users\\User' (drive letter + backslash)."
    if len(root) > 260:
        return "Error: path is too long (max 260 chars)."
    if max_results < 1:
        return "Error: max_results must be at least 1."
    max_results = min(max_results, 50)

    try:
        data = _http_get({
            "search": f"parent:{_quoted_path_prefix(root)}",
            "json": "1",
            "count": "1000",
            "path_column": "1",
            "type_column": "1",
        })
    except requests.exceptions.ConnectionError:
        return ("Error: Could not connect to Everything HTTP server. "
                "Ensure it is enabled on port 8888 (Tools -> Options -> HTTP Server).")
    except requests.exceptions.Timeout:
        return "Error: Request timed out. The Everything server may be overloaded or unreachable."
    except requests.exceptions.RequestException as exc:
        return f"Error: Everything request failed: {exc}"
    except ValueError:
        return "Error: Everything returned a non-JSON response."

    items = data.get("results", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    children = [it for it in items if isinstance(it, dict) and it.get("type") == "folder"]
    if not children:
        return f"No direct subfolders found for {root} in the Everything index."

    budget = [PAGE_BUDGET]
    # rows: (path, bytes, files_counted, files_total, complete)
    rows = []
    for child in children:
        cpath = f"{root}\\{child.get('name', '?')}"
        prefix = _quoted_path_prefix(cpath)
        if exact:
            size_sum, files, items_total, complete = _scan(prefix, budget)
            rows.append((cpath, size_sum, files, items_total, complete))
            continue
        size_sum = files = files_total = 0
        complete = True
        for cat in SIZE_CATEGORIES:
            cat_bytes, cat_files, cat_total, cat_complete = _scan(
                f"{prefix} {cat}", budget, max_pages=1
            )
            size_sum += cat_bytes
            files += cat_files
            files_total += cat_total
            complete = complete and cat_complete
        rows.append((cpath, size_sum, files, files_total, complete))

    rows.sort(key=lambda r: r[1], reverse=True)
    top = rows[:max_results]
    if exact:
        lines = [f"[exact: all indexed files, logical sizes | {root} | {len(rows)} direct subfolders]"]
    else:
        lines = [f"[fast: only files >=1MB, lower bounds | {root} | {len(rows)} direct subfolders]"]
    for i, (cpath, size_sum, files, items_total, complete) in enumerate(top, 1):
        if not complete and not files:
            lines.append(f"{i:>2}. {cpath}  not counted (page budget exhausted)")
            continue
        size_s = _format_size(size_sum) if complete else f">= {_format_size(size_sum)}"
        if exact:
            note = f"{files:,} files" if complete else f"partial: {files:,} files, cut short"
        elif not files and not items_total:
            note = "no files >=1MB"
        elif complete:
            note = f"{files:,} files >=1MB"
        else:
            note = f"counted {files:,} of {items_total:,} files >=1MB"
        lines.append(f"{i:>2}. {cpath}  {size_s}  [{note}]")
    if len(rows) > max_results:
        lines.append(f"... {len(rows) - max_results} smaller subfolders not shown (max_results={max_results})")
    if exact:
        lines.append("NOTE: exact = every file in the Everything index; sizes are logical (MFT), not on-disk usage.")
    else:
        lines.append("NOTE: fast = files under 1MB are not counted; numbers are lower bounds ('>=' when cut short).")
    return "\n".join(lines)


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
        "9. Path scoping: the path itself is a query — 'C:\\Projects' matches\n"
        "   every full path containing it (i.e. everything under that folder).\n"
        "10. Folder sizes: 'sizebyfolder' is GUI-only (the HTTP API returns 0 for it) —\n"
        "    use the folder_sizes tool to rank subfolders by total size.\n"
        "------------------------------------------------------------------\n"
        "Pro Tip: Combine filters to avoid context overflow: 'ext:md size:small dm:today'.\n"
        "If results are truncated, narrow the query or paginate with the offset parameter."
    )
    return tips


if __name__ == "__main__":
    mcp.run()
