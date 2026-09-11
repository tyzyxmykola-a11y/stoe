"""Standalone StoeCoder UI launcher.

This keeps the preserved Navigator implementation under engine/v7 untouched while
reusing its current UI/API surface from the StoeCoder project directory.
"""

from ui_server import app, coder, _coder_local_request
from event_logging import install_event_logging
from anti_loop import install_anti_loop
from diagnostic_logging import install_diagnostic_logging
from model_io import install_model_io_capture, install_model_io_ui

install_event_logging(coder)
install_anti_loop(coder)
install_diagnostic_logging(coder)
install_model_io_capture(coder)
install_model_io_ui(app, coder, _coder_local_request)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
