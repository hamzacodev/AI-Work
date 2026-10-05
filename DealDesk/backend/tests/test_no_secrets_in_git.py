"""No secret may be tracked by git (CLAUDE.md rule 2). The same check runs as a pre-commit hook (scripts/check_secrets.py)."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_secrets", ROOT / "scripts" / "check_secrets.py")
check = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(check)  # type: ignore[union-attr]

in_git = shutil.which("git") is not None and subprocess.run(["git", "rev-parse"], cwd=ROOT, capture_output=True, check=False).returncode == 0
needs_git = pytest.mark.skipif(not in_git, reason="not inside a git checkout")


@needs_git
def test_no_tracked_file_has_a_key_or_a_real_env_file():
    assert check.problems() == []


def test_the_key_shapes_catch_real_looking_keys_and_ignore_the_demo_values():
    fake = ["gsk_" + "a1B2c3D4e5F6g7H8i9J0k1L2", "tvly-" + "dev-A1b2C3d4E5f6G7h8", "sk-or-v1-" + "a1b2c3d4e5f6a1b2c3d4e5f6", "-----BEGIN " + "PRIVATE KEY-----"]  # built from pieces so this file itself holds no key-shaped text
    assert all(check.KEY_SHAPES.search(x) for x in fake)
    assert not check.KEY_SHAPES.search("GROQ_API_KEY=  # fill in")
    assert check.ENV_FILE.search("backend/.env") and check.ENV_FILE.search("frontend/.env.local")
