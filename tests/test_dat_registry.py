import io
import zipfile
from pathlib import Path

import pytest

from g1r import db
from g1r.dat_registry import DatRegistry, RegistryError
from g1r.library import LibraryStore

DATA = Path(__file__).parent / "data"
NOINTRO = (DATA / "nes-nointro.dat").read_bytes()
LIBRETRO = (DATA / "nes-libretro.dat").read_bytes()


@pytest.fixture
def env(make_settings):
    settings = make_settings()
    store = LibraryStore(settings)
    fetched = []

    def fetch(url):
        fetched.append(url)
        return LIBRETRO

    conn = db.open_database(settings)
    return settings, store, DatRegistry(settings, store, fetch), conn, fetched


def zip_of(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_first_download_becomes_active(env):
    settings, store, registry, conn, fetched = env
    version_id = registry.download_libretro(conn, "nes")
    assert fetched == [
        "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/"
        "no-intro/Nintendo%20-%20Nintendo%20Entertainment%20System.dat"
    ]
    active = store.load().dats["nes"]
    assert (active.source, active.version) == ("libretro", "2026.10.07")
    assert (settings.paths.data_dir / active.file).read_bytes() == LIBRETRO
    assert registry.active_version(conn, store.load(), "nes")["id"] == version_id


def test_second_version_waits_for_a_click(env):
    _, store, registry, conn, _ = env
    first = registry.download_libretro(conn, "nes")
    second = registry.add_upload(conn, "nes", NOINTRO, "nes.dat")
    library = store.load()
    assert registry.active_version(conn, library, "nes")["id"] == first
    row = conn.execute("SELECT * FROM dat_version WHERE id = ?", (second,)).fetchone()
    assert row["source"] == "nointro" and row["has_parent_clone"] and row["matches_platform"]
    registry.activate(conn, "nes", second)
    assert store.load().dats["nes"].source == "nointro"
    assert registry.load_active(conn, store.load(), "nes").has_parent_clone


def test_same_file_is_stored_once(env):
    _, _, registry, conn, _ = env
    assert registry.add_upload(conn, "nes", NOINTRO, "a.dat") == registry.add_upload(
        conn, "nes", NOINTRO, "b.dat"
    )
    assert len(registry.versions(conn, "nes")) == 1


def test_pinned_dat_cannot_be_switched(env):
    _, _, registry, conn, _ = env
    registry.download_libretro(conn, "nes")
    other = registry.add_upload(conn, "nes", NOINTRO, "nes.dat")
    registry.set_pinned("nes", True)
    with pytest.raises(RegistryError, match="pinned"):
        registry.activate(conn, "nes", other)
    registry.set_pinned("nes", False)
    registry.activate(conn, "nes", other)


def test_pack_is_split_by_platform(env):
    _, store, registry, conn, _ = env
    gb = NOINTRO.replace(
        b"Nintendo - Nintendo Entertainment System (Headered)", b"Nintendo - Game Boy"
    )
    dc = NOINTRO.replace(
        b"Nintendo - Nintendo Entertainment System (Headered)", b"Sony - PlayStation Vita"
    )
    pack = zip_of(
        {
            "No-Intro/nes.dat": NOINTRO,
            "No-Intro/gb.dat": gb,
            "x/vita.dat": dc,
            "readme.txt": b"hi",
            "bad.dat": b"nonsense",
        }
    )
    results = {r.member: r for r in registry.add_pack(conn, pack)}
    assert results["nes.dat"].platform == "nes" and results["nes.dat"].version_id
    assert results["gb.dat"].platform == "gb"
    assert "not a supported platform" in results["vita.dat"].message
    assert "skipped" in results["bad.dat"].message
    assert set(store.load().dats) == {"nes", "gb"}


def test_rejections(env, make_settings):
    _, _, registry, conn, _ = env
    with pytest.raises(RegistryError, match="not a supported platform"):
        registry.add_upload(conn, "psvita", NOINTRO, "x.dat")
    with pytest.raises(RegistryError, match="not a usable DAT"):
        registry.add_upload(conn, "nes", b"junk", "x.dat")
    with pytest.raises(RegistryError, match="several DATs"):
        registry.add_upload(conn, "nes", zip_of({"a.dat": NOINTRO, "b.dat": LIBRETRO}), "x.zip")
    with pytest.raises(RegistryError, match="not a valid zip"):
        registry.add_pack(conn, b"junk")


def test_upload_limit(make_settings):
    settings = make_settings({"dats": {"max_upload_bytes": 10}})
    registry = DatRegistry(settings, LibraryStore(settings), lambda url: LIBRETRO)
    with pytest.raises(RegistryError, match="larger"):
        registry.add_upload(db.open_database(settings), "nes", NOINTRO, "x.dat")


def test_download_failure_is_reported(make_settings):
    settings = make_settings()

    def fail(url):
        raise OSError("network down")

    registry = DatRegistry(settings, LibraryStore(settings), fail)
    with pytest.raises(RegistryError, match="network down"):
        registry.download_libretro(db.open_database(settings), "nes")


def test_where_each_platform_downloads_from(env):
    _, _, registry, _, _ = env
    assert registry.downloads("nes") == ["libretro"]
    # The libretro mirror keeps a disc's data track only: archived sets would not match it.
    assert registry.downloads("dc") == ["redump"]
    assert registry.downloads("psx") == ["redump"]
    # No public Switch DAT: identified by title ID, and a DAT can still be uploaded.
    assert registry.downloads("switch") == []
    with pytest.raises(RegistryError):
        registry.download(env[3], "switch", "libretro")
