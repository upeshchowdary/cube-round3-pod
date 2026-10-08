"""Parity with the Round 2 Pack Manager (nikhilagarwal03 branch: engine.ts, openrouter.ts, verify/route.ts).

Found by comparing the Python port with the TypeScript original:
  * engine.ts treats any occlusion status other than "clear" as uncertain; the port only checked partial/severe;
  * a non-OK vision response throws and fails open in Round 2; the port fell through to the CSV replay;
  * the port's vision prompt had lost the closing instruction of the original.
"""
from __future__ import annotations

import httpx
import pytest

from agents.pack.adapter import vision
from agents.pack.adapter.engine import reconcile_pack

ORDER = [{"sku": "SKU-A", "quantity": 1}]
SEEN = [{"sku": "SKU-A", "quantity": 1}]


@pytest.mark.parametrize("occlusion", [{"status": "heavy"}, {"status": "unknown"}, {}, None])
def test_anything_but_clear_occlusion_is_uncertain(occlusion):
    extracted = {"observations": SEEN, "decoys": [], "status": "complete", "reason": ""}
    if occlusion is not None:
        extracted["occlusion"] = occlusion
    assert reconcile_pack(ORDER, extracted)["verdict"] == "UNCERTAIN"


def test_clear_occlusion_with_matching_contents_seals():
    extracted = {"observations": SEEN, "decoys": [], "occlusion": {"status": "clear"}, "status": "complete", "reason": ""}
    assert reconcile_pack(ORDER, extracted)["verdict"] == "SEAL"


@pytest.mark.parametrize("status_code", [401, 429, 500])
def test_vision_http_error_fails_open_instead_of_using_csv(monkeypatch, status_code):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kwargs):
            return httpx.Response(status_code, text="provider error", request=httpx.Request("POST", url))

    monkeypatch.setattr(vision.httpx, "Client", FakeClient)
    out = vision.extract_pack_vision(image_url="https://example.invalid/box.jpg", expected_skus=["SKU-A"],
                                     fixture_id=None, sample_observed_text="SKU-A:1")
    assert out["status"] == "uncertain" and "VLM failure" in out["reason"]
    assert out["model"]["name"] != "csv-replay"  # never silently replaced by the operator's CSV answer


def test_prompt_keeps_the_original_closing_instruction():
    assert "do not produce a SEAL or STOP_AND_FIX" in vision.PACK_VISION_SYSTEM_PROMPT
