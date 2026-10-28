"""Run the loopback API and frontend with owned process groups."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]

def port_available(port):
    with socket.socket() as sock:
        # A just-stopped server can leave TIME_WAIT sockets. Match the actual
        # HTTP servers' reuse behavior while still rejecting live listeners.
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:sock.bind(('127.0.0.1',port))
        except OSError:return False
    return True

def terminate_group(child):
    try:os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:child.wait(timeout=8)
    except subprocess.TimeoutExpired:pass
    # npm can exit while its Vite grandchild still owns the listener.
    try:
        os.killpg(child.pid,0)
        os.killpg(child.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    try:child.wait(timeout=2)
    except subprocess.TimeoutExpired:pass

def main():
    for port in (4401,4402):
        if not port_available(port):
            print(f'FORGE cannot start: loopback port {port} is already in use.',file=sys.stderr)
            return 1
    if not (ROOT/'dist'/'index.html').is_file():
        print('FORGE build missing. Run npm run build first.',file=sys.stderr)
        return 1
    children=[]
    stop_signal=[]
    def stop(signum,_frame):stop_signal.append(signum)
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    commands=[[sys.executable,'-m','uvicorn','control.main:app','--host','127.0.0.1','--port','4402','--no-access-log'],['npm','run','preview']]
    try:
        for command in commands:children.append(subprocess.Popen(command,cwd=ROOT,start_new_session=True))
        while not stop_signal:
            for i,child in enumerate(children):
                code=child.poll()
                if code is not None:
                    print(f'FORGE child {i} exited unexpectedly ({code}).',file=sys.stderr)
                    return code if code and code>0 else 1
            time.sleep(.2)
        return 128+stop_signal[0]
    finally:
        for child in children:terminate_group(child)

if __name__=='__main__':raise SystemExit(main())
