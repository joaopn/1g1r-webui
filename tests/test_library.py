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


def test_ignored_filenames_default_until_edited(make_settings):
    settings = make_settings()
    store = LibraryStore(settings)
    assert store.ignored_filenames(Library()) == settings.ignored_filenames
    assert store.ignored_filenames(Library(ignored_filenames=[])) == []
