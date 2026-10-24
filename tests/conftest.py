from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r.config import DATA_DIR_ENV, deep_merge, load_settings
from g1r.web.app import create_app


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def roms_root(tmp_path):
    root = tmp_path / "roms"
    root.mkdir()
    return root


@pytest.fixture
def extra_root(tmp_path):
    root = tmp_path / "mnt"
    root.mkdir()
    return root


@pytest.fixture
def keys_root(data_dir):
    """Where uploaded console keys are kept (in the data directory); empty in tests."""
    root = data_dir / "keys"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def make_settings(data_dir, roms_root, extra_root, tmp_path):
    """Settings with data and ROM mounts in a temp dir, plus optional overrides. No clone
    lists unless a test gives its own: the image's real ones would join test games."""

    def _make(override=None):
        data_dir.mkdir(parents=True, exist_ok=True)
        paths = {"roms_root": str(roms_root), "extra_mounts_root": str(extra_root)}
        grouping = {"retool_clonelists_dir": str(tmp_path / "no-clonelists")}
        merged = deep_merge({"paths": paths, "grouping": grouping}, override or {})
        return load_settings({DATA_DIR_ENV: str(data_dir)}, merged)

    return _make


@pytest.fixture
def folder_of(make_settings, roms_root):
    """A started app with one folder of the given platform (label = platform)."""
    (roms_root / "discarded").mkdir()
    clients = []

    def make(platform: str):
        folder = roms_root / platform
        folder.mkdir()
        client = TestClient(create_app(make_settings(), report_runner=lambda *a, **_: []))
        client.__enter__()
        clients.append(client)
        body = {"platform": platform, "mount": "roms", "path": platform, "label": platform}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        return client, folder

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def n3ds(make_settings, roms_root):
    folder = roms_root / "3ds"
    folder.mkdir()
    (roms_root / "discarded").mkdir()
    with TestClient(create_app(make_settings(), report_runner=lambda *a, **_: [])) as client:
        body = {"platform": "3ds", "mount": "roms", "path": "3ds", "label": "3ds"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        yield client, folder
