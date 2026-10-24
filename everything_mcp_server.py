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
# 'parent:' lists direct children (1 request), then per child we sum file
# sizes via paged size:large / size:huge / size:gigantic queries (files
# >=1MB only — the size: filter matches files only, so folder-heavy
# prefixes cannot dilute the sample). All queries hit the in-memory index
# (no disk load).


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


@mcp.tool()
def folder_sizes(path: str, max_results: int = 20, max_pages_per_folder: int = 1) -> str:
    """
    Rank the direct subfolders of a folder by total size, using the
    Everything index (in-memory; no filesystem traversal, no disk load).

    Use this (not search_files) to answer "which folders have grown large"
    under a root like 'C:\\Users\\User' or 'C:\\ProgramData'.
    Takes a full folder path; search_files takes filenames/patterns.

    Args:
        path: Root folder to analyze (e.g. 'C:\\Users\\User').
        max_results: How many largest subfolders to report (default 20, cap 50).
        max_pages_per_folder: Pages of 1000 files counted per size category
            (large/huge/gigantic; default 1 = 3 pages per folder).
            0 = list children only, no size counting.

    Returns subfolders sorted by total size of their files >=1MB (the size:
    filter matches files only, so folders cannot dilute the sample). Totals
    are lower bounds ('>=') when the page budget cuts counting short; files
    under 1MB are excluded by design (they do not drive bloat-scale totals).
    """
    root = _normalize_folder_path(path)
    if not (root.startswith("\\\\") or re.match(r"^[A-Za-z]:(($|\\))", root)):
        return "Error: path must be a folder like 'C:\\Users\\User' (drive letter + backslash)."
    if len(root) > 260:
        return "Error: path is too long (max 260 chars)."
    if max_results < 1:
        return "Error: max_results must be at least 1."
    max_results = min(max_results, 50)
    if max_pages_per_folder < 0:
        return "Error: max_pages_per_folder must be >= 0."

    try:
        parent_search = f"parent:{_quoted_path_prefix(root)}"
        data = _http_get({
            "search": parent_search,
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

    # size: categories (files only — folders have no size): large=1-16MB,
    # huge=16MB-1GB, gigantic=1GB+. Together they cover all files >=1MB.
    SIZE_CATEGORIES = ("size:large", "size:huge", "size:gigantic")

    PAGE = 1000
    budget = 400  # hard cap on HTTP pages per call: bounds worst-case latency
    # rows: (path, bytes, files_counted, files_total, total_known, state)
    # state: ok|skipped
    rows = []
    for child in children:
        cpath = f"{root}\\{child.get('name', '?')}"
        bytes_sum = 0
        files_counted = 0
        files_total = 0
        total_known = True
        state = "ok"
        if max_pages_per_folder > 0:
            for cat in SIZE_CATEGORIES:
                offset = 0
                pages = 0
                while pages < max_pages_per_folder:
                    if budget <= 0:
                        state = "skipped"
                        break
                    try:
                        data_c = _http_get({
                            "search": f"{_quoted_path_prefix(cpath)} {cat}",
                            "json": "1",
                            "count": str(PAGE),
                            "offset": str(offset),
                            "size_column": "1",
                            "type_column": "1",
                        })
                    except (requests.exceptions.RequestException, ValueError):
                        state = "skipped"
                        break
                    budget -= 1
                    pages += 1
                    items_c = data_c.get("results", []) if isinstance(data_c, dict) else []
                    cat_total = _get_total_results(data_c)
                    if cat_total is None:
                        total_known = False
                    else:
                        files_total += cat_total
                    if not items_c:
                        break
                    for it in items_c:
                        if isinstance(it, dict) and it.get("type") != "folder":
                            files_counted += 1
                            bytes_sum += _size_bytes(it.get("size"))
                    if len(items_c) < PAGE:
                        break
                    offset += len(items_c)
                if state == "skipped":
                    break
        rows.append((cpath, bytes_sum, files_counted, files_total, total_known, state))

    rows.sort(key=lambda r: r[1], reverse=True)
    top = rows[:max_results]
    lines = [f"[folder sizes for {root} — {len(rows)} direct subfolders, Everything index]"]
    for i, (cpath, b, f_c, f_t, total_known, state) in enumerate(top, 1):
        if state == "skipped":
            lines.append(f"{i:>2}. {cpath}  not counted (page budget exhausted)")
            continue
        if max_pages_per_folder == 0:
            size_s = "-"
            note = "-"
        else:
            complete = total_known and f_c >= f_t
            size_s = _format_size(b) if complete else f">= {_format_size(b)}"
            if not total_known:
                note = f"counted {f_c:,} files >=1MB"
            elif f_t:
                if complete:
                    note = f"{f_t:,} files >=1MB"
                else:
                    note = f"counted {f_c:,} of {f_t:,} files >=1MB"
            else:
                note = "no files >=1MB"
        lines.append(f"{i:>2}. {cpath}  {size_s}  [{note}]")
    if len(rows) > max_results:
        lines.append(f"... {len(rows) - max_results} smaller subfolders not shown (max_results={max_results})")
    lines.append("NOTE: '>=' = lower bound; totals cover files >=1MB only (smaller files excluded).")
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
