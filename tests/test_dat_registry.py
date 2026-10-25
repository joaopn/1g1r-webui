import io
import zipfile
from pathlib import Path

import pytest

from g1r import db
from g1r.dat_registry import DatRegistry, RegistryError, header_matches, name_style
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
    active = store.load().dats["nes"].active["libretro"]
    assert (active.source, active.version) == ("libretro", "2026.10.07")
    assert (settings.paths.data_dir / active.file).read_bytes() == LIBRETRO
    assert registry.active_version(conn, store.load(), "nes")["id"] == version_id


def test_each_source_has_its_active_dat_and_the_order_puts_complete_dats_first(env):
    _, store, registry, conn, _ = env
    first = registry.download_libretro(conn, "nes")
    second = registry.add_upload(conn, "nes", NOINTRO, "nes.dat")
    library = store.load()
    assert [v["id"] for v in registry.active_versions(conn, library, "nes")] == [second, first]
    row = conn.execute("SELECT * FROM dat_version WHERE id = ?", (second,)).fetchone()
    assert row["source"] == "nointro" and row["has_parent_clone"] and row["matches_platform"]
    assert registry.load_active(conn, library, "nes").has_parent_clone
    assert registry.order(library, "nes") == ["nointro", "libretro", "hasheous"]


def test_a_newer_version_of_a_source_waits_for_a_click(env):
    _, store, registry, conn, _ = env
    first = registry.add_upload(conn, "nes", NOINTRO, "nes.dat")
    newer = registry.add_upload(conn, "nes", NOINTRO + b"<!-- v2 -->", "nes.dat")
    assert registry.active_version(conn, store.load(), "nes")["id"] == first
    registry.activate(conn, "nes", newer)
    assert registry.active_version(conn, store.load(), "nes")["id"] == newer


def test_a_source_added_after_the_order_was_chosen_takes_its_default_place(env):
    _, store, registry, conn, _ = env
    registry.download_libretro(conn, "nes")
    registry.set_order("nes", ["hasheous", "libretro"], [])
    registry.add_upload(conn, "nes", NOINTRO, "nes.dat")
    # No-Intro comes before libretro by default: it goes right before it, after the lookup
    # placed first.
    assert registry.order(store.load(), "nes") == ["hasheous", "nointro", "libretro"]
    registry.set_order("nes", ["libretro", "nointro", "hasheous"], ["libretro"])
    assert [v["source"] for v in registry.active_versions(conn, store.load(), "nes")] == ["nointro"]
    with pytest.raises(RegistryError):
        registry.set_order("nes", ["libretro", "libretro"], [])


def test_one_active_dat_from_before_the_order_still_loads(env):
    settings, store, registry, conn, _ = env
    version = registry.download_libretro(conn, "nes")
    row = conn.execute("SELECT * FROM dat_version WHERE id = ?", (version,)).fetchone()
    old = (
        "dats:\n  nes:\n"
        f"    source: libretro\n    file: {row['file']}\n    header_name: x\n"
        f"    sha1: {row['sha1']}\n    pinned: true\n"
    )
    settings.paths.library_path.write_text(old)
    active = store.load().dats["nes"].active["libretro"]
    assert active.pinned and registry.active_version(conn, store.load(), "nes")["id"] == version


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
    newer = registry.add_upload(conn, "nes", NOINTRO + b"<!-- v2 -->", "nes.dat")
    registry.set_pinned("nes", "nointro", True)
    with pytest.raises(RegistryError, match="pinned"):
        registry.activate(conn, "nes", newer)
    registry.activate(conn, "nes", other)
    registry.set_pinned("nes", "nointro", False)
    registry.activate(conn, "nes", newer)


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


NES_HEADER = b"Nintendo - Nintendo Entertainment System (Headered)"
WII_DEV_KIT = NOINTRO.replace(NES_HEADER, b"Nintendo - Wii (Development Kit Hard Drives)")


@pytest.mark.parametrize(
    ("platform", "name", "matches"),
    [
        ("wii", "Nintendo - Wii", True),
        ("n64", "Nintendo - Nintendo 64 (BigEndian)", True),
        ("nes", "Nintendo - Nintendo Entertainment System (Headered) (Parent-Clone)", True),
        ("amiga", "Commodore - Amiga (TOSEC)", True),
        # B7: a DAT-o-MATIC side set is not the platform's games.
        ("wii", "Nintendo - Wii (Development Kit Hard Drives)", False),
        ("wii", "Nintendo - Wii (Digital) (CDN)", False),
        ("3ds", "Nintendo - Nintendo 3DS (Digital) (CDN)", False),
        ("psx", "Sony - PlayStation (PS one Classics) (PSN)", False),
        ("gba", "Nintendo - Game Boy Advance (e-Reader)", False),
        ("wii", "Nintendo - Wii U", False),
        ("gb", "Nintendo - Game Boy Advance", False),
        # No-Intro's Non-Redump set of a disc platform, named its own way on DAT-o-MATIC.
        ("psx", "Non-Redump - Sony - PlayStation", True),
        ("ngc", "Non-Redump - Nintendo - Nintendo GameCube", True),
        ("ps2", "Non-Redump - Sony - PlayStation", False),
        ("nes", "Non-Redump - Nintendo - Nintendo Entertainment System", False),
        # PSP's digital-only releases are a side set of their own; the minis are not.
        ("psp", "Sony - PlayStation Portable (PSN)", True),
        ("psp", "Sony - PlayStation Portable (PSN) (Minis)", False),
    ],
)
def test_header_matches_only_format_variants(make_settings, platform, name, matches):
    settings = make_settings()
    assert header_matches(settings, settings.platforms.profiles[platform], name) is matches


