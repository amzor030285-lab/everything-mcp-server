import pytest

import everything_mcp_server as m


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "unknown size"),
        ("abc", "unknown size"),
        (-5, "unknown size"),
        (0, "0 B"),
        (999, "999.00 B"),
        (1024, "1.00 KB"),
        (1536, "1.50 KB"),
        (1024**2, "1.00 MB"),
        (1024**3, "1.00 GB"),
        (int(1.5 * 1024**3), "1.50 GB"),
    ],
)
def test_format_size(value, expected):
    assert m._format_size(value) == expected


def test_format_filetime_unix_epoch():
    assert m._format_filetime(116444736000000000) == "1970-01-01 00:00"


@pytest.mark.parametrize("value", [None, "", 0, -1, "abc"])
def test_format_filetime_unknown(value):
    assert m._format_filetime(value) == "unknown date"


@pytest.mark.parametrize("query", ["", "   ", "*", "***", "a", "e", "a" * 101])
def test_validate_query_rejects(query):
    with pytest.raises(ValueError):
        m._validate_query(query)


@pytest.mark.parametrize(
    "query,expected",
    [("report", "report"), ("  ext:md  ", "ext:md"), ("ab", "ab"), ("яя", "яя")],
)
def test_validate_query_accepts(query, expected):
    assert m._validate_query(query) == expected


def test_quoted_path_prefix():
    assert m._quoted_path_prefix("C:\\Program Files") == '"C:\\Program Files\\"'
    assert m._quoted_path_prefix("C:\\") == '"C:\\"'
    assert m._quoted_path_prefix("\\\\srv\\share") == '"\\\\srv\\share\\"'


def test_normalize_folder_path():
    assert m._normalize_folder_path("C:/Users/User/") == "C:\\Users\\User"
    assert m._normalize_folder_path('"C:\\Users\\User"') == "C:\\Users\\User"
    assert m._normalize_folder_path("C:\\") == "C:"


@pytest.mark.parametrize(
    "value,expected",
    [(None, 0), ("", 0), ("abc", 0), (-5, 0), ("1024", 1024), (7, 7)],
)
def test_size_bytes(value, expected):
    assert m._size_bytes(value) == expected


def test_folder_sizes_validation_happens_before_any_request():
    assert m.folder_sizes("not a path").startswith("Error:")
    assert m.folder_sizes("C:\\Windows", max_results=0).startswith("Error:")
