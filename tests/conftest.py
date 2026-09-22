"""No test reaches the network: the site audit's one fetch function refuses unless a test records one."""
import pytest

import audit


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(url, accept=None):
        raise OSError(f"no network in tests: {url}")
    monkeypatch.setattr(audit, "get", refuse)
