from dataclasses import replace

import pytest

from g1r import matching
from g1r.config import RankingConfig
from g1r.dats import Dat, DatGame, DatHeader, DatRom
from g1r.grouping import (
    SOURCE_DAT,
    SOURCE_NAME,
    SOURCE_RETOOL,
    SOURCE_SINGLE,
    DatSet,
    Group,
    SourceDat,
    build_groups,
)
from g1r.names import parse_name
from g1r.ranking import decide


@pytest.fixture
def settings(make_settings, tmp_path):
    from pathlib import Path

    clonelists = Path(__file__).parent / "data" / "clonelists"
    return make_settings({"grouping": {"retool_clonelists_dir": str(clonelists)}})


def dat(*names, parents=None):
    parents = parents or {}
    games = [DatGame(name=n, id=str(i), cloneofid=None) for i, n in enumerate(names)]
    ids = {g.name: g.id for g in games}
    for game in games:
        if game.name in parents:
            game.cloneofid = ids[parents[game.name]]
    return Dat(DatHeader(name="Nintendo - Nintendo Entertainment System"), games, "logiqx")


def groups_of(settings, d, names):
    return {
        g.name: g
        for g in build_groups(settings, d, [(n + ".zip", n, "dat-checksum") for n in names])
    }


def ranking(**kw):
    base = {
        "criteria": ["prerelease", "region"],
        "regions": ["World", "USA", "Europe", "Japan"],
        "languages": ["En"],
        "multi_region": "best",
    }
    return RankingConfig(**(base | kw))


def test_parse_name_regions_languages_revision(settings):
    p = parse_name("Yie Ar Kung-Fu (Japan) (En) (Rev 1.4)", settings.names)
    assert (p.title, p.regions, p.languages, p.revision) == (
        "Yie Ar Kung-Fu",
        ("Japan",),
        ("En",),
        "Rev 1.4",
    )
    assert parse_name("Game (USA) (Beta 2)", settings.names).prerelease
    assert parse_name("Game (USA) (Virtual Console)", settings.names).rerelease


def test_dat_parent_clone_wins(settings):
    d = dat("Tetris (USA)", "Tetris (Japan)", parents={"Tetris (Japan)": "Tetris (USA)"})
    g = groups_of(settings, d, ["Tetris (USA)", "Tetris (Japan)"])
    assert g["Tetris (USA)"].source == SOURCE_DAT and len(g["Tetris (USA)"].versions) == 2


def test_retool_joins_different_titles(settings):
    names = ["Mother (Japan)", "EarthBound Beginnings (USA, Europe) (Virtual Console)"]
    g = groups_of(settings, dat(*names), names)
    assert g["Mother"].source == SOURCE_RETOOL and len(g["Mother"].versions) == 2


def test_name_grouping_keeps_publishers_and_variants_apart(settings):
    names = [
        "Klax (Japan) (Hudson Soft)",
        "Klax (USA) (Mindscape)",
        "Tetris (Bulletproof) (Japan)",
        "Tetris (USA)",
        "Space Invaders (Japan)",
        "Space Invaders (USA) (SGB Enhanced)",
        "Contra (USA)",
        "Contra (Japan) (Rev 1)",
        "Contra (USA) (Beta)",
    ]
    g = groups_of(settings, dat(*names), names)
    assert "Klax (Hudson Soft)" in g and "Klax (Mindscape)" in g
    assert "Tetris (Bulletproof)" in g and len(g["Tetris"].versions) == 1
    assert g["Space Invaders"].source == SOURCE_NAME and len(g["Space Invaders"].versions) == 2
    assert len(g["Contra"].versions) == 3


def test_name_grouping_can_be_switched_off(make_settings):
    settings = make_settings({"grouping": {"infer_from_dat_names": False}})
    names = ["Contra (USA)", "Contra (Japan)"]
    assert len(build_groups(settings, dat(*names), [(n, n, "m") for n in names])) == 2


