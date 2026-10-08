"""The orchestrator owns workflow state. Status and final outcome are DERIVED from the evidence chain.

Uses fake agents so each rule can be tested in isolation. Copy and adapt for any rule your Pod changes.
"""
import json
from pathlib import Path

import pytest

from orchestration.orchestrator import apply_override, bundle, load_flow, resume, run_workflow
from orchestration.store import EvidenceConflict, MemoryStore
from shared.utils.schema import errors
from tests.helpers import Boom, Fake

ROOT = Path(__file__).resolve().parents[2]
STANDARD = load_flow(ROOT / "orchestration/flow.json")
CASE = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}  # receiving, prep, returns, recovery


def fakes(**verdicts):
    base = {s: Fake("PASS") for s in ("receiving", "prep", "pack", "returns", "recovery")}
    base.update({s: (v if hasattr(v, "run") else Fake(v)) for s, v in verdicts.items()})
    return base


def run(flow=STANDARD, store=None, **verdicts):
    store = store or MemoryStore()
    return run_workflow(CASE, flow, store, fakes(**verdicts)), store


def with_policy(**policy):
    return {**STANDARD, "defaults": {**STANDARD["defaults"], **policy}}


def valid(wf):
    assert errors("workflow-state", wf) == []
    return wf


# ------------------------------------------------------------ status and final outcome
def test_all_pass_is_completed_and_clean():
    wf, _ = run()
    assert (wf["status"], wf["final_outcome"]["outcome"], wf["final_outcome"]["provisional"]) == ("COMPLETED", "CLEAN", False)
    assert valid(wf)["timestamps"]["completed_at"]


def test_recovery_fail_is_a_claim_with_amount_and_evidence():
    wf, _ = run(recovery=Fake("FAIL", needs_human=False, payload={"claimable_usd": 4.25}))
    fo = wf["final_outcome"]
    assert (wf["status"], fo["outcome"], fo["claimable_usd"]) == ("COMPLETED", "CLAIM_RECOMMENDED", 4.25)
    assert fo["contributing_records"], "no outcome without evidence"


def test_stage_fail_without_claim_is_an_exception():
    wf, _ = run(prep="FAIL")
    assert (wf["status"], wf["final_outcome"]["outcome"]) == ("COMPLETED", "EXCEPTION")


def test_uncertain_is_preserved_and_blocks_for_a_person_not_a_pass():
    wf, store = run(receiving="UNCERTAIN")
    rec = store.get_evidence(next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "receiving"))
    assert rec["decision"]["verdict"] == "UNCERTAIN", "the evidence must stay UNCERTAIN"
    assert (wf["status"], wf["final_outcome"]["outcome"], wf["final_outcome"]["needs_human"]) == ("BLOCKED", "NEEDS_REVIEW", True)
    assert wf["final_outcome"]["provisional"] is True
    assert all(s["state"] == "completed" for s in wf["stage_results"] if s["state"] != "skipped"), "default policy continues"


def test_policy_block_halts_and_leaves_later_stages_unrun():
    wf, store = run(with_policy(on_uncertain="block"), receiving="UNCERTAIN")
    states = {s["stage"]: s["state"] for s in wf["stage_results"]}
    assert states["prep"] == states["returns"] == states["recovery"] == "pending"
    assert wf["status"] == "BLOCKED" and wf["halted"]["stage"] == "receiving"
    assert [t["event"] for t in wf["transitions"] if t["event"] == "halted"]


def test_block_policy_ignores_uncertain_that_needs_no_person():
    """Recovery's SILENT is UNCERTAIN with needs_human=false: nothing for a human to decide, so no halt."""
    wf, _ = run(with_policy(on_uncertain="block"), recovery=Fake("UNCERTAIN", needs_human=False))
    assert wf["halted"] is None and (wf["status"], wf["final_outcome"]["outcome"]) == ("COMPLETED", "CLEAN")


def test_fail_before_recovery_runs_is_recovery_required():
    wf, _ = run(with_policy(on_uncertain="block"), receiving="FAIL", prep=Fake("UNCERTAIN"))
    assert wf["status"] == "RECOVERY_REQUIRED" and "recovery" in wf["status_reason"].lower()
    assert {s["stage"]: s["state"] for s in wf["stage_results"]}["recovery"] == "pending"


