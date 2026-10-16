import pytest
import yaml

from g1r.config import DATA_DIR_ENV, deep_merge, load_settings


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
def make_settings(data_dir, roms_root, extra_root):
    """Settings with data and ROM mounts in a temp dir, plus an optional config.yaml override."""

    def _make(override=None):
        data_dir.mkdir(parents=True, exist_ok=True)
        paths = {"roms_root": str(roms_root), "extra_mounts_root": str(extra_root)}
        merged = deep_merge({"paths": paths}, override or {})
        (data_dir / "config.yaml").write_text(yaml.safe_dump(merged), encoding="utf-8")
        return load_settings({DATA_DIR_ENV: str(data_dir)})

    return _make
