"""No test reaches the network for real demand: the one fetch line refuses, and harvests cache in a temp dir."""
import pytest

import demand


@pytest.fixture(autouse=True)
def no_demand_network(tmp_path, monkeypatch):
    def refuse(url):
        raise ConnectionError("no network in tests")
    monkeypatch.setattr(demand, "_fetch_json", refuse)
    monkeypatch.setattr(demand, "_cache", lambda category, real=demand._cache: tmp_path / "demand" / real(category).name)
