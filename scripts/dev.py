"""One cross-platform entry point for the Pod (Windows, macOS, Linux). Needs only Python 3.11+ (and Node for the UI).

  python scripts/dev.py setup        .venv + Python deps + .env (+ UI deps when npm is installed)
  python scripts/dev.py doctor       check Python, Node, the venv, ports
  python scripts/dev.py test         the whole test suite
  python scripts/dev.py run          every sample workflow and the Pod's own cases -> out/
  python scripts/dev.py case UNIT-0014 org_demo_alpha
  python scripts/dev.py serve        orchestrator API on :8100
  python scripts/dev.py ui           the UI on :5173 (expects the API on :8100)
  python scripts/dev.py up           API + UI together; Ctrl+C stops both

`make setup/test/run/serve` do the same on macOS/Linux; this script is for machines without make (most Windows ones).
Options: --api-port N, --ui-port N (serve/ui/up).
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
UI = ROOT / "ui"


def say(msg: str) -> None:
    print(f"[pod] {msg}", flush=True)


def need_python() -> None:
    if sys.version_info < (3, 11):
        sys.exit(f"Python 3.11+ is required (this is {sys.version.split()[0]}). Install it from python.org and re-run.")


def need_venv() -> None:
    if not VPY.exists():
        sys.exit("No .venv yet. Run:  python scripts/dev.py setup")


def npm() -> str | None:
    return shutil.which("npm")


def sh(cmd: list[str], cwd: Path = ROOT, env: dict | None = None) -> int:
    return subprocess.call(cmd, cwd=cwd, env={**os.environ, **(env or {})})


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def setup(args) -> int:
    need_python()
    if not VPY.exists():
        say(f"creating .venv with Python {sys.version.split()[0]}")
        venv.create(VENV, with_pip=True)
    say("installing Python dependencies (requirements.txt)")
    if sh([str(VPY), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt"]):
        return 1
    if not (ROOT / ".env").exists():
        shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
        say("created .env from .env.example (add API keys there only if you want live model modes)")
    if args.no_ui:
        return 0
    if not npm():
        say("npm not found: skipped the UI. Install Node.js 20.19+ (22 LTS recommended), then: python scripts/dev.py setup")
        return 0
    say("installing UI dependencies (npm ci)")
    return sh([npm(), "ci", "--no-audit", "--no-fund"], cwd=UI)


def doctor(args) -> int:
    ok = True
    py = sys.version_info
    say(f"python  {py.major}.{py.minor}.{py.micro}  {'ok' if py >= (3, 11) else 'TOO OLD: need 3.11+'}")
    ok &= py >= (3, 11)
    say(f".venv   {'ok' if VPY.exists() else 'missing: run setup'}")
    ok &= VPY.exists()
    node = shutil.which("node")
    ver = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip() if node else None
    say(f"node    {ver or 'missing (only the UI needs it)'}")
    say(f"ui deps {'ok' if (UI / 'node_modules').exists() else 'missing: run setup'}")
    say(f".env    {'present' if (ROOT / '.env').exists() else 'absent (optional; setup copies .env.example)'}")
    for port, what in ((args.api_port, "API"), (args.ui_port, "UI")):
        say(f"port {port} ({what}) {'free' if port_free(port) else 'IN USE: stop that process or pass --' + what.lower() + '-port'}")
    return 0 if ok else 1


def test(args) -> int:
    need_venv()
    extra = [a for a in (args.unit, args.org) if a] + args.rest  # e.g.  dev.py test tests/e2e -x
    return sh([str(VPY), "-m", "pytest", *extra])


def run(args) -> int:
    need_venv()
    env = {"LOG_LEVEL": os.environ.get("LOG_LEVEL", "WARNING")}
    rc = sh([str(VPY), "-m", "orchestration.run", "--all"], env=env)
    return rc or sh([str(VPY), "-m", "orchestration.run", "--all", "--cases", "data/input/my_cases.json"], env=env)


def case(args) -> int:
    need_venv()
    return sh([str(VPY), "-m", "orchestration.run", "--unit", args.unit, "--org", args.org])


def serve_cmd(port: int) -> list[str]:
    return [str(VPY), "-m", "uvicorn", "orchestration.api:app", "--port", str(port)]


def ui_cmd(port: int) -> list[str]:
    return [npm(), "run", "dev", "--", "--port", str(port), "--strictPort"]


def serve(args) -> int:
    need_venv()
    return sh(serve_cmd(args.api_port))


def ui(args) -> int:
    if not npm():
        sys.exit("npm not found. Install Node.js 20.19+ (22 LTS recommended).")
    if not (UI / "node_modules").exists():
        sys.exit("UI dependencies missing. Run:  python scripts/dev.py setup")
    return sh(ui_cmd(args.ui_port), cwd=UI, env={"ORCH_API_URL": f"http://127.0.0.1:{args.api_port}"})


def up(args) -> int:
    need_venv()
    if not npm() or not (UI / "node_modules").exists():
        sys.exit("The UI needs Node.js and `python scripts/dev.py setup` first.")
    for port in (args.api_port, args.ui_port):
        if not port_free(port):
            sys.exit(f"port {port} is in use. Stop that process, or pass --api-port / --ui-port.")
    api = subprocess.Popen(serve_cmd(args.api_port), cwd=ROOT)
    web = subprocess.Popen(ui_cmd(args.ui_port), cwd=UI,
                           env={**os.environ, "ORCH_API_URL": f"http://127.0.0.1:{args.api_port}"})
    say(f"API  http://127.0.0.1:{args.api_port}/health")
    say(f"UI   http://localhost:{args.ui_port}/   (control center: /overview)   Ctrl+C stops both")
    try:
        while api.poll() is None and web.poll() is None:
            try:
                api.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        for p in (web, api):
            if p.poll() is None:
                p.terminate()
        for p in (web, api):
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["setup", "doctor", "test", "run", "case", "serve", "ui", "up"])
    ap.add_argument("unit", nargs="?")
    ap.add_argument("org", nargs="?")
    ap.add_argument("--api-port", type=int, default=8100)
    ap.add_argument("--ui-port", type=int, default=5173)
    ap.add_argument("--no-ui", action="store_true", help="setup: skip npm ci")
    args, rest = ap.parse_known_args()
    args.rest = rest
    if args.command == "case" and not (args.unit and args.org):
        ap.error("case needs a unit and an org, e.g.  python scripts/dev.py case UNIT-0014 org_demo_alpha")
    return {"setup": setup, "doctor": doctor, "test": test, "run": run, "case": case, "serve": serve,
            "ui": ui, "up": up}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
