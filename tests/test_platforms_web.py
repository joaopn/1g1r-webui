from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r.library import LibraryStore
from g1r.web.app import create_app, suggest_label


@pytest.fixture
def setup(make_settings, roms_root):
    (roms_root / "NES Set (No-Intro)").mkdir()
    (roms_root / "gb").mkdir()
    settings = make_settings()
    with TestClient(create_app(settings)) as client:
        yield client, LibraryStore(settings)


def add(client, **form):
    data = {"platform": "nes", "mount": "roms", "path": "NES Set (No-Intro)", "label": ""} | form
    return client.post("/platforms", data=data)


def test_suggest_label():
    assert suggest_label("roms/NES Set (No-Intro)") == "nes-set-no-intro"


def test_add_platform_dialog_lists_only_enabled_platforms(setup):
    client, _ = setup
    html = client.get("/platforms/new").text
    assert "one platform only" in html
    assert 'value="nes"' in html and 'value="psx"' not in html
    assert "NES Set (No-Intro)" in html


def test_browse_lists_subfolders(setup):
    client, _ = setup
    html = client.get("/browse", params={"mount": "roms", "path": ""}).text
    assert "gb" in html and "NES Set (No-Intro)" in html


def test_add_platform_saves_and_redirects(setup):
    client, store = setup
    response = add(client)
    assert response.status_code == HTTPStatus.NO_CONTENT
    assert response.headers["HX-Redirect"] == "/section/matching/nes-set-no-intro"
    folder = store.load().folder("nes-set-no-intro")
    assert (folder.platform, folder.mount, folder.path) == ("nes", "roms", "NES Set (No-Intro)")
    page = client.get("/section/matching/nes-set-no-intro").text
    assert "Nintendo Entertainment System" in page
    assert "discarded/nes-set-no-intro/" in page
    for section in ("conversion", "matching", "discarded"):
        assert f'href="/section/{section}/nes-set-no-intro"' in page


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({"platform": "psx"}, "Choose a platform"),
        ({"path": ""}, "not the mount itself"),
        ({"path": "../x"}, "may not contain"),
        ({"label": "Bad Label"}, "lowercase"),
        ({"path": "missing"}, "does not exist"),
    ],
)
def test_add_platform_errors_rerender_the_dialog(setup, form, message):
    client, store = setup
    response = add(client, **form)
    assert response.status_code == HTTPStatus.OK
    assert message in response.text
    assert store.load().folders == []


def test_duplicate_label_and_folder_rejected(setup):
    client, store = setup
    add(client, label="nes")
    assert "already used" in add(client, path="gb", label="nes", platform="gb").text
    assert "already added" in add(client, label="nes2").text
    assert len(store.load().folders) == 1


def test_remove_folder_keeps_files(setup, roms_root):
    client, store = setup
    add(client, label="nes")
    client.post("/folders/nes/remove")
    assert store.load().folders == []
    assert (roms_root / "NES Set (No-Intro)").is_dir()


def test_unknown_folder_page_is_404(setup):
    client, _ = setup
    assert client.get("/section/matching/nope").status_code == HTTPStatus.NOT_FOUND


def test_settings_targets_and_ignored_are_saved(setup):
    client, store = setup
    page = client.get("/settings").text
    assert 'name="target-nes"' in page and "metadata.txt" in page
    client.post("/settings/targets", data={"target-nes": "plain", "target-gb": "bogus"})
    client.post("/settings/ignored", data={"ignored": "foo.txt\n\n  *.bak \n"})
    library = store.load()
    assert library.platform_targets == {"nes": "plain"}
    assert library.ignored_filenames == ["foo.txt", "*.bak"]
