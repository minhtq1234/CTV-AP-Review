import os
import subprocess
import sys
from pathlib import Path


def test_smoke_fixture_rejects_missing_root_before_importing_app():
    script = """
import builtins
import importlib
import os

os.environ.pop("CTV_CCCD_SMOKE_ROOT", None)
real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "app":
        raise AssertionError("app must not import before the smoke-root guard")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
try:
    importlib.import_module("cccd_smoke_app")
except KeyError as error:
    assert error.args == ("CTV_CCCD_SMOKE_ROOT",)
else:
    raise AssertionError("fixture import unexpectedly succeeded without a smoke root")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_smoke_cccd_delay_spans_two_polling_intervals(tmp_path):
    script = """
import cccd_smoke_app

assert cccd_smoke_app.SMOKE_CCCD_DELAY_SECONDS == 3.2
"""
    env = {
        **os.environ,
        "CTV_CCCD_SMOKE_ROOT": str(tmp_path / "smoke-root"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parent,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
