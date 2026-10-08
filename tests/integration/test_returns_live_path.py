"""Returns agent: the live-model path and its configuration, without calling Google.

Found by running the agent live on the real Round 2 dataset (returns_input_50.csv):
  * the Pod's LOG_LEVEL values (INFO / WARNING, set by .env.example and `make run`) crashed Round 2's Settings;
  * live / record mode built the Gemini client with the wrong arguments, so it raised TypeError every time;
  * a fail-open record after real model requests said `calls: 0`.
"""
from __future__ import annotations

import pytest

returns_app = pytest.importorskip("agents.returns.app")
from agents.returns.adapter.runtime import create_model_client  # noqa: E402
from shared.utils.hashing import verify  # noqa: E402
from shared.utils.schema import errors as schema_errors  # noqa: E402

REQUEST = {"schema_version": "1.0", "request_id": "WF-org_demo_alpha-UNIT-0016:returns", "workflow_id": "WF-org_demo_alpha-UNIT-0016",
           "stage": "returns", "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-0016", "route": "mfn"}, "inputs": [],
           "previous_evidence": [], "context": {"overrides": [], "case": {}}}


@pytest.mark.parametrize("level", ["INFO", "WARNING", "DEBUG", "info", "nonsense"])
def test_pod_log_levels_do_not_crash_returns(monkeypatch, level):
    monkeypatch.setenv("LOG_LEVEL", level)
    monkeypatch.setenv("RETURNS_MODEL_MODE", "replay")
    out = returns_app.handle(REQUEST)
    assert out["evidence"]["status"] == "completed"


def test_live_client_is_constructed(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    client, cassette = create_model_client("live", "org_demo_alpha", "UNIT-0016", returns_app._round2_settings(), tmp_path)
    assert client is not None and cassette is None


def test_live_model_override_never_touches_replay(monkeypatch):
    # A global model override made every replay fail (schema_error): cassettes are tied to the model they recorded.
    monkeypatch.setenv("RETURNS_LIVE_MODEL", "gemini-test-model")
    assert returns_app._round2_settings("live").rm_judgment_model == "gemini-test-model"
    assert returns_app._round2_settings("replay").rm_judgment_model != "gemini-test-model"
    monkeypatch.setenv("RETURNS_MODEL_MODE", "replay")
    assert returns_app.handle(REQUEST)["evidence"]["status"] == "completed"


def test_failed_live_requests_are_counted_in_the_pending_record(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("RETURNS_MODEL_MODE", "live")

    async def fake_pipeline(*args, quota, **kwargs):
        quota.requests_sent += 2  # two real requests went out, then the provider failed
        raise RuntimeError("provider 503")

    monkeypatch.setattr(returns_app, "process_returned_row", fake_pipeline)
    out = returns_app.handle(REQUEST)
    ev = out["evidence"]
    assert ev["status"] != "completed" and ev["decision"]["verdict"] == "UNCERTAIN"
    assert ev["model"]["calls"] == 2 and ev["model"]["provider"] == "google"
    assert verify(ev) and not schema_errors("agent-output", out)
