"""Checks that no secret is about to be shared. Run from the repo root:

    python3 scripts/check_secrets.py            # every file git tracks
    python3 scripts/check_secrets.py --staged   # only what is staged (used by the pre-commit hook)

It fails when (1) an env file with real values is tracked (only `.env.example` files may be), (2) a file contains a string shaped like a
real key (Groq, Tavily, OpenRouter, Supabase, Google, a JWT, a private key), or (3) a file contains the exact VALUE of a secret from your
local env files. Values are never printed, only the file names.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_SHAPES = re.compile(
    r"(gsk_[A-Za-z0-9]{20,}|tvly-[A-Za-z0-9\-]{16,}|sk-or-[A-Za-z0-9\-]{20,}|sb_secret_[A-Za-z0-9_\-]{10,}|"
    r"eyJhbGciOi[A-Za-z0-9_\-\.]{40,}|AIza[0-9A-Za-z_\-]{30,}|GOCSPX-[A-Za-z0-9_\-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
ENV_FILE = re.compile(r"(^|/)\.env(\..+)?$")
PUBLIC_BY_DESIGN = {"DEMO_PASSWORD", "DEMO_EMAIL"}  # the demo login shown to reviewers


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore", check=False).stdout  # binary files (pictures) decode to junk, never crash


def local_secret_values() -> dict[str, str]:
    """The real values in your own env files (git-ignored). Used only to check that none of them was copied anywhere else."""
    found: dict[str, str] = {}
    for path in (ROOT / "backend" / ".env", ROOT / "frontend" / ".env.local", ROOT / "frontend" / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(errors="ignore").splitlines():
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$", line)
            if m and m.group(1) not in PUBLIC_BY_DESIGN and re.search(r"KEY|SECRET|TOKEN|PASSWORD", m.group(1)):
                value = m.group(2).strip("\"'")
                if len(value) >= 8:
                    found[m.group(1)] = value
    return found


def problems(staged: bool = False) -> list[str]:
    files = [f for f in (git("diff", "--cached", "--name-only", "--diff-filter=ACM") if staged else git("ls-files")).split("\n") if f]
    values = local_secret_values()
    out: list[str] = []
    for f in files:
        if ENV_FILE.search(f) and not f.endswith(".example"):
            out.append(f"{f}: an env file must never be tracked (only .env.example)")
            continue
        path = ROOT / f
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        text = (git("show", f":{f}") if staged else path.read_text(errors="ignore")) or ""
        if KEY_SHAPES.search(text):
            out.append(f"{f}: contains a string shaped like a real key")
        for name, value in values.items():
            if value in text:
                out.append(f"{f}: contains the value of {name}")
    return out


if __name__ == "__main__":
    found = problems("--staged" in sys.argv)
    for p in found:
        print("SECRET CHECK FAILED:", p)
    print("secret check: " + ("FAILED, nothing was shared" if found else "ok, no secrets found"))
    sys.exit(1 if found else 0)
