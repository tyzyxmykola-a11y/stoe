@echo off
setlocal

set "STOE_PYTHON=%USERPROFILE%\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
if exist "%STOE_PYTHON%" (
  "%STOE_PYTHON%" -c "import mcp" >nul 2>nul
  if not errorlevel 1 goto run_server
)

set "STOE_PYTHON=python"
%STOE_PYTHON% -c "import mcp" >nul 2>nul
if errorlevel 1 goto missing_runtime

:run_server
"%STOE_PYTHON%" "%~1"
exit /b %errorlevel%

:missing_runtime
echo SToE Memory requires a Python runtime containing the mcp package. 1>&2
exit /b 1
