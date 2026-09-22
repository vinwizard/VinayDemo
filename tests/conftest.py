"""No test reaches the network: the site audit's and real demand's one fetch functions refuse,
unless a test records responses; demand harvests cache in a temp dir."""
import pytest

import audit
import demand


@pytest.fixture(autouse=True)
def no_network(tmp_path, monkeypatch):
    def refuse(url, accept=None):
        raise OSError(f"no network in tests: {url}")
    monkeypatch.setattr(audit, "get", refuse)

    def refuse_demand(url):
        raise ConnectionError("no network in tests")
    monkeypatch.setattr(demand, "_fetch_json", refuse_demand)
    monkeypatch.setattr(demand, "_cache", lambda category, real=demand._cache: tmp_path / "demand" / real(category).name)
