"""Single local worker, process-group cancellation, fenced restart recovery."""
import os
import signal
import subprocess
import sys
import time
from .store import ROOT

class Supervisor:
    def __init__(self, store):
        self.store = store
        self.children = {}

    def start(self, cid):
        info = self.store.launch_info(cid)
        if info["status"] not in {"queued", "pause_requested"}: return
        existing = self.children.get(cid)
        if existing and existing.poll() is None: return
        logpath = self.store.path / "logs" / f"{cid}-g{info['generation']}.log"
        module="control.final_worker" if info["operation"]=="registered_evaluation" else "control.worker"
        with logpath.open("ab") as output:
            child = subprocess.Popen([sys.executable, "-m", module, cid, str(info["generation"]), info["worker_token"]], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, start_new_session=True, env={**os.environ, "FORGE_DATA_DIR": str(self.store.path), "PYTHONUNBUFFERED": "1"})
        self.children[cid] = child

    def _matching(self, pid, token):
        if not pid: return False
        try:
            command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True, stderr=subprocess.DEVNULL)
            return ("control.worker" in command or "control.final_worker" in command) and token in command
        except subprocess.CalledProcessError: return False

    def terminate(self, info):
        child = self.children.get(info["id"])
        pid = child.pid if child else info.get("pid")
        if pid and (child and child.poll() is None or self._matching(pid, info.get("worker_token", ""))):
            try: os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError: pass
            until = time.monotonic()+3
            while time.monotonic()<until:
                if child:
                    if child.poll() is not None: break
                elif not self._matching(pid, info.get("worker_token", "")): break
                time.sleep(.05)
            else:
                try: os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError: pass
            if child: child.wait(timeout=3)
            elif self._matching(pid, info.get("worker_token", "")): raise RuntimeError("Worker termination unconfirmed")

    def cancel(self, cid):
        info = self.store.launch_info(cid)
        self.terminate(info)
        self.store.terminated(cid, info["generation"])

    def recover(self):
        for old in self.store.recover(): self.terminate(old)

    def reap(self):
        for cid, child in list(self.children.items()):
            exit_code = child.poll()
            if exit_code is None: continue
            state = self.store.get(cid, detail=False)
            if state["status"] in {"queued", "running", "pause_requested"}:
                self.store.finish(cid, state["generation"], "failed", state["stage"], error=f"Local worker exited ({exit_code}) before committing a phase. Partial trajectories excluded; resume restarts the incomplete phase.")
            del self.children[cid]

    def shutdown(self): self.recover()
