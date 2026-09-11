"""Standalone StoeCoder UI launcher.

This keeps the preserved Navigator implementation under engine/v7 untouched while
reusing its current UI/API surface from the StoeCoder project directory.
"""

from ui_server import app, coder, _coder_local_request
from event_logging import install_event_logging
from role_config_isolation import install_role_config_isolation
from repository_navigation import install_repository_navigation, install_information_gain_tracking
from inspection_navigation import install_inspection_navigation
from anti_loop import install_anti_loop
from verification_policy import install_verification_policy
from workflow_guard import install_workflow_guard
from workflow_controls import install_workflow_controls
from diagnostic_logging import install_diagnostic_logging
from model_io import install_model_io_capture, install_model_io_ui

install_event_logging(coder)
install_role_config_isolation(coder)
install_repository_navigation(coder)
install_inspection_navigation(coder)
install_anti_loop(coder)
install_information_gain_tracking(coder)
install_verification_policy(coder)
install_workflow_guard(coder)
install_workflow_controls(coder)
install_diagnostic_logging(coder)
install_model_io_capture(coder)
install_model_io_ui(app, coder, _coder_local_request)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
