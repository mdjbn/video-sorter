from __future__ import annotations

from pathlib import Path

from videosorter.paths import is_same_dir, is_under, norm_path, overlap_message, overlaps


def test_norm_path_strips_trailing_separator(tmp_path: Path) -> None:
    d = tmp_path / "a"
    d.mkdir()
    assert norm_path(f"{d}/") == norm_path(d)
    assert norm_path(f"{d}///") == norm_path(d)


def test_norm_path_keeps_root() -> None:
    assert norm_path("/") == "/"


def test_norm_path_empty() -> None:
    assert norm_path("") == ""
    assert norm_path("   ") == ""


def test_same_dir(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    assert is_same_dir(a, f"{a}/")
    assert not is_same_dir(a, tmp_path / "b")


def test_sibling_prefix_is_not_under(tmp_path: Path) -> None:
    """`/a/bc` 不在 `/a/b` 里面——裸 startswith 会误判成重叠。"""
    parent = tmp_path / "b"
    sibling = tmp_path / "bc"
    parent.mkdir()
    sibling.mkdir()
    assert not is_under(sibling, parent)
    assert not overlaps(sibling, parent)


def test_child_is_under(tmp_path: Path) -> None:
    parent = tmp_path / "b"
    child = parent / "c"
    child.mkdir(parents=True)
    assert is_under(child, parent)
    assert overlaps(child, parent)
    assert overlaps(parent, child)


def test_self_overlaps(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    assert overlaps(a, a)


def test_disjoint_dirs_do_not_overlap(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert not overlaps(a, b)


def test_empty_path_never_overlaps(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    assert not overlaps("", a)
    assert not is_under("", a)


def test_sibling_under_common_parent_compliant(tmp_path: Path) -> None:
    """源 /videos/inbox 与标签 /videos/sorted/旅行：同父但不嵌套，属于合规布局。"""
    inbox = tmp_path / "videos" / "inbox"
    tag = tmp_path / "videos" / "sorted" / "旅行"
    inbox.mkdir(parents=True)
    tag.mkdir(parents=True)
    assert not overlaps(inbox, tag)


def test_overlap_message_explains_direction(tmp_path: Path) -> None:
    parent = tmp_path / "b"
    child = parent / "c"
    child.mkdir(parents=True)
    assert "是同一个目录" in overlap_message(parent, parent, "源文件夹")
    assert "这个目录在源文件夹" in overlap_message(child, parent, "源文件夹")
    assert "在这个目录里面" in overlap_message(parent, child, "源文件夹")
