"""Explicit NVIDIA inference routes. No automatic provider/model substitution."""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import time
import httpx
from dotenv import dotenv_values
from .store import ROOT, canonical, digest, now

ROUTES = {
    "planner": {"provider": "Fireworks", "model": "accounts/fireworks/models/nemotron-3-ultra-nvfp4", "url": "https://api.fireworks.ai/inference/v1/chat/completions", "key": "FIREWORKS_AI_API_KEY", "input_rate": .60, "output_rate": 2.40},
    "visual": {"provider": "Together", "model": "nvidia/NVIDIA-Nemotron-3.5-Super-VL", "url": "https://api.together.xyz/v1/chat/completions", "key": "TOGETHER_AI_API_KEY", "input_rate": .15, "output_rate": .50},
}

def credentials():
    # Parent file is never copied, printed, exported, or passed to a browser.
    return dotenv_values(ROOT.parent / ".env")

def status():
    keys = credentials()
    return [{"purpose": purpose, "provider": r["provider"], "model": r["model"], "configured": bool(keys.get(r["key"])), "role": "Bounded development hypotheses" if purpose == "planner" else "Advisory analysis of actual simulation renders"} for purpose, r in ROUTES.items()] + [{"purpose": "submission", "provider": "Nebius", "model": "nvidia/NVIDIA-Nemotron-3-Ultra-550b-a55b", "configured": False, "status": "Qualification pending; not used by this local application"}]

def strict_json(content):
    text = content.strip()
    if text.startswith("```json") and text.endswith("```"): text = text[7:-3].strip()
    elif text.startswith("```") and text.endswith("```"): text = text[3:-3].strip()
    return json.loads(text)

def _call(store, cid, gen, purpose, messages, source_hashes):
    route = ROUTES[purpose]
    key = credentials().get(route["key"])
    if not key: raise RuntimeError(f"{route['provider']} credentials are not configured. No fallback was attempted.")
    payload = {"model": route["model"], "messages": messages, "temperature": .15, "max_tokens": 32000 if purpose == "planner" else 8192}
    if purpose == "planner": payload["reasoning_effort"] = "high"
    else: payload["chat_template_kwargs"] = {"enable_thinking": True}
    request_hash = digest(payload)
    started = time.monotonic()
    receipt = {"schema_version": 1, "provider": route["provider"], "model": route["model"], "requested_at": now(), "request_hash": request_hash, "source_hashes": source_hashes, "settings": {k: v for k, v in payload.items() if k not in {"messages", "model"}}, "timeout_seconds": 480 if purpose == "planner" else 180, "status": "running", "reasoning_content_retained": False}
    call_id = store.provider_start(cid, gen, purpose, {k: receipt[k] for k in ("provider", "model", "request_hash", "settings", "source_hashes")})
    try:
        with httpx.Client(timeout=httpx.Timeout(receipt["timeout_seconds"], connect=20)) as client:
            response = client.post(route["url"], headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=payload)
        receipt["http_status"] = response.status_code
        receipt["request_id"] = response.headers.get("x-request-id") or response.headers.get("x-amzn-requestid")
        if response.status_code != 200:
            raise RuntimeError(f"{route['provider']} returned HTTP {response.status_code}; no fallback attempted")
        body = response.json()
        receipt["request_id"] = receipt["request_id"] or body.get("id")
        receipt["returned_model"] = body.get("model")
        receipt["usage"] = body.get("usage", {})
        usage = receipt["usage"]
        if "prompt_tokens" in usage and "completion_tokens" in usage:
            receipt["estimated_cost_usd"] = round((usage["prompt_tokens"]*route["input_rate"] + usage["completion_tokens"]*route["output_rate"])/1e6, 8)
        if body.get("model") != route["model"]:
            raise ValueError("Provider returned a different model identity; response not accepted")
        choices = body.get("choices") or []
        if not choices: raise ValueError("Provider returned no completion choices")
        content = choices[0].get("message", {}).get("content")
        receipt["finish_reason"] = choices[0].get("finish_reason")
        receipt["final_content"] = str(content or "")[:160000]
        if not isinstance(content, str) or not content.strip(): raise ValueError("Provider returned no final content")
        if receipt["finish_reason"] == "length": raise ValueError("Provider exhausted its completion allowance")
        result = strict_json(content)
        receipt["status"] = "received"
        return result, receipt, call_id
    except Exception as exc:
        receipt["status"] = "failed"
        receipt["error"] = f"{type(exc).__name__}: {exc}"[:600]
        receipt["elapsed_seconds"] = round(time.monotonic()-started, 3)
        store.provider_finish(call_id, "failed", receipt)
        raise
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic()-started, 3)

