"""Fenced episode execution and immutable engine evidence persistence."""
import json
import time
from engine import run_episode, TASK_SPEC_HASH
from .store import digest, FenceLost

class RunContext:
    def __init__(self, store, cid, generation):
        self.store, self.cid, self.gen = store, cid, generation
        self.campaign = store.get(cid, detail=False)
        self.config = self.campaign["config"]
        if self.config["task_sha"] != TASK_SPEC_HASH: raise ValueError("Frozen task revision no longer matches this engine")
        self.base_index = json.loads((store.path/"base"/"index.json").read_text())
        self.base = store.read_artifact(self.config["base_checkpoint_sha"])
        self.started = time.perf_counter()
        self._cancel_checked, self._canceled = 0., False

    def state(self): return self.store.get(self.cid, detail=False)
    def boundary(self): self.store.boundary(self.cid,self.gen)
    def canceled(self):
        clock = time.monotonic()
        if clock-self._cancel_checked > .08:
            self._canceled = self.store.canceled(self.cid,self.gen)
            self._cancel_checked = clock
        return self._canceled

    def update(self, stage, completed, total, message, **patch):
        self.store.progress(self.cid,self.gen,stage,completed,total,message,patch)

    def run(self, scene, policy=None, purpose="discovery", trace=False):
        self.boundary()
        policy = policy or self.base
        identity = digest({"scenario":scene,"policy":policy["checkpoint_hash"],"purpose":purpose,"rich_trace":bool(trace),"task":TASK_SPEC_HASH})
        ident = self.cid+"-e"+identity[:14]
        old = self.store.existing_episode(self.cid,identity)
        if old is not None: return self._result(ident,old)
        try:
            episode = run_episode(scene,policy,trace=trace,cancel_callback=self.canceled)
        except ValueError as exc:
            episode = {"schema":"forge.invalid-reset/v1","episode_id":ident,"status":"invalid_scene","success":None,"scenario":scene,"terminal_reason":"invalid_scene","error":str(exc),"task_spec_hash":TASK_SPEC_HASH,"simulation_only":True,"policy":{"policy_id":policy["policy_id"],"checkpoint_hash":policy["checkpoint_hash"]},"trace":{"recorded":False,"frames":[]},"metrics":{}}
        if episode["status"] == "interrupted":
            self.store.artifact({"kind":"interrupted_attempt","campaign_id":self.cid,"generation":self.gen,"episode":episode})
            raise FenceLost("Partial episode interrupted; no task verdict accepted")
        summary = {"id":ident,"engine_episode_id":episode["episode_id"],"scenario":scene,"policy_id":policy["policy_id"],"checkpoint_hash":policy["checkpoint_hash"],"purpose":purpose,"success":episode.get("success"),"valid":episode["status"]=="completed","outcome":"success" if episode.get("success") else episode.get("terminal_reason","invalid"),"terminal_reason":episode.get("terminal_reason"),"status":episode["status"],"metrics":episode.get("metrics",{}),"trace_available":bool(episode.get("trace",{}).get("recorded"))}
        self.store.save_episode(self.cid,self.gen,identity,episode,summary)
        return self._result(ident,episode)

    def _result(self, ident, episode):
        return {"id":ident,"episode":episode,"valid":episode["status"]=="completed","success":episode.get("success"),"scenario":episode["scenario"],"terminal_reason":episode.get("terminal_reason")}

    def base_demos(self): return [self.store.read_artifact(sha) for sha in self.base_index["demo_shas"]]