def test_override_then_resume_completes_a_blocked_workflow():
    flow = with_policy(on_uncertain="block")
    store = MemoryStore()
    clients = fakes(receiving="UNCERTAIN")
    wf = run_workflow(CASE, flow, store, clients)
    rid = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "receiving")
    wf = apply_override(wf["workflow_id"], store, record_id=rid, new_verdict="PASS", actor="op_amira", reason="photo retaken, carton fine")
    assert wf["status"] == "BLOCKED", "overriding does not silently resume"
    wf = resume(wf["workflow_id"], flow, store, clients)
    assert (wf["status"], wf["final_outcome"]["outcome"]) == ("COMPLETED", "CLEAN")


# ------------------------------------------------------------ failures are recorded, never hidden
@pytest.mark.parametrize("exc_name,code", [("AgentTimeout", "agent_timeout"), ("AgentUnavailable", "agent_unavailable")])
def test_transient_failure_is_retried_then_recorded(exc_name, code):
    import tests.helpers as h
    boom = Boom(getattr(h, exc_name)("down"))
    wf, store = run(prep=boom)
    sr = next(s for s in wf["stage_results"] if s["stage"] == "prep")
    assert boom.calls == 2 and sr["attempts"] == 2, "1 try + 1 retry from flow defaults"
    assert sr["state"] == "error" and sr["error"]["code"] == code and sr["error"]["retryable"] is True
    assert wf["status"] == "FAILED" and wf["final_outcome"]["outcome"] == "INCOMPLETE" and wf["final_outcome"]["provisional"]
    assert any(e["code"] == code for e in wf["errors"])
    assert {s["stage"]: s["state"] for s in wf["stage_results"]}["recovery"] == "completed", "later stages still run"


def test_refusal_is_not_retried():
    import tests.helpers as h
    boom = Boom(h.AgentRejected("HTTP 404"))
    wf, _ = run(receiving=boom)
    assert boom.calls == 1 and wf["errors"][0]["code"] == "agent_rejected" and wf["errors"][0]["retryable"] is False


def test_agent_crash_does_not_crash_the_orchestrator():
    wf, _ = run(prep=Boom(RuntimeError("model blew up")))
    assert next(s for s in wf["stage_results"] if s["stage"] == "prep")["error"]["code"] == "agent_exception"
    assert wf["status"] == "FAILED"


@pytest.mark.parametrize("how,code", [("garbage", "invalid_output"), ("tampered", "invalid_output"), ("wrong_stage", "invalid_output"),
                                      ("disagree", "invalid_output"), ("other_tenant", "tenant_mismatch")])
def test_invalid_output_is_rejected_and_recorded(how, code):
    from tests.helpers import Mangle
    wf, store = run(receiving=Mangle("receiving", how))
    sr = next(s for s in wf["stage_results"] if s["stage"] == "receiving")
    assert sr["error"]["code"] == code and sr["state"] == "error"
    rec = store.get_evidence(sr["record_id"])
    assert rec["status"] != "completed" and rec["checks"] == [] and rec["decision"]["verdict"] == "UNCERTAIN", \
        "a degraded stage must not fabricate a judgment"
    assert errors("evidence", rec) == []


def test_a_workflow_is_never_completed_or_clean_when_a_required_stage_did_not_complete():
    import tests.helpers as h
    for broken in (Boom(h.AgentUnavailable("x")), Boom(RuntimeError("x")), h.Mangle("prep", "garbage"), h.Mangle("prep", "other_tenant")):
        wf, _ = run(prep=broken)
        assert wf["status"] != "COMPLETED" and wf["final_outcome"]["outcome"] != "CLEAN"


def test_resume_retries_a_failed_stage_and_keeps_the_failed_evidence():
    import tests.helpers as h
    flaky, store = h.Flaky(h.AgentUnavailable("blip"), n=2), MemoryStore()
    clients = fakes(prep=flaky)
    wf = run_workflow(CASE, STANDARD, store, clients)
    assert wf["status"] == "FAILED"
    failed_id = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "prep")
    wf = resume(wf["workflow_id"], STANDARD, store, clients)
    ids = wf["evidence_references"]
    assert wf["status"] == "COMPLETED" and failed_id in ids and next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "prep") != failed_id
    assert store.get_evidence(failed_id)["status"] != "completed", "the failed attempt remains traceable"


def _record(wf, stage):
    return next(s["record_id"] for s in wf["stage_results"] if s["stage"] == stage)