def test_pack_skips_side_sets(env):
    _, store, registry, conn, _ = env
    pack = zip_of({"No-Intro/nes.dat": NOINTRO, "No-Intro/wii-devkit.dat": WII_DEV_KIT})
    results = {r.member: r for r in registry.add_pack(conn, pack)}
    assert results["wii-devkit.dat"].platform is None
    assert results["wii-devkit.dat"].message == "skipped: another Wii set, not its games"
    assert set(store.load().dats) == {"nes"}


def test_recheck_flags_a_side_set_stored_before(env):
    _, _, registry, conn, _ = env
    version = registry.add_upload(conn, "wii", WII_DEV_KIT, "wii.dat")
    conn.execute("UPDATE dat_version SET matches_platform = 1 WHERE id = ?", (version,))
    registry.recheck_names(conn)
    row = conn.execute("SELECT matches_platform FROM dat_version WHERE id = ?", (version,))
    assert row.fetchone()["matches_platform"] == 0


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
    # Amiga and C64: No-Intro from the mirror, or the TOSEC pack.
    assert registry.downloads("amiga") == ["libretro", "tosec"]
    assert registry.downloads("c64") == ["libretro", "tosec"]
    # The libretro mirror keeps a disc's data track only: archived sets would not match it.
    # Dreamcast also takes TOSEC (CDIs, prototypes, homebrew).
    assert registry.downloads("dc") == ["redump", "tosec"]
    assert registry.downloads("psx") == ["redump"]
    # No public Switch DAT: identified by title ID, and a DAT can still be uploaded.
    assert registry.downloads("switch") == []
    with pytest.raises(RegistryError):
        registry.download(env[3], "switch", "libretro")


@pytest.mark.parametrize(
    ("source", "header", "style"),
    [
        ("libretro", "Commodore - Amiga", "nointro"),
        ("tosec", "Commodore - Amiga (TOSEC)", "tosec"),
        # A single TOSEC DAT uploaded on its own.
        ("upload", "Commodore Amiga - Games - [ADF] (TOSEC-v2025-03-13)", "tosec"),
        ("nointro", "Nintendo - Game Boy", "nointro"),
    ],
)
def test_names_read_as_the_active_dat_writes_them(source, header, style):
    assert name_style({"source": source, "header_name": header}) == style
    assert name_style(None) == "nointro"


def test_platforms_follow_the_default_order_until_they_have_their_own(env):
    _, store, registry, conn, _ = env
    registry.download_libretro(conn, "nes")
    registry.add_upload(conn, "nes", NOINTRO, "nes.dat")
    assert registry.order(store.load(), "nes") == ["nointro", "libretro", "hasheous"]
    registry.set_order("nes", ["libretro", "hasheous", "nointro"], ["hasheous"])
    library = store.load()
    assert registry.order(library, "nes") == ["libretro", "hasheous", "nointro"]
    assert [e.id for e in registry.entries(conn, library, "nes") if not e.on] == ["hasheous"]
    registry.set_order("nes", None, [])
    library = store.load()
    assert registry.order(library, "nes") == ["nointro", "libretro", "hasheous"]
    assert all(e.on for e in registry.entries(conn, library, "nes"))


def test_a_source_off_everywhere_is_off_on_every_platform(env):
    _, store, registry, conn, _ = env
    registry.download_libretro(conn, "nes")
    registry.add_upload(conn, "nes", NOINTRO, "nes.dat")
    registry.set_order("nes", ["libretro", "nointro", "hasheous"], ["nointro"])
    registry.set_global_off(["libretro"])
    library = store.load()
    assert registry.globally_off(library, "libretro")
    assert [e.id for e in registry.entries(conn, library, "nes") if not e.on] == [
        "libretro",
        "nointro",
    ]
    registry.set_global_off([])
    assert [e.id for e in registry.entries(conn, store.load(), "nes") if not e.on] == ["nointro"]
    # Online lookups are switched in Settings, never for every platform here.
    with pytest.raises(RegistryError):
        registry.set_global_off(["hasheous"])


