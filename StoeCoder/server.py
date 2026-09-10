"""Standalone StoeCoder UI launcher.

This keeps the preserved Navigator implementation under engine/v7 untouched while
reusing its current UI/API surface from the StoeCoder project directory.
"""

from pathlib import Path

import stoe_coder as _stoe_coder

REPO_ROOT = Path(__file__).resolve().parents[1]
_runtime = _stoe_coder.StoeCoderRuntime(repo_root=REPO_ROOT)
_stoe_coder.get_runtime = lambda: _runtime

from ui_server import app  # noqa: E402


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