def decide_names(settings, names, **kw):
    group = build_groups(settings, dat(*names), [(n, n, "m") for n in names])[0]
    return decide(group, ranking(**kw))


def test_region_decides_and_multi_region_counts_best(settings):
    d = decide_names(settings, ["Contra (Japan)", "Contra (Europe)", "Contra (Japan, USA)"])
    assert d.winner.game_name == "Contra (Japan, USA)" and d.reason == "region priority"
    d = decide_names(settings, ["Contra (Japan, USA)", "Contra (Europe)"], multi_region="first")
    assert d.winner.game_name == "Contra (Europe)"


def test_prerelease_loses(settings):
    d = decide_names(settings, ["Contra (World) (Beta)", "Contra (Japan)"])
    assert d.winner.game_name == "Contra (Japan)"


def test_same_region_revisions_are_undecided_by_default(settings):
    d = decide_names(settings, ["Contra (USA)", "Contra (USA) (Rev 1)"])
    assert d.winner is None and len(d.candidates) == 2 and "do not separate" in d.reason
    d = decide_names(
        settings,
        ["Contra (USA)", "Contra (USA) (Rev 1)"],
        criteria=["prerelease", "region", "revision"],
    )
    assert d.winner.game_name == "Contra (USA) (Rev 1)"


def test_original_over_rerelease_only_when_enabled(settings):
    names = ["Contra (Japan)", "Contra (USA) (Virtual Console)"]
    assert decide_names(settings, names).winner.game_name == "Contra (USA) (Virtual Console)"
    d = decide_names(settings, names, criteria=["original", "region"])
    assert d.winner.game_name == "Contra (Japan)"


def test_no_alphabetical_tiebreak(settings):
    d = decide_names(
        settings, ["Contra (Unknown) (Alt 1)", "Contra (Unknown) (Alt 2)"], criteria=[]
    )
    assert d.winner is None and "do not separate" in d.reason


def test_ranking_config_validation():
    with pytest.raises(ValueError):
        ranking(criteria=["region", "region"])
    with pytest.raises(ValueError):
        ranking(criteria=["alphabetical"])


def test_retool_short_names_keep_distinguishing_tags(settings):
    # Regression: Bullet-Proof Tetris was grouped with Nintendo's Tetris because the
    # bare title was looked up in Retool's list.
    names = [
        "Tetris (USA)",
        "Tetris (Japan) (En) (Rev 2) (Bullet-Proof)",
        "Tetris (USA) (Tengen)",
        "Super Tetris II (Japan)",
    ]
    g = groups_of(settings, dat(*names), names)
    assert [v.game_name for v in g["Tetris"].versions] == ["Tetris (USA)"]
    assert g["Tetris - Tengen"].source == SOURCE_RETOOL and len(g["Tetris - Tengen"].versions) == 2
    assert "Tetris (Bullet-Proof)" in g and g["Tetris (Bullet-Proof)"].source == SOURCE_SINGLE


def test_retool_full_names(settings):
    names = ["Odd Name (Japan) (Special)", "Odd Name (USA)"]
    g = groups_of(settings, dat(*names), names)
    assert len(g["Exact"].versions) == 2


def amiga(roms_per_game: dict[str, int], name="Commodore - Amiga") -> Dat:
    games = [
        DatGame(name=n, roms=[DatRom(f"{n} (Disk {i}).ipf", 1, None, None, None) for i in range(k)])
        for n, k in roms_per_game.items()
    ]
    return Dat(DatHeader(name=name), games, "logiqx")


