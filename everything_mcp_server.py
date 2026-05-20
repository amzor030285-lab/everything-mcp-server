from mcp.server.fastmcp import FastMCP
import urllib.parse
import json
import requests
import re

# Initialize FastMCP server
mcp = FastMCP("EverythingSearch")

# Everything HTTP Server URL
EVERYTHING_URL = "http://127.0.0.1:8888/"

# КОНСТАНТЫ БЕЗОПАСНОСТИ
MAX_RESULTS_DEFAULT = 50  # Максимум файлов за один запрос
MAX_QUERY_LENGTH = 100    # Максимальная длина запроса в символах
MAX_RESULTS_HARD_LIMIT = 100  # Абсолютный потолок


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
    while size_bytes >= 1024 and idx < len(units) - 1:
        size_bytes /= 1024
        idx += 1
    return f"{size_bytes:.2f} {units[idx]}"


@mcp.tool()
def search_files(query: str, max_results: int = MAX_RESULTS_DEFAULT) -> str:
    """
    Search for files and folders on the local machine using the Everything Search engine.

    IMPORTANT: Use only the filename or search pattern, NOT full paths.
    
    Args:
        query: The search term (e.g., 'report', 'ext:py'). Do not use full paths.
        max_results: Number of results to return (default: 50). Max allowed: 100.

    Returns a list of files with their paths and modification dates.
    """
    # 1. ВАЛИДАЦИЯ max_results
    if not isinstance(max_results, int):
        return f"Error: max_results must be an integer, got {type(max_results).__name__}."
    if max_results < 1:
        return "Error: max_results must be at least 1."
    if max_results > MAX_RESULTS_HARD_LIMIT:
        max_results = MAX_RESULTS_HARD_LIMIT

    # 2. ВАЛИДАЦИЯ ЗАПРОСА
    if len(query) > MAX_QUERY_LENGTH:
        return f"Error: Query is too long ({len(query)} chars). Max allowed is {MAX_QUERY_LENGTH}."
    
    query = query.strip()
    if not query:
        return "Error: Query cannot be empty. Please provide a filename or pattern (e.g., 'report', 'ext:py')."

    # 3. ЗАЩИТА ОТ ШИРОКИХ ПОИСКОВ (если нет фильтров)
    if re.match(r'^[\*\s]+$', query):
        return "Error: Too broad search pattern detected. Please specify a filename or extension (e.g., 'ext:md')."

    try:
        encoded_query = urllib.parse.quote(query)
        
        # Используем параметр count (корректное имя для Everything HTTP API)
        url = f"{EVERYTHING_URL}?search={encoded_query}&json=1&path_column=1&count={max_results}"

        response = requests.get(url, timeout=5)
        response.raise_for_status()

        data = response.json()
        
        # Everything API может вернуть dict {"results": [...]} или plain list
        if isinstance(data, dict):
            items = data.get("results", [])
        elif isinstance(data, list):
            items = data
        else:
            items = []

        if not items:
            return _empty_result_hint(query)

        results = []
        for item in items[:max_results]:  # Дополнительная защита на случай игнорирования count
            if not isinstance(item, dict):
                continue
            
            name = item.get("name", "Unknown")
            path = item.get("path", "Unknown")
            size = _format_size(item.get("size"))
            
            results.append(f"{name} -> {path} ({size})")

        # Если сервер вернул больше, чем запрошено (count проигнорирован)
        if len(items) > max_results:
            return (
                f"[WARNING] Server returned {len(items)} items, showing first {max_results}. "
                + "Use a more specific query or filter.\n\n"
                + "\n".join(results)
            )

        return "\n".join(results)

    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to Everything Search HTTP server. Please ensure it is enabled on port 8888."
    except requests.exceptions.Timeout:
        return "Error: Request timed out. The Everything server may be overloaded or unreachable."
    except Exception as e:
        return f"Error: {str(e)}"


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
    """Provides comprehensive tips and advanced search syntax for the Everything Search engine."""
    tips = (
        "Everything Search Advanced Syntax:\n"
        "------------------------------------------------------------------\n"
        "1. Extensions: 'ext:jpg;png;pdf' (Finds all JPG, PNG, and PDF files)\n"
        "2. Exact Match: '\"report 2024\"' (Finds only files matching this exact phrase)\n"
        "3. Dates: 'dm:today' (Modified today), 'dm:yesterday' (Modified yesterday)\n"
        "4. Size: 'size:tiny' (<10kb), 'size:small' (10-100kb), 'size:huge' (>100mb)\n"
        "5. Folders: 'folder:myfolder' (Search only within specific folder)\n"
        "6. Boolean: 'project AND config', 'project OR config', 'project NOT logs'\n"
        "7. Regex: 'regex:^test.*\\.py$'\n"
        "------------------------------------------------------------------\n"
        "Pro Tip: Combine filters to avoid context overflow: 'ext:md size:small dm:today'."
    )
    return tips


if __name__ == "__main__":
    mcp.run()