def test_resume_re_runs_recovery_after_an_upstream_stage_is_repaired():
    """D-012: Recovery judged the degraded Prep record; once Prep is repaired, Recovery must see the real evidence."""
    import tests.helpers as h
    store, recovery = MemoryStore(), Fake("PASS")
    clients = fakes(prep=h.Flaky(h.AgentUnavailable("blip"), n=2), recovery=recovery)
    wf = run_workflow(CASE, STANDARD, store, clients)
    old_rcy, degraded_prep = _record(wf, "recovery"), _record(wf, "prep")
    assert degraded_prep in store.get_evidence(old_rcy)["upstream_refs"]
    wf = resume(wf["workflow_id"], STANDARD, store, clients)
    new_rcy, new_prep = _record(wf, "recovery"), _record(wf, "prep")
    assert recovery.calls == 2 and new_rcy != old_rcy
    assert new_prep in store.get_evidence(new_rcy)["upstream_refs"], "Recovery re-judged with the repaired Prep record"
    assert old_rcy in wf["evidence_references"], "the earlier Recovery record stays on record"
    assert any(t["event"] == "stage_stale" and t["stage"] == "recovery" for t in wf["transitions"])
    assert wf["status"] == "COMPLETED"


def test_resume_after_an_override_re_runs_recovery_with_the_override():
    store, recovery = MemoryStore(), Fake("PASS")
    clients = fakes(prep="FAIL", recovery=recovery)
    wf = run_workflow(CASE, STANDARD, store, clients)
    wf = apply_override(wf["workflow_id"], store, record_id=_record(wf, "prep"), new_verdict="PASS", actor="op", reason="label is flat")
    assert recovery.calls == 1, "an override alone does not re-run anything"
    assert any(t["event"] == "downstream_judged_before_override" for t in wf["transitions"])
    wf = resume(wf["workflow_id"], STANDARD, store, clients)
    assert recovery.calls == 2
    assert store.get_evidence(_record(wf, "recovery"))["upstream_refs"], "re-run record still cites its upstream"


def test_stages_without_the_flag_are_not_re_run():
    store, prep = MemoryStore(), Fake("PASS")
    clients = fakes(receiving="UNCERTAIN", prep=prep)
    wf = run_workflow(CASE, STANDARD, store, clients)
    apply_override(wf["workflow_id"], store, record_id=_record(wf, "receiving"), new_verdict="PASS", actor="op", reason="ok")
    resume(wf["workflow_id"], STANDARD, store, clients)
    assert prep.calls == 1, "Prep does not judge with upstream evidence, so the flow does not re-run it"


# ------------------------------------------------------------ overrides
def test_override_references_the_evidence_and_changes_the_outcome_without_rewriting_it():
    wf, store = run(prep="FAIL")
    prep_id = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "prep")
    before = json.dumps(store.get_evidence(prep_id), sort_keys=True)
    assert wf["final_outcome"]["outcome"] == "EXCEPTION"
    wf = apply_override(wf["workflow_id"], store, record_id=prep_id, new_verdict="PASS", actor="op_amira", reason="label is flat, agent misread the seam")
    o = wf["overrides"][0]
    assert o["supersedes"] == {"record_id": prep_id, "override_id": None}
    assert (o["original_verdict"], o["previous_verdict"], o["new_verdict"], o["actor"]) == ("FAIL", "FAIL", "PASS", "op_amira")
    assert o["reason"] and o["at"]
    assert (wf["status"], wf["final_outcome"]["outcome"]) == ("COMPLETED", "CLEAN")
    assert wf["final_outcome"]["effective_verdicts"]["prep"] == "PASS"
    assert json.dumps(store.get_evidence(prep_id), sort_keys=True) == before, "the original evidence is untouched"
    assert wf["stage_results"][1]["verdict"] == "FAIL", "the agent's own verdict is still on record"
    valid(wf)


def test_overrides_chain_and_latest_wins():
    wf, store = run(prep="FAIL")
    prep_id = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "prep")
    apply_override(wf["workflow_id"], store, record_id=prep_id, new_verdict="PASS", actor="a", reason="first look")
    wf = apply_override(wf["workflow_id"], store, record_id=prep_id, new_verdict="FAIL", actor="b", reason="second look")
    assert wf["overrides"][1]["supersedes"]["override_id"] == "OVR-001" and wf["overrides"][1]["previous_verdict"] == "PASS"
    assert wf["final_outcome"]["effective_verdicts"]["prep"] == "FAIL" and wf["final_outcome"]["outcome"] == "EXCEPTION"


