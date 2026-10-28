import importlib.util
from pathlib import Path
import socket
import subprocess
import sys
import time

spec=importlib.util.spec_from_file_location("forge_launcher",Path(__file__).parents[1]/"scripts"/"run.py")
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

def test_occupied_port_is_reported():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        assert not launcher.port_available(sock.getsockname()[1])

def test_termination_closes_grandchild_listener():
    grandchild="import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); print(s.getsockname()[1],flush=True); time.sleep(60)"
    parent=f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-u','-c',{grandchild!r}]); time.sleep(60)"
    process=subprocess.Popen([sys.executable,"-u","-c",parent],stdout=subprocess.PIPE,text=True,start_new_session=True)
    try:
        port=int(process.stdout.readline())
        with socket.create_connection(("127.0.0.1",port),timeout=2):pass
        launcher.terminate_group(process)
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            try:
                with socket.create_connection(("127.0.0.1",port),timeout=.1):pass
            except OSError:break
            time.sleep(.05)
        else:raise AssertionError("Grandchild listener survived process-group termination")
        assert process.poll() is not None
    finally:
        launcher.terminate_group(process)
