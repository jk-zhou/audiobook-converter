"""Shared helpers for browser E2E scripts (playwright, user-perspective)."""
import json
import os
import sys
from pathlib import Path

BASE = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8765")
SHOTS = Path(os.getenv("E2E_SHOTS", "/tmp/hac-shots"))
SHOTS.mkdir(parents=True, exist_ok=True)
RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"{'✓' if cond else '✗'} {name} {detail}")


def report(part):
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n== {part}: {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ==")
    return 1 if fails else 0


def exit_code():
    return 1 if any(not r[1] for r in RESULTS) else 0


def ffprobe(path):
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", "-show_chapters", str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


_spawned_servers = []


def restart_server():
    """Kill the e2e uvicorn and relaunch it with identical env/data dir.

    Lets part scripts verify DB-backed persistence across a real restart.
    """
    import os
    import signal
    import subprocess
    import time

    port = os.environ["E2E_BASE_URL"].rsplit(":", 1)[1]
    data_dir = os.environ["E2E_DATA"]
    # find and kill the uvicorn listening on the e2e port
    out = subprocess.run(["pkill", "-f", f"uvicorn hac.main:app --host 127.0.0.1 --port {port}"])
    for _ in range(20):
        r = subprocess.run(["curl", "-sf", "-m", "1",
                            f"{os.environ['E2E_BASE_URL']}/api/health"],
                           capture_output=True)
        if r.returncode != 0:
            break
        time.sleep(0.3)
    env = dict(os.environ)
    env["HAC_DATA_DIR"] = data_dir
    log = open("/tmp/opencode/e2e-restart-server.log", "w")
    proc = subprocess.Popen(
        [".venv/bin/uvicorn", "hac.main:app", "--host", "127.0.0.1", "--port", port],
        env=env, stdout=log, stderr=subprocess.STDOUT,
        cwd=os.environ.get("E2E_ROOT", os.getcwd()))
    _spawned_servers.append(proc)
    import atexit
    atexit.register(_kill_spawned)
    for _ in range(40):
        r = subprocess.run(["curl", "-sf", "-m", "1",
                            f"{os.environ['E2E_BASE_URL']}/api/health"],
                           capture_output=True)
        if r.returncode == 0:
            return True
        time.sleep(0.5)
    raise RuntimeError("server did not come back after restart")


def _kill_spawned():
    import signal
    for proc in _spawned_servers:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
    _spawned_servers.clear()