def test_overriding_a_claim_withdraws_it():
    wf, store = run(recovery=Fake("FAIL", needs_human=False, payload={"claimable_usd": 2}))
    rid = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "recovery")
    wf = apply_override(wf["workflow_id"], store, record_id=rid, new_verdict="PASS", actor="seller", reason="charge was valid after all")
    assert wf["final_outcome"]["outcome"] == "CLEAN" and wf["final_outcome"]["claimable_usd"] is None


def test_override_needs_actor_reason_and_real_evidence():
    wf, store = run()
    rid = wf["evidence_references"][0]
    for kw in ({"actor": "", "reason": "x"}, {"actor": "a", "reason": " "}):
        with pytest.raises(ValueError):
            apply_override(wf["workflow_id"], store, record_id=rid, new_verdict="PASS", **kw)
    with pytest.raises(ValueError):
        apply_override(wf["workflow_id"], store, record_id="RCV-NOPE", new_verdict="PASS", actor="a", reason="x")


# ------------------------------------------------------------ evidence is immutable and the chain is traceable
def test_evidence_cannot_be_replaced():
    wf, store = run()
    rec = dict(store.get_evidence(wf["evidence_references"][0]))
    rec["decision"] = {**rec["decision"], "reason": "rewritten"}
    from shared.utils.hashing import seal
    with pytest.raises(EvidenceConflict):
        store.put_evidence(seal(rec))


def test_every_final_outcome_traces_back_to_stored_evidence():
    wf, store = run(prep="FAIL")
    b = bundle(wf, store)
    for rid in wf["final_outcome"]["contributing_records"]:
        assert rid in wf["evidence_references"] and b["evidence"][rid] is not None
    assert all(errors("evidence", r) == [] for r in b["evidence"].values())


def test_rerunning_a_case_does_not_duplicate_or_change_evidence():
    store = MemoryStore()
    clients = fakes()
    a = run_workflow(CASE, STANDARD, store, clients)
    b = run_workflow(CASE, STANDARD, store, clients)
    assert a["evidence_references"] == b["evidence_references"]
    assert sum(c.calls for c in clients.values()) == 4, "completed stages are not re-run"


# ------------------------------------------------------------ routing
def states(wf):
    return {s["stage"]: s["state"] for s in wf["stage_results"]}


def test_fba_goes_through_prep_not_pack(cases):
    s = states(run_workflow(next(c for c in cases if c["route"] == "fba"), STANDARD))
    assert s["prep"] != "skipped" and s["pack"] == "skipped"


def test_mfn_goes_through_pack_not_prep(cases):
    s = states(run_workflow(next(c for c in cases if c["route"] == "mfn"), STANDARD))
    assert s["pack"] != "skipped" and s["prep"] == "skipped"


def test_returns_only_when_a_return_happened(cases):
    for case in cases[:30]:
        assert (states(run_workflow(case, STANDARD))["returns"] != "skipped") == case["returned"]


def test_unrouted_subject_skips_prep_and_pack_but_completes_the_rest(cases):
    s = states(run_workflow(next(c for c in cases if c["route"] == "unknown"), STANDARD))
    assert s["prep"] == s["pack"] == "skipped" and s["receiving"] == s["recovery"] == "completed"


def test_specialist_flow_has_no_prep_and_recovery_stays_silent_on_inbound_fees(cases):
    flow = load_flow(ROOT / "orchestration/flow.specialist.json")
    assert "prep" not in [s["stage"] for s in flow["steps"]]
    store = MemoryStore()
    wf = run_workflow(next(c for c in cases if c["route"] == "fba"), flow, store)
    rec = store.get_evidence(next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "recovery"))
    for charge in rec["payload"]["charges"]:
        if charge["charge_type"] == "inbound_defect_fee":
            assert charge["position"] == "SILENT", "no Prep evidence, so no claim"


# ------------------------------------------------------------ an agent that cannot be imported
def test_agent_that_cannot_be_imported_is_recorded_not_a_crash():
    """A missing dependency in one agent (e.g. an import of a package not in requirements.txt) must become an error
    record for that stage; the other stages still run and the workflow ends FAILED, never a crashed run."""
    from orchestration.clients import InProcClient

    broken = InProcClient({"module": "agents.no_such_agent_module", "stage": "returns"})
    assert broken.load_error and "no_such_agent_module" in broken.load_error
    wf, _ = run(returns=broken)
    by_stage = {s["stage"]: s for s in wf["stage_results"]}
    assert by_stage["returns"]["state"] == "error"
    assert by_stage["returns"]["error"]["code"] == "agent_exception"
    assert by_stage["recovery"]["state"] == "completed"
    assert valid(wf)["status"] == "FAILED"
