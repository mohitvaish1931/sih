"""
Test harness: isolated SQLite database, demo scenarios seeded once, and every
outbound HTTP call blocked so the suite is deterministic and runs offline.
"""

import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sifra-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp, 'test.db')}"   # never the real DB from .env
os.environ["SUPABASE_DB_URL"] = os.environ["DATABASE_URL"]
os.environ["ML_LIVE_REFERENCE"] = "false"
os.environ["AUTO_SEED_DEMO"] = "false"
os.environ["LLM_ENABLED"] = "false"
os.environ["GEOIP_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
import requests  # noqa: E402


class _Offline(requests.exceptions.ConnectionError):
    pass


def _blocked(*args, **kwargs):
    raise _Offline("network disabled in tests")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", _blocked)
    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    yield


@pytest.fixture(scope="session")
def seeded():
    import seed_data
    orig = requests.Session.request
    requests.Session.request = _blocked
    try:
        seed_data.seed_database()
    finally:
        requests.Session.request = orig
    return True


@pytest.fixture(scope="session")
def client(seeded):
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


@pytest.fixture()
def db(seeded):
    from app.database import SessionLocal
    s = SessionLocal()
    yield s
    s.close()
