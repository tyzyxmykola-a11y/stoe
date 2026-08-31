#!/usr/bin/env python3
"""
SToE Information Field — Quick Start
Run this to start the navigator server.
"""
import subprocess
import sys
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
VERSION = os.getenv("VERSION", "v82")
import webbrowser
import time

os.chdir(os.path.dirname(__file__))

print(f"""
╔══════════════════════════════════════════════╗
║  SToE Information Field Navigator  {VERSION}      ║
║  Special Theory of Everything — M. Voronin  ║
╚══════════════════════════════════════════════╝

Starting server...
""")

# Start server
proc = subprocess.Popen([sys.executable, "server.py"])
time.sleep(1.5)

print("✓ Server running at http://localhost:5000")
print("✓ Open in your browser to navigate the field")
print("\nPress Ctrl+C to stop\n")

try:
    webbrowser.open("http://localhost:5000")
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()
    print("\nField server stopped.")