def test_names_from_several_dats_join_and_a_partial_version_is_marked(settings):
    full = SourceDat("full", amiga({"Batman (Europe)": 3, "Cadaver (Europe)": 2}))
    partial = SourceDat("partial", amiga({"Batman (Europe)": 1, "Zool (Europe)": 1}))
    tosec = SourceDat("tosec", amiga({"Batman - The Movie (1989)(Ocean)": 3}), "tosec")
    groups = {
        g.name: g
        for g in build_groups(
            settings,
            DatSet([full, partial, tosec]),
            [
                ("Batman (Europe).zip", "Batman (Europe)", "dat-checksum", "full"),
                ("Batman (Europe) (Disk 2).ipf", "Batman (Europe)", "dat-checksum", "partial"),
                ("Zool (Europe).ipf", "Zool (Europe)", "dat-checksum", "partial"),
                ("Batman tosec.zip", "Batman - The Movie (1989)(Ocean)", "dat-checksum", "tosec"),
            ],
        )
    }
    batman = groups["Batman"]
    assert {v.rel_path: v.incomplete for v in batman.versions} == {
        "Batman (Europe).zip": False,
        "Batman (Europe) (Disk 2).ipf": True,
    }
    # A name only one DAT lists is whole by its DAT; TOSEC's never joins No-Intro's by text.
    assert not groups["Zool"].versions[0].incomplete
    movie = groups["Batman - The Movie (1989) (Ocean)"]
    assert batman.key == "name:Batman" and movie.key.startswith("name:tosec:")


def test_a_partial_version_is_never_kept_over_a_whole_one(settings):
    full = SourceDat("full", amiga({"Batman (Europe)": 3}))
    partial = SourceDat("partial", amiga({"Batman (Europe)": 1}))
    identities = [
        ("Batman (Europe).zip", "Batman (Europe)", "dat-checksum", "full"),
        ("Batman (Europe) (Disk 2).ipf", "Batman (Europe)", "dat-checksum", "partial"),
    ]
    (group,) = build_groups(settings, DatSet([full, partial]), identities)
    status, _, winner, _ = matching._decide(group, ranking(), {}, set(), group)
    assert status == matching.STATUS_DECIDED and winner.rel_path == "Batman (Europe).zip"
    only_partial = Group(group.key, group.name, group.source, group.versions[1:] * 2)
    only_partial.versions[1] = replace(only_partial.versions[1], rel_path="copy.ipf")
    status, _, winner, candidates = matching._decide(
        only_partial, ranking(), {}, set(), only_partial
    )
    assert status == matching.STATUS_UNDECIDED and winner is None and len(candidates) == 2


def test_one_disk_named_online_is_never_kept_over_the_whole_game(settings):
    """B3: Hasheous names a lone disk as the game its DAT lists with every disk."""
    full = SourceDat(
        "full",
        Dat(
            DatHeader(name="Commodore - Amiga"),
            [
                DatGame(
                    name="Game (Europe)",
                    roms=[DatRom(f"d{i}", 1, None, None, None) for i in (1, 2)],
                ),
                DatGame(
                    name="Game (USA)",
                    cloneof="Game (Europe)",
                    roms=[DatRom(f"u{i}", 1, None, None, None) for i in (1, 2)],
                ),
            ],
            "logiqx",
        ),
    )
    identities = [
        ("Game (Europe).zip", "Game (Europe)", "dat-checksum", "full"),
        ("Game (USA) (Disk 2).ipf", "Game (USA)", "hasheous", ""),
    ]
    (group,) = build_groups(settings, DatSet([full]), identities)
    assert {v.rel_path: v.incomplete for v in group.versions} == {
        "Game (Europe).zip": False,
        "Game (USA) (Disk 2).ipf": True,
    }
    # USA ranks above Europe, but the USA version is one disk: the whole game is kept.
    status, _, winner, _ = matching._decide(group, ranking(), {}, set(), group)
    assert status == matching.STATUS_DECIDED and winner.rel_path == "Game (Europe).zip"


def test_single_file_methods_are_the_scanners():
    from g1r import grouping, scanner

    assert grouping.SINGLE_FILE_METHODS == {scanner.METHOD_HASHEOUS, scanner.METHOD_FUZZY}
