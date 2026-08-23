import pytest

from uc_steamos_agent.commands import shortcuts


def test_list_shortcuts_returns_sorted_filenames(tmp_path):
    (tmp_path / "Chrome").write_text("steam://openurl/https://google.com")
    (tmp_path / "VLC").write_text("/usr/bin/vlc")
    assert shortcuts.list_shortcuts(str(tmp_path)) == ["Chrome", "VLC"]


def test_list_shortcuts_missing_dir_returns_empty(tmp_path):
    assert shortcuts.list_shortcuts(str(tmp_path / "missing")) == []


def test_read_shortcut_strips_whitespace(tmp_path):
    (tmp_path / "Netflix").write_text("  https://netflix.com  \n")
    assert shortcuts.read_shortcut(str(tmp_path), "Netflix") == "https://netflix.com"


def test_read_shortcut_missing_raises(tmp_path):
    with pytest.raises(shortcuts.ShortcutError, match="no such shortcut"):
        shortcuts.read_shortcut(str(tmp_path), "DoesNotExist")


def test_read_shortcut_empty_file_raises(tmp_path):
    (tmp_path / "Empty").write_text("   ")
    with pytest.raises(shortcuts.ShortcutError, match="empty"):
        shortcuts.read_shortcut(str(tmp_path), "Empty")


@pytest.mark.parametrize("bad_name", ["../escape", "a/b", "..", "."])
def test_read_shortcut_rejects_path_traversal(tmp_path, bad_name):
    with pytest.raises(shortcuts.ShortcutError, match="invalid shortcut name"):
        shortcuts.read_shortcut(str(tmp_path), bad_name)


def test_is_url():
    assert shortcuts.is_url("steam://open/games") is True
    assert shortcuts.is_url("https://youtube.com") is True
    assert shortcuts.is_url("http://example.com") is True
    assert shortcuts.is_url("/usr/bin/vlc") is False
