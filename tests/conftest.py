import pytest
import yaml

from g1r.config import DATA_DIR_ENV, load_settings


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def make_settings(data_dir):
    """Settings with the data directory in a temp dir and an optional config.yaml override."""

    def _make(override=None):
        data_dir.mkdir(parents=True, exist_ok=True)
        if override is not None:
            (data_dir / "config.yaml").write_text(yaml.safe_dump(override), encoding="utf-8")
        return load_settings({DATA_DIR_ENV: str(data_dir)})

    return _make
