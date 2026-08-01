import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def tmp_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME so nothing touches the real ~/.hermes."""
    home = tmp_path / "hermes-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


@pytest.fixture()
def conn(tmp_home):
    import yti_store
    c = yti_store.connect()
    yield c
    c.close()
