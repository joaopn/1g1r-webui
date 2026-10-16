import pytest

from g1r import mounts
from g1r.library import FolderEntry


@pytest.fixture
def settings(make_settings, roms_root, extra_root):
    (roms_root / "nes" / "sub").mkdir(parents=True)
    (roms_root / "gb").mkdir()
    (roms_root / ".hidden").mkdir()
    (roms_root / "discarded" / "nes").mkdir(parents=True)
    (extra_root / "disk2" / "snes").mkdir(parents=True)
    return make_settings()


def test_mounts_list_main_and_extra(settings, roms_root):
    assert [(m.id, m.root) for m in mounts.list_mounts(settings)][0] == ("roms", roms_root)
    assert [m.id for m in mounts.list_mounts(settings)] == ["roms", "mnt/disk2"]


def test_subdirectories_hide_discarded_and_hidden(settings):
    assert mounts.subdirectories(settings, "roms", "") == ["gb", "nes"]


@pytest.mark.parametrize("bad", ["../etc", "nes/../../x"])
def test_parent_traversal_refused(settings, bad):
    with pytest.raises(mounts.FolderPathError):
        mounts.resolve(settings, "roms", bad)


def test_symlink_escape_refused(settings, roms_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (roms_root / "link").symlink_to(outside)
    with pytest.raises(mounts.FolderPathError, match="outside"):
        mounts.resolve(settings, "roms", "link")


def test_check_new_folder_rules(settings):
    assert mounts.check_new_folder(settings, "roms", "nes", []).name == "nes"
    assert mounts.check_new_folder(settings, "mnt/disk2", "", []).name == "disk2"
    with pytest.raises(mounts.FolderPathError, match="not the mount itself"):
        mounts.check_new_folder(settings, "roms", "", [])
    with pytest.raises(mounts.FolderPathError, match="discarded"):
        mounts.check_new_folder(settings, "roms", "discarded/nes", [])
    with pytest.raises(mounts.FolderPathError, match="does not exist"):
        mounts.check_new_folder(settings, "roms", "psx", [])
    existing = [FolderEntry(label="nes", platform="nes", mount="roms", path="nes")]
    with pytest.raises(mounts.FolderPathError, match="already added"):
        mounts.check_new_folder(settings, "roms", "nes", existing)
    with pytest.raises(mounts.FolderPathError, match="nested"):
        mounts.check_new_folder(settings, "roms", "nes/sub", existing)


def test_unknown_mount(settings):
    with pytest.raises(mounts.FolderPathError, match="unknown mount"):
        mounts.resolve(settings, "mnt/nope", "")
