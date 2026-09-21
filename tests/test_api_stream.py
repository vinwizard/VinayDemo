"""Stream endpoint checks. No HTTP client: run_events is a plain generator, so it is called directly.

The one rule worth pinning here is that a setup failure is visible to the browser without its
detail, because that detail can carry the API key.
"""
import api.main as main


def test_setup_failure_is_streamed_without_the_exception_detail(monkeypatch):
    def boom(mode, scenario=None, company_id=None):
        raise RuntimeError("boom: sk-secret")

    monkeypatch.setattr(main, "build_provider", boom)
    chunks = list(main.run_events("A", "live"))

    assert len(chunks) == 1
    assert chunks[0].startswith("event: error")
    assert "RuntimeError" in chunks[0]
    assert "sk-secret" not in chunks[0]
    assert "boom" not in chunks[0]
