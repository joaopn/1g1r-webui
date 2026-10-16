from pathlib import Path

import pytest

from g1r.dats import DatError, parse_dat, parse_dat_bytes

DATA = Path(__file__).parent / "data"


def test_logiqx_with_parent_clone():
    dat = parse_dat(DATA / "nes-nointro.dat")
    assert dat.format == "logiqx"
    assert dat.header.name == "Nintendo - Nintendo Entertainment System (Headered)"
    assert dat.header.version == "20261015-000000"
    assert [g.name for g in dat.games] == ["Tetris (USA)", "Tetris (Japan)"]
    assert dat.games[1].cloneofid == "0002" and dat.has_parent_clone
    assert dat.games[0].roms[0].crc == "1394f57e" and dat.games[0].roms[0].size == 49168


def test_clrmamepro_without_parent_clone():
    dat = parse_dat(DATA / "nes-libretro.dat")
    assert dat.format == "clrmamepro"
    assert dat.header.version == "2026.10.07"
    assert not dat.has_parent_clone
    assert dat.games[0].roms[0].crc == "1394f57e"
    assert dat.games[1].name == 'Name \\"quoted\\" (USA)'


@pytest.mark.parametrize(
    "data",
    [b"hello", b"<other/>", b"<datafile><game/></datafile>", b"clrmamepro ( name x", b"<datafile"],
)
def test_bad_dats_are_rejected(data):
    with pytest.raises(DatError):
        parse_dat_bytes(data)


def test_bom_and_whitespace_are_tolerated():
    data = b"\xef\xbb\xbf\n" + (DATA / "nes-nointro.dat").read_bytes()
    assert parse_dat_bytes(data).header.name.startswith("Nintendo")
