"""The whole demo in one command: `make demo-up` (after `make up` and `make web-install`).

    uv run python -m bench.demo_up

Seeds the demo store afresh (`make demo-seed`), then runs, until Ctrl+C: the demo API (recorded
model exchanges replayed at their pace, on the store's clock), the executor that carries out
approvals, the WhatsApp worker when WhatsApp is configured in `.env`, and the web app. Once
everything answers it prints the address to open: http://localhost:3000/demo, which opens the
demo store on Home, signed in as its owner, without an email. Never for real stores.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000/api/v1/ready"
WEB = "http://localhost:3000"
READY_S = 120


def say(text: str) -> None:
    print(text, flush=True)  # shown at once, even when the output goes to a file


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2):  # noqa: S310 (local addresses only)
            return True
    except (urllib.error.URLError, OSError):
        return False


def _wait(url: str, children: list[subprocess.Popen[bytes]]) -> bool:
    deadline = time.monotonic() + READY_S
    while time.monotonic() < deadline:
        if _answers(url):
            return True
        if any(child.poll() is not None for child in children):
            return False
        time.sleep(1)
    return False


def main() -> int:
    uv, npm = shutil.which("uv"), shutil.which("npm")
    if uv is None or npm is None:
        say("Needs uv and npm on the PATH (Node 20.19 or later).")
        return 1
    say("Seeding the demo store...")
    if subprocess.run([uv, "run", "python", "-m", "bench.demo_seed"], cwd=ROOT).returncode:  # noqa: S603
        say("The demo store could not be seeded: is `make up` running?")
        return 1
    serve = [uv, "run", "python", "-m", "bench.demo_serve"]
    commands = [[*serve, "api"], [*serve, "worker"]]
    whatsapp = get_settings().whatsapp_access_token is not None
    if whatsapp:
        commands.append([*serve, "whatsapp"])
    commands.append([npm, "run", "dev"])
    quiet = {**os.environ, "LOG_LEVEL": "WARNING"}  # the servers' warnings only
    children = [
        subprocess.Popen(  # noqa: S603
            command, cwd=ROOT / "frontend" if command[0] == npm else ROOT, env=quiet
        )
        for command in commands
    ]
    try:
        if not (_wait(API, children) and _wait(WEB, children)):
            say("The demo did not start: see the output above.")
            return 1
        say("\nThe demo is running. Open http://localhost:3000/demo")
        if whatsapp:
            say("WhatsApp: on (the worker answers the business number).")
        say("Ctrl+C stops everything.")
        while all(child.poll() is None for child in children):
            time.sleep(1)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    sys.exit(main())
