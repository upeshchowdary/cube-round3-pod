"""Returns Manager: agent entry point.

Round 2 Returns Manager pipeline (Gemini vision session + deterministic validation,
identity fusion, completeness, Amazon-condition grading, rules engine) behind a Round 3 adapter;
replay cassettes in CI, live Gemini on demand.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# 1. Add Round 2 source directory to sys.path (§3)
REPO_ROOT = Path(__file__).resolve().parents[2]
R2_SRC = REPO_ROOT / "agents" / "returns" / "r2" / "agent" / "src"
if str(R2_SRC) not in sys.path:
    sys.path.insert(0, str(R2_SRC))

# 2. Config file pointing to Pod root .env (§3)
os.environ.setdefault("RM_ENV_FILE", str(REPO_ROOT / ".env"))

# 3. Import Round 2 modules
from returns_manager.batch.io_csv import BeforeRow, ReturnedRow
from returns_manager.batch.runner import (
    RequestCapReached,
    RowResult,
    _NoDbQuota,
    load_rubric,
    process_returned_row,
)
from returns_manager.config import Settings
from returns_manager.llm.quota import QuotaExhaustedError
from returns_manager.llm.replay_client import CassetteMismatch

# 4. Import Adapter modules
from agents.returns.adapter.captures import CaptureError, resolve_captures
from agents.returns.adapter.mapping import build_returns_record
from agents.returns.adapter.orders import lookup_order
from agents.returns.adapter.runtime import (
    LocalCaptureTransport,
    create_model_client,
    run_sync,
)
from agents.returns.adapter.upstream import check_packing_error, reconcile_upstream
from shared.utils.hashing import seal
from shared.utils.log import get_logger
from shared.utils.records import pending_output, utcnow
from shared.utils.server import make_app

STAGE = "returns"
AGENT_ID = "returns-manager-rtn0045@2"

INPUT_DIR = Path(os.environ.get("INPUT_DIR", REPO_ROOT / "data" / "input"))
R2_REF_DIR = REPO_ROOT / "agents" / "returns" / "r2" / "reference"
CASSETTES_DIR = REPO_ROOT / "agents" / "returns" / "cassettes"

logger = get_logger("returns")


def _read_round2_commit() -> str:
    copied_from = REPO_ROOT / "agents" / "returns" / "r2" / "COPIED_FROM.txt"
    if copied_from.is_file():
        for line in copied_from.read_text(encoding="utf-8").splitlines():
            if line.startswith("Commit SHA:"):
                return line.split(":", 1)[1].strip()
    return "f9b143e4e63d74ed052cf8732e38a7c1cba9a3d8"


def _read_prompt_version() -> str:
    lock_file = REPO_ROOT / "agents" / "returns" / "r2" / "agent" / "prompts" / "prompts.lock.json"
    if lock_file.is_file():
        try:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
            return data.get("judgment", {}).get("version", "1.5.0")
        except Exception:
            pass
    return "1.5.0"


def _round2_settings() -> Settings:
    """Round 2 Settings, with the Pod's LOG_LEVEL convention mapped onto Round 2's.

    The Pod documents LOG_LEVEL as DEBUG | INFO | WARNING (`.env.example`, `make run` sets WARNING); Round 2 accepts only
    lower-case debug | info | warning | error and raised a ValidationError on the Pod's values, which crashed this agent.
    """
    level = os.environ.get("LOG_LEVEL", "info").strip().lower()
    return Settings(log_level=level if level in ("debug", "info", "warning", "error") else "info")


ROUND2_COMMIT = _read_round2_commit()
PROMPT_VERSION = _read_prompt_version()


def handle(request: dict) -> dict:
    t0 = time.perf_counter()
    start_time_iso = utcnow()

    subject_id = request["subject"]["subject_id"]
    org_id = request["subject"]["org_id"]

    # 1. Tenancy and Order lookup (§4.1)
    # Raises LookupError directly if subject is unknown or belongs to another tenant
    order = lookup_order(subject_id, org_id, input_dir=INPUT_DIR, r2_ref_dir=R2_REF_DIR)

    if not order.category:
        return pending_output(
            request,
            code="no_category",
            message=f"No product category could be determined for SKU {order.ordered_sku}",
            retryable=False,
            agent_id=AGENT_ID,
        )

    # 2. Captures discovery and validation (§4.2)
    try:
        captures = resolve_captures(request, input_dir=INPUT_DIR)
    except CaptureError as exc:
        return pending_output(
            request,
            code=exc.code,
            message=exc.message,
            retryable=False,
            agent_id=AGENT_ID,
        )

    # 3. Upstream reconciliation (§4.3)
    used_pack = captures.reference_source == "pack"
    used_rcv = captures.reference_source == "receiving"
    upstream_recon, consumed_refs = reconcile_upstream(
        request,
        order.ordered_sku,
        used_pack_as_reference=used_pack,
        used_rcv_as_reference=used_rcv,
    )

    # 4. Model client and mode configuration (§4.4)
    mode = os.environ.get("RETURNS_MODEL_MODE", "replay")
    try:
        settings = _round2_settings()
    except Exception as exc:  # a configuration problem is recorded, never a crash of the agent
        return pending_output(request, code="model_not_configured", message=f"Round 2 settings invalid: {exc}"[:500],
                              retryable=False, agent_id=AGENT_ID)

    try:
        client, cassette_path = create_model_client(
            mode,
            org_id,
            subject_id,
            settings,
            CASSETTES_DIR,
        )
    except FileNotFoundError as exc:
        return pending_output(
            request,
            code="no_cassette",
            message=f"no cassette found for {subject_id} in {org_id}. Record one with: python -m agents.returns.tools.record_cassette --unit {subject_id} --org {org_id}",
            retryable=False,
            agent_id=AGENT_ID,
        )
    except ValueError as exc:
        msg = str(exc)
        if "GEMINI_API_KEY" in msg:
            return pending_output(
                request,
                code="model_not_configured",
                message=msg,
                retryable=False,
                agent_id=AGENT_ID,
            )
        return pending_output(
            request,
            code="agent_internal_error",
            message=msg,
            retryable=False,
            agent_id=AGENT_ID,
        )
    except Exception as exc:  # any other client set-up failure is recorded, never a crash
        return pending_output(request, code="model_not_configured", message=f"{type(exc).__name__}: {exc}"[:500],
                              retryable=False, agent_id=AGENT_ID)

    cassette_sha256: str | None = None
    cassette_provenance: str | None = None
    if cassette_path and cassette_path.is_file():
        cassette_bytes = cassette_path.read_bytes()
        cassette_sha256 = hashlib.sha256(cassette_bytes).hexdigest()
        first = next((ln for ln in cassette_bytes.decode("utf-8").splitlines() if ln.strip()), "")
        try:
            cassette_provenance = json.loads(first).get("provenance") if first else None
        except ValueError:
            cassette_provenance = None

    # Quota guard
    max_requests = int(os.environ.get("RETURNS_MAX_REQUESTS", "6"))
    rpm = 6000.0 if mode == "replay" else settings.rm_rpm_limit_judgment
    quota = _NoDbQuota(rpm=rpm, max_requests=max_requests)

    # 5. Build BeforeRow and ReturnedRow (§4.4)
    before = BeforeRow(
        record_id=order.record_id,
        unit_id=order.unit_id,
        org_id=order.org_id,
        order_id=order.order_id,
        ordered_sku=order.ordered_sku,
        ordered_asin=order.ordered_asin,
        identity_match="",  # never copy CSV operator column (§1.7)
        parts_list=order.parts_list,
        time=order.captured_at or start_time_iso,
        photo_ref=captures.reference_url,
        category=order.category,
        list_price_minor=order.list_price_minor,
    )

    returned = ReturnedRow(
        record_id=order.record_id,
        unit_id=order.unit_id,
        org_id=order.org_id,
        order_id=order.order_id,
        ordered_sku=order.ordered_sku,
        ordered_asin=order.ordered_asin,
        returned_photo_refs=tuple(captures.return_urls),
        time=order.captured_at or start_time_iso,
    )

    # 6. Run Round 2 pipeline (§4.4)
    transport = LocalCaptureTransport(INPUT_DIR)

    async def _execute_pipeline() -> RowResult:
        headers = {"User-Agent": "ReturnsManagerRound3Adapter/1.0"}
        async with httpx.AsyncClient(transport=transport, timeout=30.0, headers=headers) as http_client:
            return await process_returned_row(
                returned,
                {order.unit_id: before},
                settings=settings,
                client=client,
                http_client=http_client,
                quota=quota,
                default_category=order.category,
                list_price_minor=order.list_price_minor,
            )

    def _pending_after_calls(code: str, message: str, retryable: bool) -> dict:
        """A fail-open record that still says which model was called and how many requests were really sent:
        failed requests count against the quota too, so `calls: 0` would understate the spend."""
        out = pending_output(request, code=code, message=message, retryable=retryable, agent_id=AGENT_ID)
        if mode != "replay" and quota.requests_sent:
            ev = dict(out["evidence"])
            ev["model"] = {"name": settings.rm_judgment_model, "version": settings.rm_judgment_model, "provider": "google",
                           "prompt_version": PROMPT_VERSION, "calls": quota.requests_sent, "cost_usd": 0.0}
            out = {**out, "evidence": seal(ev)}
        return out

    try:
        row_result: RowResult = run_sync(_execute_pipeline())
    except CassetteMismatch as exc:
        return _pending_after_calls("cassette_mismatch", str(exc), False)
    except (QuotaExhaustedError, RequestCapReached) as exc:
        return _pending_after_calls("quota_exhausted", str(exc), True)
    except Exception as exc:
        logger.error("Returns Manager pipeline failed: %s (%s)", type(exc).__name__, exc, exc_info=True)
        return _pending_after_calls("agent_internal_error", f"{type(exc).__name__}: {exc}", True)

    # Handle runner fail-open (§4.4)
    if row_result.note is not None:
        note_msg = row_result.output_row.get("rationale") or row_result.note
        return _pending_after_calls(row_result.note, note_msg, False)

    # 7. Check for packing error note (§4.3)
    # Round 2 checks carry their key in `check_key` (judgment/pipeline.py: Check); `name` never existed, so this lookup
    # used to miss and the packing-error note could never fire.
    ident_chk = next((c for c in (row_result.detail or {}).get("checks", []) if c.get("check_key") == "identity"), None)
    ident_verdict = ident_chk["verdict"] if ident_chk else "UNCERTAIN"
    packing_note = check_packing_error(upstream_recon, ident_verdict)

    # 8. Rubric snapshot ID
    try:
        rubric = load_rubric(order.category)
        cond_scale_source = f"{rubric.snapshot_id} (unverified_substitute)"
    except Exception:
        cond_scale_source = "amazon-uk-condition-guidelines-2020-12 (unverified_substitute)"

    latency_ms = int((time.perf_counter() - t0) * 1000)
    captured_at = order.captured_at or start_time_iso
    captured_at_source = "order_row" if order.captured_at else "handle_start"
    recorded_calls = 1 if mode == "replay" else None

    # 9. Map to Round 3 Evidence Record (§4.5)
    return build_returns_record(
        request,
        order,
        row_result,
        captures,
        upstream_recon,
        agent_id=AGENT_ID,
        model_mode=mode,
        cassette_sha256=cassette_sha256,
        cassette_provenance=cassette_provenance,
        prompt_version=PROMPT_VERSION,
        model_name=settings.rm_judgment_model,
        model_version=settings.rm_judgment_model,
        live_calls=quota.requests_sent,
        recorded_calls=recorded_calls,
        cost_note="free tier; list-price estimate $0.0042",
        condition_scale_source=cond_scale_source,
        round2_commit=ROUND2_COMMIT,
        captured_at_source=captured_at_source,
        captured_at=captured_at,
        latency_ms=latency_ms,
        packing_error_note=packing_note,
    )


app = make_app(STAGE, handle)
