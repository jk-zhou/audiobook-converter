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