def test_a_saved_global_order_becomes_each_platforms_own(env):
    settings, store, registry, conn, _ = env
    registry.download_libretro(conn, "nes")
    registry.add_upload(conn, "nes", NOINTRO, "nes.dat")
    library = settings.paths.library_path.read_text()
    library += "dat_order: [libretro, hasheous, nointro]\ndat_off: [hasheous]\n"
    settings.paths.library_path.write_text(library)
    loaded = store.load()
    assert loaded.dats["nes"].order == ["libretro", "hasheous", "nointro"]
    assert loaded.dats["nes"].off == ["hasheous"]
    assert registry.order(loaded, "nes") == ["libretro", "hasheous", "nointro"]
    assert [e.id for e in registry.entries(conn, loaded, "nes") if not e.on] == ["hasheous"]


def test_a_library_from_when_screenscraper_was_a_lookup_still_loads(env):
    settings, store, registry, conn, _ = env
    registry.download_libretro(conn, "nes")
    library = settings.paths.library_path.read_text()
    library += (
        "lookups:\n  hasheous: true\n  screenscraper: true\n"
        "dat_order: [screenscraper, libretro, hasheous]\n"
    )
    settings.paths.library_path.write_text(library)
    loaded = store.load()
    assert loaded.lookups.hasheous is True
    assert registry.order(loaded, "nes") == ["libretro", "hasheous"]


REDUMP_PSX = NOINTRO.replace(NES_HEADER, b"Sony - PlayStation")
NONREDUMP_PSX = NOINTRO.replace(NES_HEADER, b"Non-Redump - Sony - PlayStation")


def test_a_non_redump_upload_is_its_own_source_after_redump(env):
    _, store, registry, conn, _ = env
    redump = registry.add(
        conn, "psx", REDUMP_PSX, source="redump", origin=None, original_name="psx.dat"
    )
    other = registry.add_upload(conn, "psx", NONREDUMP_PSX, "psx-nonredump.dat")
    row = conn.execute("SELECT * FROM dat_version WHERE id = ?", (other,)).fetchone()
    assert row["source"] == "nonredump" and row["matches_platform"]
    library = store.load()
    assert registry.order(library, "psx") == ["redump", "nonredump", "hasheous"]
    # Both DATs' names are there to match files to by hand.
    assert [v["id"] for v, _ in registry.load_all(conn, library, "psx")] == [redump, other]


def test_the_daily_pack_adds_a_non_redump_set_to_its_platform(env):
    _, store, registry, conn, _ = env
    pack = zip_of({"No-Intro/psx.dat": NONREDUMP_PSX})
    results = registry.add_pack(conn, pack)
    assert [(r.platform, r.message) for r in results] == [("psx", "added")]
    assert set(store.load().dats["psx"].active) == {"nonredump"}


def test_non_redump_pages_are_offered_only_where_the_set_exists(env):
    _, _, registry, _, _ = env
    assert registry.pages("psx") == [
        ("nonredump", "https://datomatic.no-intro.org/index.php?page=download&op=dat&s=168")
    ]
    assert registry.pages("nes") == []
    assert registry.pages("neo-geo-cd") == []


PSN_PSP = NOINTRO.replace(NES_HEADER, b"Sony - PlayStation Portable (PSN)")


def test_psp_downloads_its_psn_set_from_the_mirror_as_a_source_of_its_own(make_settings):
    settings = make_settings()
    store = LibraryStore(settings)
    fetched = []

    def fetch(url):
        fetched.append(url)
        return PSN_PSP

    registry = DatRegistry(settings, store, fetch)
    conn = db.open_database(settings)
    assert "psn" in registry.downloads("psp")
    assert "psn" not in registry.downloads("psx")
    version = registry.download(conn, "psp", "psn")
    assert fetched == [
        "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/"
        "no-intro/Sony%20-%20PlayStation%20Portable%20%28PSN%29.dat"
    ]
    row = conn.execute("SELECT * FROM dat_version WHERE id = ?", (version,)).fetchone()
    assert row["source"] == "psn" and row["matches_platform"]
    assert row["original_name"] == "Sony - PlayStation Portable (PSN).dat"
    # An uploaded copy (DAT-o-MATIC's) goes to the same source, and so does the pack's.
    upload = registry.add_upload(
        conn, "psp", PSN_PSP.replace(b"</datafile>", b"<!-- v2 --></datafile>"), "psn.dat"
    )
    upload_row = conn.execute("SELECT source FROM dat_version WHERE id = ?", (upload,))
    assert upload_row.fetchone()["source"] == "psn"
    results = registry.add_pack(conn, zip_of({"No-Intro/psn.dat": PSN_PSP}))
    assert [(r.platform, r.message) for r in results] == [("psp", "added")]
    assert registry.order(store.load(), "psp") == ["psn", "hasheous"]
