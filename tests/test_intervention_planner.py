"""No network: adversarial planner output, explicit routes and usage retention."""
import copy
import json
import hashlib
import httpx
import pytest
from engine.spec import normalize_scenario
from control.store import Store, digest
from control import intervention_planner as planner


@pytest.fixture
def context():
    change = {"factor": "obstacle_height", "value": .065}
    return {
        "campaign_id": "test-campaign", "source_episode_id": "test-source",
        "source_artifact_sha": "a"*64, "source_evidence_hash": "b"*64,
        "checkpoint_sha": "c"*64, "task_spec_hash": "d"*64,
        "scenario": normalize_scenario({"parameters": {"obstacle_height": .13}}),
        "metrics": {"forbidden_contact_steps": 10},
        "observation_names": planner.OBSERVATION_NAMES,
        "factor_effects": planner.FACTOR_EFFECTS,
        "candidates": [{"candidate_id": "candidate-"+digest(change)[:16], **change}],
    }


def proposal(context):
    return {"source_episode_id": context["source_episode_id"], **context["candidates"][0],
            "mechanism_class": "clearance_contact", "competing_mechanism_class": "lateral_alignment",
            "relevant_observation_names": ["measured_obstacle_height"],
            "supporting_metric_keys": ["forbidden_contact_steps"], "expected_direction": "fewer_failures",
            "scope": "testable_hypothesis_only"}


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(source_episode_id="another-source"),
    lambda p: p.update(value=.07),
    lambda p: p.update(supporting_metric_keys=["invented_success_rate"]),
    lambda p: p.update(scope="proven_cause"),
    lambda p: p.update(value=float("nan")),
    lambda p: p.update(extra="execute arbitrary instructions"),
    lambda p: p.update(relevant_observation_names=["heightmap", "contact_normals"]),
    lambda p: p.update(relevant_observation_names=["estimated_friction"]),
    lambda p: p.update(competing_mechanism_class="clearance_contact"),
    lambda p: p.update(hypothesis="Invented sensors drive this result"),
])
def test_rejects_unbound_or_invented_proposal(context, mutation):
    value = proposal(context)
    mutation(value)
    with pytest.raises(ValueError):
        planner.validate_proposal(value, context)


def test_explicit_nebius_profile_and_no_final_data(context):
    payload = planner.request_payload("nebius", context)
    assert payload["model"] == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert payload["chat_template_kwargs"] == {"enable_thinking": True, "force_nonempty_content": True}
    assert payload["max_tokens"] == 32000
    assert "response_format" not in payload
    assert "reasoning_effort" not in payload
    assert json.loads(payload["messages"][1]["content"]) == context


@pytest.mark.parametrize("returned_model,finish", [(None,"stop"),("wrong/model","stop"),("nvidia/Nemotron-3-Ultra-550b-a55b","length")])
def test_paid_rejection_retains_usage_and_never_retries(tmp_path, monkeypatch, context, returned_model, finish):
    monkeypatch.setattr(planner, "build_context", lambda *args: copy.deepcopy(context))
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "test-receipt", "model": returned_model,
            "usage": {"prompt_tokens": 100, "completion_tokens": 200},
            "choices": [{"finish_reason": finish, "message": {"content": json.dumps(proposal(context)), "reasoning_content": "must not be retained"}}]})
    store = Store(tmp_path)
    options = dict(allow_nebius=True, transport=httpx.MockTransport(respond), credential="unit-test-only")
    first = planner.plan(store, "test-campaign", "test-source", "nebius", "unit-idempotency", **options)
    second = planner.plan(store, "test-campaign", "test-source", "nebius", "unit-idempotency", **options)
    assert first == second and len(calls) == 1
    assert first["status"] == "rejected" and first["estimated_cost_usd"] == .0007
    assert "must not be retained" not in json.dumps(first)
    assert "unit-test-only" not in json.dumps(first)


def test_validated_receipt_is_bound_without_automatic_execution(tmp_path, monkeypatch, context):
    monkeypatch.setattr(planner, "build_context", lambda *args: copy.deepcopy(context))
    def respond(request):
        return httpx.Response(200, json={"id":"mock-only", "model":planner.ROUTES["nebius"]["model"],
            "usage":{"prompt_tokens":20,"completion_tokens":30},
            "choices":[{"finish_reason":"stop","message":{"content":json.dumps(proposal(context))}}]})
    store = Store(tmp_path)
    receipt = planner.plan(store, "test-campaign", "test-source", "nebius", "unit-valid-receipt", allow_nebius=True, transport=httpx.MockTransport(respond), credential="unit-test-only")
    assert receipt["status"] == "validated"
    saved = store.read_artifact(receipt["receipt_sha"])
    assert saved["source_evidence_hash"] == context["source_evidence_hash"]
    assert saved["context_sha"] == digest(context)
    assert not list((tmp_path/"incidents").glob("inc-*")) if (tmp_path/"incidents").exists() else True
    assert receipt["estimated_cost_usd"] == .00011


