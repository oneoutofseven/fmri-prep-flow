"""Wait for a container process and clean up its process group on interruption."""

import os
import signal
import subprocess


def execute(argv, log_path, environment=None, on_start=None):
    previous = signal.getsignal(signal.SIGTERM)
    process = None

    def interrupted(signum, frame):
        raise KeyboardInterrupt("Termination requested")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        with open(log_path, "x") as log:
            process = subprocess.Popen(
                argv, stdout=log, stderr=subprocess.STDOUT, env=environment, start_new_session=True
            )
            if on_start:
                on_start(process.pid)
            return process.wait()
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        signal.signal(signal.SIGTERM, previous)
