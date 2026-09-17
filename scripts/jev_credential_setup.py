#!/usr/bin/env python3
"""Install TypeSafe credential outside the repo, then run the Jev canary."""
import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))
from decision_layer import DEFAULT_CREDENTIAL_PATH

def main():
    target = DEFAULT_CREDENTIAL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    secret = getpass.getpass("TypeSafe API key (hidden): ").strip()
    if not secret:
        print("JEV_CREDENTIAL_SETUP: FAIL | empty credential", file=sys.stderr)
        return 2
    fd, name = tempfile.mkstemp(prefix="typesafe-", dir=target.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secret + "\n")
        os.replace(name, target)
        os.chmod(target, 0o600)
    finally:
        Path(name).unlink(missing_ok=True)
    secret = ""
    print(f"Credential installed securely at {target} (mode 600).")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "jev_canary.py")], cwd=ROOT)
    return proc.returncode

if __name__ == "__main__":
    raise SystemExit(main())