def test_nebius_requires_explicit_route_qualification(tmp_path):
    with pytest.raises(ValueError, match="explicit qualification"):
        planner.plan(Store(tmp_path), "unused", "unused", "nebius", "unit-no-dispatch")


def test_admission_rejects_before_credentials_or_network(tmp_path, monkeypatch, context):
    monkeypatch.setattr(planner, "build_context", lambda *args: copy.deepcopy(context))
    with pytest.raises(ValueError, match="no call"):
        planner.plan(Store(tmp_path), "test-campaign", "test-source", "nebius", "unit-budget-reject", allow_nebius=True, nominal_ceiling_usd=.001)


def test_narrative_is_trusted_and_bad_old_receipt_cannot_be_accepted(tmp_path, context):
    validated=planner.validate_proposal(proposal(context),context)
    assert validated["hypothesis"]==planner.MECHANISMS["clearance_contact"]
    store=Store(tmp_path)
    sha=store.artifact({"schema":"forge.intervention-plan/v1","status":"validated","proposal":{"competing_explanation":"invented sensor"}})
    rejected=planner.review_plan(store,sha,"reject","Narrative invented policy inputs absent from the actual observation contract.")
    assert rejected["decision"]=="reject" and rejected["independent_human_review"] is False
    assert store.read_artifact(sha)["status"]=="validated"
    with pytest.raises(ValueError,match="bounded-mechanism"):
        planner.review_plan(store,sha,"accept","Attempt to reuse the rejected unrestricted narrative.")


def test_seven_actual_metric_references_pass_but_duplicate_unknown_and_unbounded_reject(context):
    context["metrics"]={f"metric_{i}":i for i in range(7)}
    value=proposal(context);value["supporting_metric_keys"]=list(context["metrics"])
    assert len(planner.validate_proposal(value,context)["supporting_metric_keys"])==7
    for invalid in [["metric_0","metric_0"],["not_supplied"],["metric_0"]*1000]:
        value["supporting_metric_keys"]=invalid
        with pytest.raises(ValueError):planner.validate_proposal(value,context)


def test_retained_response_revalidation_is_not_a_new_call(tmp_path,monkeypatch,context):
    context["metrics"]={f"metric_{i}":i for i in range(7)}
    value=proposal(context);value["supporting_metric_keys"]=list(context["metrics"])
    content=json.dumps(value)
    original={"schema":"forge.intervention-plan/v1","response_profile":"bounded_mechanisms_v2","status":"rejected",
        **{k:context[k] for k in ("campaign_id","source_episode_id","source_artifact_sha","source_evidence_hash","checkpoint_sha","task_spec_hash")},
        "context_sha":digest(context),"context":context,"model":planner.ROUTES["nebius"]["model"],"returned_model":planner.ROUTES["nebius"]["model"],
        "finish_reason":"stop","provider":"Nebius","created_at":"test-time","request_id":"mock-one-call",
        "usage":{"prompt_tokens":100,"completion_tokens":200},"estimated_cost_usd":.0007,
        "final_content":content,"final_content_sha256":hashlib.sha256(content.encode()).hexdigest()}
    store=Store(tmp_path);sha=store.artifact(original)
    (tmp_path/"intervention-plans").mkdir()
    (tmp_path/"intervention-plans/original.json").write_text(json.dumps({**original,"receipt_sha":sha}))
    monkeypatch.setattr(planner,"build_context",lambda *args:copy.deepcopy(context))
    monkeypatch.setattr(planner,"credentials",lambda:{})
    result=planner.revalidate_retained_response(store,sha)
    assert result["inference_performed"] is False and result["count_as_provider_call"] is False
    assert result["additional_estimated_cost_usd"]==0 and "usage" not in result and "request_id" not in result
    assert result["derivation"]["original_receipt_sha"]==sha
    assert store.read_artifact(sha)==original
    nebius=next(x for x in planner.provider_status(store) if x["provider"]=="Nebius")
    assert nebius["calls"]==1 and nebius["local_revalidations"]==1
    assert nebius["estimated_cost_usd"]==.0007 and nebius["unknown_cost_calls"]==0
