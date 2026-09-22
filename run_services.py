#!/usr/bin/env python3
"""
Multi-service orchestrator for the Microservices Blog Server.
Spawns each microservice (User, Blog, Comment, Payment) and the API Gateway
as concurrent processes and manages graceful shutdown.
"""

import os
import signal
import subprocess
import sys
import time

SERVICES = [
    ("User Service   ", "services.user.main:app", 8001),
    ("Blog Service   ", "services.blog.main:app", 8002),
    ("Comment Service", "services.comment.main:app", 8003),
    ("Payment Service", "services.payment.main:app", 8004),
    ("API Gateway    ", "services.gateway.main:app", 8000),
]

processes = []


def cleanup(signum=None, frame=None):
    print("\n🛑 Shutting down all microservices gracefully...")
    for name, proc in processes:
        if proc.poll() is None:
            print(f"Terminating {name} (PID {proc.pid})...")
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
    
    # Give processes a brief moment to terminate
    time.sleep(1)
    for name, proc in processes:
        if proc.poll() is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
    print("✅ All services stopped.")
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Prefer virtual environment python if present
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(workspace_dir, ".venv", "bin", "python")
    if os.path.exists(venv_python):
        python_executable = venv_python
    else:
        python_executable = sys.executable

    print("=" * 65)
    print("🚀 Starting Microservices Blog Platform")
    print(f"🐍 Python Executable: {python_executable}")
    print("=" * 65)

    for name, app_module, port in SERVICES:
        cmd = [
            python_executable,
            "-m",
            "uvicorn",
            app_module,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ]
        print(f"🔹 Launching [{name}] on http://127.0.0.1:{port}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        processes.append((name, proc))

    print("=" * 65)
    print("✨ All services launched!")
    print("🌐 Gateway / Docs: http://127.0.0.1:8000/docs")
    print("🩺 Health Check:  http://127.0.0.1:8000/health")
    print("Press Ctrl+C to stop all services.")
    print("=" * 65)

    try:
        while True:
            for name, proc in processes:
                # Print non-blocking logs if available
                line = proc.stdout.readline() if proc.stdout else ""
                if line:
                    print(f"[{name.strip()}] {line.strip()}")
                
                # Check if process exited unexpectedly
                code = proc.poll()
                if code is not None:
                    print(f"⚠️ {name} exited with code {code}!")
            time.sleep(0.05)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
