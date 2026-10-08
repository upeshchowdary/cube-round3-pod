"""Vision extractor for Pack Manager.

Wraps VLM calls (Llama-3.2-90B / Qwen-2.5-VL via Groq / OpenRouter) with:
1. Single batched call per unit (§5.2).
2. Fail-open timeout guard (6s limit, §5.3).
3. Cassette / replay support from Round 2 evaluation benchmarks (run_2.json).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_RESULTS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "run_2.json"

DEFAULT_MODEL_NAME = "meta-llama/llama-3.2-90b-vision-instruct"  # OpenRouter id (the Round 2 benchmark model)
# Groq does not serve Llama 3.2 Vision; this is its image-capable model. PACK_MODEL_NAME overrides either default.
GROQ_DEFAULT_MODEL_NAME = "qwen/qwen3.8-27b"
DEFAULT_PROVIDER = "openrouter"
VLM_TIMEOUT_S = 6.0

PACK_VISION_SYSTEM_PROMPT = """You are a cautious outbound packing verifier.

Inspect the supplied open-box image and return only a valid JSON object. Read visible
product text, SKU labels, barcodes, and packaging marks when they are legible. Count
every physically visible item, including identical items, without counting printed
images, product illustrations, labels, or reflections as physical products.

Assess occlusion before making a judgment. If an item is partly hidden, cropped,
blurred, too small, or otherwise not reliably countable, report it as uncertain and
explain the limitation. Never invent a SKU, quantity, or item that is not visible.

Expected SKUs and catalogue metadata are candidate references only. Do not make a
product match solely because a candidate SKU was supplied. If a visible item has a
different or unreadable SKU, report it as a decoy or unexpected item rather than
forcing it to match the closest expected SKU. Keep decoys separate from confirmed
observations. A decoy may be visible even when the expected item is also present.

Use this exact JSON shape:
{
  "observations": [{
    "sku": "string or UNKNOWN",
    "quantity": 0,
    "confidence": 0.0,
    "evidenceRef": "short description of visible evidence"
  }],
  "decoys": [{
    "label": "string",
    "quantity": 0,
    "reason": "why it does not match an expected item"
  }],
  "occlusion": {
    "status": "clear | partial | severe",
    "details": "string"
  },
  "status": "complete | uncertain",
  "reason": "string"
}

