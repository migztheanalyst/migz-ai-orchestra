"""Shared bounded subprocess primitives for Orchestra runtime code."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Mapping, Sequence


def merged_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    return env


def run_bounded(
    command: Sequence[str],
    *,
    cwd: str | Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    combine_output: bool = False,
    merge_env: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run an argument-vector command with a hard timeout and no shell."""
    if env is None:
        child_env = None
    elif merge_env:
        child_env = merged_env(env)
    else:
        child_env = {str(key): str(value) for key, value in env.items()}

    if combine_output and not capture_output:
        raise ValueError("combine_output requires capture_output")

    kwargs = {
        "cwd": Path(cwd),
        "input": input_text,
        "text": True,
        "timeout": timeout,
        "env": child_env,
        "shell": False,
    }
    if capture_output:
        if combine_output:
            kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        else:
            kwargs["capture_output"] = True
    return subprocess.run([str(part) for part in command], **kwargs)


def run_live_bounded(
    command: Sequence[str],
    *,
    cwd: str | Path,
    heartbeat: Callable[[], None],
    timeout: float,
    env: Mapping[str, str] | None = None,
    heartbeat_interval: float = 45.0,
    poll_interval: float = 1.0,
) -> subprocess.CompletedProcess[str]:
    """Run a long command with bounded lifetime, merged logs, and heartbeat."""
    fd, name = tempfile.mkstemp(prefix="migz-live-", suffix=".log")
    os.close(fd)
    log_path = Path(name)
    try:
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [str(part) for part in command],
                cwd=Path(cwd),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
                env=merged_env(env),
            )
            last_heartbeat = time.monotonic()
            deadline = last_heartbeat + timeout
            try:
                while proc.poll() is None:
                    now = time.monotonic()
                    if now - last_heartbeat >= heartbeat_interval:
                        heartbeat()
                        last_heartbeat = now
                    if now >= deadline:
                        _terminate_process(proc)
                        log.flush()
                        os.fsync(log.fileno())
                        text = log_path.read_text(encoding="utf-8", errors="replace")
                        return subprocess.CompletedProcess(command, 124, text, "bounded process timeout")
                    time.sleep(poll_interval)
            finally:
                if proc.poll() is None:
                    _terminate_process(proc)
        text = log_path.read_text(encoding="utf-8", errors="replace")
        return subprocess.CompletedProcess(command, proc.returncode, text, "")
    finally:
        log_path.unlink(missing_ok=True)


def _terminate_process(proc: subprocess.Popen[str], grace_seconds: float = 10.0) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=grace_seconds)