def plan_search(store, cid, gen, task, candidates, evidence):
    schema = {"hypotheses": [{"factor": "one registered factor name", "claim": "bounded mechanism", "evidence_episode_ids": ["an input episode id"]}], "search_order": ["candidate_id"], "rationale": "brief testable reasoning, not a verdict"}
    source = {"task": task, "candidates": candidates, "development_evidence": evidence}
    system = "You are the development experiment planner for FORGE. Analyze only authored local MuJoCo development evidence. Choose informative next trials from the finite supplied candidates. Cover both suspected failures and controls. Never invent episode outcomes, alter the task oracle, claim real robot or GR00T execution, or infer held-out results. This is instrumented-state control with a learned waypoint head. Return only JSON matching the schema. Schema: " + json.dumps(schema)
    result, receipt, call_id = _call(store, cid, gen, "planner", [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(source)}], {"task": digest(task), "development_evidence": digest(evidence), "candidate_pool": digest(candidates)})
    try:
        if not isinstance(result, dict) or set(result) != {"hypotheses", "search_order", "rationale"}: raise ValueError("Planner schema mismatch")
        ids = {c["candidate_id"] for c in candidates}
        order = result["search_order"]
        if not isinstance(order, list) or not 4 <= len(order) <= len(candidates) or len(set(order)) != len(order) or not set(order) <= ids: raise ValueError("Planner selected invalid or duplicate candidates")
        factors = set(candidates[0]["parameters"])
        evidence_ids = {e["id"] for e in evidence}
        if not isinstance(result["hypotheses"], list) or not 1 <= len(result["hypotheses"]) <= 6: raise ValueError("Planner hypotheses missing")
        for h in result["hypotheses"]:
            if set(h) != {"factor", "claim", "evidence_episode_ids"} or h["factor"] not in factors or not isinstance(h["claim"], str) or len(h["claim"]) > 1600 or not set(h["evidence_episode_ids"]) <= evidence_ids: raise ValueError("Ungrounded planner hypothesis")
        if not isinstance(result["rationale"], str) or len(result["rationale"]) > 2400: raise ValueError("Invalid planner rationale")
        receipt["status"] = "validated"
        sha = store.provider_finish(call_id, "validated", receipt)
        return {**result, "status": "validated", "provider": receipt["provider"], "model": receipt["model"], "receipt_sha": sha}
    except Exception as exc:
        receipt.update(status="schema_rejected", error=str(exc))
        store.provider_finish(call_id, "schema_rejected", receipt)
        raise

def analyze_render(store, cid, gen, image_paths, evidence):
    parts = [{"type": "text", "text": "Analyze these actual MuJoCo simulation render frames. Advisory image observations only; geometry/contact telemetry is authoritative. Do not claim hardware or infer unseen motion. Return only JSON {\"observations\":[{\"frame\":0,\"description\":\"visible fact\"}],\"hypothesis\":\"testable explanation with uncertainty\",\"limitations\":\"image limitations\"}. Frame order and measured evidence: " + json.dumps(evidence)}]
    hashes = {}
    for i, path in enumerate(image_paths):
        raw = Path(path).read_bytes()
        hashes[f"frame_{i}"] = hashlib.sha256(raw).hexdigest()
        parts.append({"type": "image_url", "image_url": {"url": "data:image/png;base64,"+base64.b64encode(raw).decode()}})
    result, receipt, call_id = _call(store, cid, gen, "visual", [{"role": "user", "content": parts}], hashes)
    try:
        if set(result) != {"observations", "hypothesis", "limitations"} or not isinstance(result["observations"], list) or not 1 <= len(result["observations"]) <= 8: raise ValueError("Visual schema mismatch")
        for item in result["observations"]:
            if set(item) != {"frame", "description"} or not isinstance(item["frame"], int) or not 0 <= item["frame"] < len(image_paths) or not isinstance(item["description"], str) or len(item["description"]) > 1600: raise ValueError("Invalid image reference")
        if any(not isinstance(result[k], str) or len(result[k]) > 2400 for k in ("hypothesis", "limitations")): raise ValueError("Invalid visual analysis")
        receipt["status"] = "validated"
        sha = store.provider_finish(call_id, "validated", receipt)
        return {**result, "status": "validated", "provider": receipt["provider"], "model": receipt["model"], "receipt_sha": sha, "frame_hashes": hashes}
    except Exception as exc:
        receipt.update(status="schema_rejected", error=str(exc))
        store.provider_finish(call_id, "schema_rejected", receipt)
        raise