Use status=uncertain whenever the image cannot support a reliable inventory. The
response describes visual evidence only; do not produce a SEAL or STOP_AND_FIX
decision here."""


def _load_benchmark_results() -> dict[str, dict[str, Any]]:
    """Loads pre-computed evaluation results for offline replay in CI."""
    if not FIXTURES_RESULTS_PATH.is_file():
        return {}
    try:
        data = json.loads(FIXTURES_RESULTS_PATH.read_text(encoding="utf-8"))
        return {r["fixture_id"]: r for r in data.get("results", [])}
    except Exception:
        return {}


BENCHMARK_RESULTS = _load_benchmark_results()


def extract_pack_vision(
    *,
    image_url: str | None = None,
    expected_skus: list[str] | None = None,
    fixture_id: str | None = None,
    sample_observed_text: str | None = None,
) -> dict[str, Any]:
    """Batched vision extraction from an open box carton image.

    Returns:
        dict containing observations, decoys, occlusion, status, reason, model info, and latency_ms.
    """
    t0 = time.perf_counter()

    # 1. Replay mode from benchmark results (CI / offline deterministic test)
    if fixture_id and fixture_id in BENCHMARK_RESULTS:
        bench = BENCHMARK_RESULTS[fixture_id]
        detected = bench.get("detected_items", [])
        is_uncertain = bench.get("ai_verdict") == "UNCERTAIN"
        discrepancies = bench.get("discrepancies", [])

        decoys = []
        for disc in discrepancies:
            if "Unexpected" in disc or "foreign" in disc:
                decoys.append({"label": disc, "quantity": 1, "reason": disc})

        occlusion_status = "severe" if is_uncertain else "clear"
        reason = discrepancies[0] if discrepancies else ("Normal carton contents" if not is_uncertain else "Severe occlusion")

        return {
            "observations": [
                {
                    "sku": d.get("sku", "UNKNOWN"),
                    "quantity": d.get("quantity", 1),
                    "confidence": d.get("confidence", 0.95),
                    "evidenceRef": f"fixture:{fixture_id}",
                }
                for d in detected
            ],
            "decoys": decoys,
            "occlusion": {
                "status": occlusion_status,
                "details": reason if is_uncertain else "",
            },
            "status": "uncertain" if is_uncertain else "complete",
            "reason": reason,
            # Replay of a recorded Round 2 benchmark answer: no model is called now.
            "model": {
                "name": f"{DEFAULT_MODEL_NAME} (recorded)",
                "version": "2026-10",
                "provider": "replay:run_2.json",
                "calls": 0,
                "cost_usd": 0.0,
            },
            "latency_ms": bench.get("latency_ms", 1845),
        }

    # 2. Live VLM API call if API key and image provided (a local capture under data/input/ is sent as a data URL)
    image_url = _as_url(image_url)
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GROQ_API_KEY")
    if api_key and image_url and (image_url.startswith("http://") or image_url.startswith("https://") or image_url.startswith("data:")):
        endpoint = "https://openrouter.ai/api/v1/chat/completions" if os.environ.get("OPENROUTER_API_KEY") else "https://api.groq.com/openai/v1/chat/completions"
        provider = "openrouter" if os.environ.get("OPENROUTER_API_KEY") else "groq"
        model_name = os.environ.get("PACK_MODEL_NAME") or (DEFAULT_MODEL_NAME if provider == "openrouter" else GROQ_DEFAULT_MODEL_NAME)

        try:
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": PACK_VISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": json.dumps({"expectedSkus": expected_skus or []})},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ],
                "response_format": {"type": "json_object"},
            }
            with httpx.Client(timeout=VLM_TIMEOUT_S) as client:
                res = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                # Round 2 (verify/route.ts, openrouter.ts) throws on any non-OK response and fails open. Before this
                # check a 4xx/5xx fell through to the CSV replay below: a failed model call became the operator's
                # answer, or (for a capture with no CSV row) "nothing in the box" and a false STOP_AND_FIX.
                if res.status_code != 200:
                    raise RuntimeError(f"vision request failed (HTTP {res.status_code}): {res.text[:200]}")
                if res.status_code == 200:
                    raw_content = res.json()["choices"][0]["message"]["content"]
                    parsed = json.loads(raw_content)
                    latency_ms = int((time.perf_counter() - t0) * 1000)
                    return {
                        "observations": parsed.get("observations", []),
                        "decoys": parsed.get("decoys", []),
                        # A model that does not report occlusion has not shown the box is clear (Round 2 treated a
                        # missing value as not clear, which makes the verdict UNCERTAIN).
                        "occlusion": parsed.get("occlusion") or {"status": "not_reported", "details": "model did not report occlusion"},
                        "status": parsed.get("status", "complete"),
                        "reason": parsed.get("reason", ""),
                        "model": {
                            "name": model_name,
                            "version": "2026-10",
                            "provider": provider,
                            "calls": 1,
                            "cost_usd": None,  # not measured; token usage is in the provider response
                        },
                        "latency_ms": latency_ms,
                    }
        except Exception as exc:
            # Fail open guard (§5.3): never crash the line
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return {
                "observations": [],
                "decoys": [],
                "occlusion": {"status": "severe", "details": f"VLM call failed open: {exc}"},
                "status": "uncertain",
                "reason": f"VLM failure ({type(exc).__name__}): {exc}",
                "model": {
                    "name": model_name,
                    "version": "2026-10",
                    "provider": provider,
                    "calls": 1,
                    "cost_usd": 0.0,
                },
                "latency_ms": latency_ms,
            }

    # 3. Fallback for sample data replay (data/sample/pack_sample.csv): the operator-recorded box contents.
    #    No image is examined and no model is called.
    from agents.pack.adapter.engine import parse_order_lines
    observed_items = parse_order_lines(sample_observed_text or "")
    latency_ms = int((time.perf_counter() - t0) * 1000)

    return {
        "observations": [
            {
                "sku": it["sku"],
                "quantity": it["quantity"],
                "confidence": None,
                "evidenceRef": "sample:observed_in_box",
            }
            for it in observed_items
        ],
        "decoys": [],
        "occlusion": {"status": "clear", "details": ""},
        "status": "complete",
        "reason": "Replayed from the sample CSV observed_in_box column (no vision run)",
        "model": {
            "name": "csv-replay",
            "version": "pack-r2-replay",
            "provider": None,
            "calls": 0,
            "cost_usd": 0.0,
        },
        "latency_ms": latency_ms,
    }


_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _as_url(ref: str | None) -> str | None:
    """A relative capture ref under INPUT_DIR becomes a base64 data URL; anything else is returned unchanged."""
    if not ref or ref.startswith(("http://", "https://", "data:")):
        return ref
    root = Path(os.environ.get("INPUT_DIR", REPO_ROOT / "data" / "input")).resolve()
    path = (root / ref).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in _MIME:
        return ref
    import base64
    return f"data:{_MIME[path.suffix.lower()]};base64,{base64.b64encode(path.read_bytes()).decode()}"

