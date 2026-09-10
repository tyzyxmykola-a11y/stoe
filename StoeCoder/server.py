"""Standalone StoeCoder UI launcher.

This keeps the preserved Navigator implementation under engine/v7 untouched while
reusing its current UI/API surface from the StoeCoder project directory.
"""

from ui_server import app


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
