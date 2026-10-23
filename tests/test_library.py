import pytest

from g1r.library import FolderEntry, Library, LibraryError, LibraryStore


def test_missing_library_is_empty(make_settings):
    assert LibraryStore(make_settings()).load() == Library()


def test_round_trip_and_header(make_settings):
    store = LibraryStore(make_settings())
    store.update(
        lambda lib: lib.folders.append(
            FolderEntry(label="nes", platform="nes", mount="roms", path="nes")
        )
    )
    text = store.path.read_text(encoding="utf-8")
    assert text.startswith("# Written by 1g1r-webui")
    assert store.load().folder("nes").path == "nes"
    assert not list(store.path.parent.glob(".library-*"))


def test_invalid_library_is_reported(make_settings):
    store = LibraryStore(make_settings())
    store.path.write_text("folders: [{label: x}]\n", encoding="utf-8")
    with pytest.raises(LibraryError):
        store.load()


def test_target_falls_back_to_default(make_settings):
    store = LibraryStore(make_settings())
    lib = Library(platform_targets={"nes": "plain", "gb": "nonsense"})
    assert store.target_for(lib, "nes") == "plain"
    assert store.target_for(lib, "gb") == "zip"


def test_ignored_patterns_default_until_edited(make_settings):
    settings = make_settings()
    store = LibraryStore(settings)
    folder = FolderEntry(label="nes", platform="nes", mount="roms", path="nes")
    assert store.ignored_patterns(folder) == settings.ignored_filenames
    folder.ignored_patterns = []
    assert store.ignored_patterns(folder) == []


def test_one_shared_ignore_list_becomes_each_folders_own(make_settings):
    store = LibraryStore(make_settings())
    store.path.write_text(
        "ignored_filenames: ['*.bak']\n"
        "folders:\n"
        "- {label: a, platform: nes, mount: roms, path: a}\n"
        "- {label: b, platform: nes, mount: roms, path: b, ignored_patterns: ['*.txt']}\n",
        encoding="utf-8",
    )
    library = store.load()
    assert library.folder("a").ignored_patterns == ["*.bak"]
    assert library.folder("b").ignored_patterns == ["*.txt"]
    store.save(library)
    assert "ignored_filenames" not in store.path.read_text(encoding="utf-8")
