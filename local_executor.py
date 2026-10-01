#!/usr/bin/env python3
"""
OmniShell Host Execution Agent V4

A local host bridge for OmniShell.

Features
--------
- Cross-platform execution: Linux / macOS / Windows
- Execution IDs and execution history in memory
- Synchronous and asynchronous execution
- Cancellation of process trees
- Timeout handling
- stdout/stderr capture
- Live output callbacks internally
- Working-directory support
- Controlled environment overrides
- Risk classification
- Optional execution-policy enforcement
- Dry-run support
- System reconnaissance
- Process inspection
- Browser/terminal/tool discovery
- Post-execution verification hooks
- Guaranteed temporary-file cleanup
- BrokenPipe-safe HTTP responses
- Backward-compatible POST /execute endpoint

Security model
--------------
This service executes commands on the HOST machine. It should only listen on
localhost unless you deliberately add authentication and a remote deployment
model.

For additional protection, set:

    OMNISHELL_ENFORCE_POLICY=true

When enabled, destructive/critical commands require:

    "approved": true

in the /execute request.

Default:
    OMNISHELL_ENFORCE_POLICY=false

The existing OmniShell flow can therefore continue to work while the policy
layer is introduced gradually.
"""

from __future__ import annotations

import http.server
import json
import os
import platform
import re
import shlex
import shutil
import signal
import socketserver
import subprocess
import threading
import time
import tempfile
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


HOST = os.getenv("OMNISHELL_HOST", "127.0.0.1")
PORT = int(os.getenv("OMNISHELL_PORT", "8003"))

DEFAULT_TIMEOUT = float(
    os.getenv("OMNISHELL_DEFAULT_TIMEOUT", "300")
)

MAX_TIMEOUT = float(
    os.getenv("OMNISHELL_MAX_TIMEOUT", "3600")
)

ENFORCE_POLICY = (
    os.getenv("OMNISHELL_ENFORCE_POLICY", "false").lower()
    in {"1", "true", "yes", "on"}
)

# Critical/high-risk host mutations require explicit approval by default.
# OMNISHELL_ENFORCE_POLICY can still be enabled to apply the same gate to all
# policy-classified commands; this separate switch makes dangerous operations
# fail closed even when legacy deployments leave ENFORCE_POLICY disabled.
REQUIRE_RISK_APPROVAL = (
    os.getenv("OMNISHELL_REQUIRE_RISK_APPROVAL", "true").lower()
    in {"1", "true", "yes", "on"}
)

MAX_HISTORY = int(
    os.getenv("OMNISHELL_MAX_HISTORY", "500")
)

MAX_RECOVERY_ATTEMPTS = int(
    os.getenv("OMNISHELL_MAX_RECOVERY_ATTEMPTS", "5")
)

EXECUTION_BUDGET_SECONDS = float(
    os.getenv("OMNISHELL_EXECUTION_BUDGET_SECONDS", "300")
)

MAX_OUTPUT_BYTES = int(
    os.getenv("OMNISHELL_MAX_OUTPUT_BYTES", str(10 * 1024 * 1024))
)

SCHEDULER_UPLOAD_MAX_ATTEMPTS = int(
    os.getenv("OMNISHELL_UPLOAD_MAX_ATTEMPTS", "5")
)

SCHEDULER_UPLOAD_BUDGET_SECONDS = float(
    os.getenv("OMNISHELL_UPLOAD_BUDGET_SECONDS", "30")
)



# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class ExecutionResult:
    execution_id: str
    status: str
    success: bool
    exit_code: Optional[int]
    signal: Optional[int]
    command: str
    shell: str
    shell_path: str
    os: str
    architecture: str
    working_directory: str
    stdout: str
    stderr: str
    output: str
    duration_ms: int
    timed_out: bool
    cancelled: bool
    risk_level: str
    risk_reasons: list[str] = field(default_factory=list)
    process_pid: Optional[int] = None
    process_detected: bool = False
    expected_process: Optional[str] = None
    verification: dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0
    attempt: int = 1
    max_attempts: int = 1
    recovery_action: Optional[str] = None
    verification_passed: bool = True
    idempotency_key: Optional[str] = None
    budget_exhausted: bool = False
    safety_decision: Optional[str] = None


@dataclass
class ExecutionTask:
    execution_id: str
    command: str
    process: Optional[subprocess.Popen] = None
    started_at: float = 0.0
    cancelled: bool = False
    finished: bool = False
    result: Optional[ExecutionResult] = None
    output_lines: list[str] = field(default_factory=list)


# ============================================================
# EXECUTION REGISTRY
# ============================================================

class ExecutionRegistry:
    def __init__(self, max_history: int = MAX_HISTORY):
        self._lock = threading.RLock()
        self._tasks: dict[str, ExecutionTask] = {}
        self._history: list[ExecutionResult] = []
        self._max_history = max_history

    def create(self, command: str, execution_id: Optional[str] = None) -> ExecutionTask:
        execution_id = execution_id or uuid.uuid4().hex

        task = ExecutionTask(
            execution_id=execution_id,
            command=command,
            started_at=time.time(),
        )

        with self._lock:
            self._tasks[execution_id] = task

        return task

    def get(self, execution_id: str) -> Optional[ExecutionTask]:
        with self._lock:
            return self._tasks.get(execution_id)

    def finish(
        self,
        execution_id: str,
        result: ExecutionResult,
    ) -> None:
        with self._lock:
            task = self._tasks.get(execution_id)

            if task:
                task.finished = True
                task.result = result

            self._history.append(result)

            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def all_history(self) -> list[ExecutionResult]:
        with self._lock:
            return list(reversed(self._history))

    def active(self) -> list[ExecutionTask]:
        with self._lock:
            return [
                task
                for task in self._tasks.values()
                if not task.finished
            ]

    def cancel(self, execution_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(execution_id)

            if not task or task.finished:
                return False

            task.cancelled = True
            process = task.process

        if process:
            terminate_process_tree(process)
            return True

        return True


REGISTRY = ExecutionRegistry()

# Short-lived idempotency memory prevents accidental duplicate execution when
# a client retries the same request after a network timeout.
_IDEMPOTENCY_LOCK = threading.RLock()
_IDEMPOTENCY_RESULTS: dict[str, ExecutionResult] = {}
_IDEMPOTENCY_MAX = int(os.getenv("OMNISHELL_IDEMPOTENCY_MAX", "1000"))

def _idempotency_get(key: Optional[str]) -> Optional[ExecutionResult]:
    if not key:
        return None
    with _IDEMPOTENCY_LOCK:
        return _IDEMPOTENCY_RESULTS.get(key)

def _idempotency_put(key: Optional[str], result: ExecutionResult) -> None:
    if not key:
        return
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY_RESULTS[key] = result
        if len(_IDEMPOTENCY_RESULTS) > _IDEMPOTENCY_MAX:
            for old_key in list(_IDEMPOTENCY_RESULTS)[:len(_IDEMPOTENCY_RESULTS) - _IDEMPOTENCY_MAX]:
                _IDEMPOTENCY_RESULTS.pop(old_key, None)


# ============================================================
# GENERAL UTILITIES
# ============================================================

def now_ms() -> int:
    return int(time.time() * 1000)


def safe_decode(data: bytes) -> str:
    return data.decode(
        "utf-8",
        errors="replace",
    )


def clamp_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT

    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT

    return min(timeout, MAX_TIMEOUT)


def normalize_working_directory(
    working_directory: Optional[str],
) -> str:
    if not working_directory:
        return os.getcwd()

    path = os.path.abspath(
        os.path.expanduser(
            os.path.expandvars(
                working_directory
            )
        )
    )

    if not os.path.isdir(path):
        raise ValueError(
            f"Working directory does not exist: {path}"
        )

    return path


def sanitize_environment(
    overrides: Optional[dict[str, Any]],
) -> dict[str, str]:
    """
    Only accept string-like environment values.

    Environment variables are inherited from the local executor process and
    can optionally be overridden by the caller.
    """

    environment = os.environ.copy()

    if not overrides:
        return environment

    for key, value in overrides.items():

        if not isinstance(key, str):
            continue

        if not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*",
            key,
        ):
            raise ValueError(
                f"Invalid environment variable name: {key}"
            )

        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = str(value)

    return environment


# ============================================================
# PLATFORM / SHELL DETECTION
# ============================================================

def detect_shell() -> tuple[str, str]:
    system = platform.system().lower()

    if system == "windows":
        powershell = shutil.which("pwsh")

        if powershell:
            return "powershell", powershell

        powershell = shutil.which("powershell")

        if powershell:
            return "powershell", powershell

        cmd = shutil.which("cmd")

        return (
            "cmd",
            cmd or "C:\\Windows\\System32\\cmd.exe",
        )

    shell = os.environ.get("SHELL")

    if shell and os.path.exists(shell):
        return Path(shell).name, shell

    for candidate in (
        "/bin/bash",
        "/usr/bin/bash",
        "/bin/zsh",
        "/usr/bin/zsh",
        "/bin/sh",
    ):
        if os.path.exists(candidate):
            return Path(candidate).name, candidate

    return "sh", "/bin/sh"


def find_terminal() -> Optional[str]:
    if platform.system().lower() == "windows":
        return None

    terminals = [
        "gnome-terminal",
        "konsole",
        "xfce4-terminal",
        "xterm",
        "x-terminal-emulator",
    ]

    for terminal in terminals:
        if shutil.which(terminal):
            return terminal

    return None


# ============================================================
# SYSTEM RECONNAISSANCE
# ============================================================

def command_version(command: str) -> Optional[str]:
    executable = shutil.which(command)

    if not executable:
        return None

    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
        )

        output = (
            result.stdout or result.stderr
        ).strip()

        return output.splitlines()[0] if output else None

    except Exception:
        return None


def get_installed_browsers() -> list[str]:
    browsers: set[str] = set()

    if platform.system().lower() == "windows":
        try:
            import winreg

            browsers.add("Edge")

            registry_path = (
                r"SOFTWARE\Clients\StartMenuInternet"
            )

            for hkey in (
                winreg.HKEY_LOCAL_MACHINE,
                winreg.HKEY_CURRENT_USER,
            ):
                try:
                    with winreg.OpenKey(
                        hkey,
                        registry_path,
                    ) as key:

                        count = winreg.QueryInfoKey(key)[0]

                        for index in range(count):
                            try:
                                browser_key = (
                                    winreg.EnumKey(
                                        key,
                                        index,
                                    )
                                )

                                try:
                                    with winreg.OpenKey(
                                        key,
                                        f"{browser_key}\\Capabilities",
                                    ) as capability_key:

                                        name = winreg.QueryValueEx(
                                            capability_key,
                                            "ApplicationName",
                                        )[0]

                                        browsers.add(name)

                                except FileNotFoundError:
                                    browsers.add(browser_key)

                            except OSError:
                                continue

                except FileNotFoundError:
                    continue

        except Exception:
            pass

    else:
        candidates = {
            "google-chrome": "Google Chrome",
            "google-chrome-stable": "Google Chrome",
            "brave-browser": "Brave",
            "firefox": "Firefox",
            "chromium": "Chromium",
            "chromium-browser": "Chromium",
        }

        for command, name in candidates.items():
            if shutil.which(command):
                browsers.add(name)

    return sorted(browsers)


def get_system_info() -> dict[str, Any]:
    shell_name, shell_path = detect_shell()

    tools = {}

    for command in (
        "git",
        "docker",
        "python",
        "python3",
        "node",
        "npm",
        "pnpm",
        "yarn",
        "pip",
        "pip3",
        "curl",
        "wget",
        "jq",
        "ffmpeg",
        "ssh",
    ):
        path = shutil.which(command)

        tools[command] = {
            "installed": path is not None,
            "path": path,
            "version": (
                command_version(command)
                if path
                else None
            ),
        }

    return {
        "os": platform.system(),
        "platform": platform.platform(),
        "distribution": (
            platform.freedesktop_os_release()
            if hasattr(platform, "freedesktop_os_release")
            and platform.system() == "Linux"
            else {}
        ),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "hostname": platform.node(),
        "username": (
            os.environ.get("USERNAME")
            or os.environ.get("USER")
            or "unknown"
        ),
        "home": os.path.expanduser("~"),
        "cwd": os.getcwd(),
        "shell": shell_name,
        "shell_path": shell_path,
        "terminal": find_terminal(),
        "browsers": get_installed_browsers(),
        "tools": tools,
    }


def get_realtime_metrics() -> dict[str, Any]:
    """Gather real-time CPU, RAM, disk, network, and uptime metrics."""
    metrics: dict[str, Any] = {
        "timestamp": time.time(),
        "os": platform.system(),
        "cpu_count": os.cpu_count() or 1,
    }
    try:
        import psutil
        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        metrics["memory"] = {
            "total_mb": round(mem.total / (1024 * 1024), 1),
            "available_mb": round(mem.available / (1024 * 1024), 1),
            "used_mb": round(mem.used / (1024 * 1024), 1),
            "percent": mem.percent,
        }
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        metrics["disk"] = {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_gb": round(disk.used / (1024 ** 3), 2),
            "free_gb": round(disk.free / (1024 ** 3), 2),
            "percent": disk.percent,
        }
        metrics["boot_time"] = psutil.boot_time()
        metrics["uptime_seconds"] = int(time.time() - psutil.boot_time())
    except Exception as exc:
        metrics["psutil_error"] = str(exc)

    return metrics


def send_desktop_notification(title: str, message: str) -> bool:
    """Trigger a native cross-platform desktop alert/notification."""
    system = platform.system().lower()
    try:
        if system == "linux":
            if shutil.which("notify-send"):
                subprocess.Popen(["notify-send", title, message])
                return True
        elif system == "darwin":
            script = f'display notification "{message}" with title "{title}"'
            subprocess.Popen(["osascript", "-e", script])
            return True
        elif system == "windows":
            ps_cmd = f'[reflection.assembly]::loadwithpartialname("System.Windows.Forms"); [System.Windows.Forms.MessageBox]::Show("{message}", "{title}")'
            subprocess.Popen(["powershell", "-Command", ps_cmd])
            return True
    except Exception as e:
        print(f"[HOST AGENT] Notification error: {e}")
    return False


def execute_with_recovery(
    command: str,
    *,
    working_directory: Optional[str] = None,
    approved: bool = False,
    max_attempts: int = 2,
    retry_on: Optional[list[str]] = None,
    backoff_seconds: Optional[list[float]] = None,
    expected_process: Optional[str] = None,
    expected_path: Optional[str] = None,
    expected_absent_path: Optional[str] = None,
    fallback_script: Optional[str] = None,
    diagnostic_command: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    execution_id: Optional[str] = None,
    environment: Optional[dict[str, Any]] = None,
    timeout: Any = None,
    dry_run: bool = False,
    deadline: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
) -> ExecutionResult:
    """Execute a command with bounded retries, diagnostics and optional fallback.

    Retries are only attempted for transient failures. Destructive/critical
    commands are never blindly retried. A successful result is cached by the
    optional idempotency key so network-level retries cannot duplicate work.
    """
    cached = _idempotency_get(idempotency_key)
    if cached:
        return cached

    max_attempts = max(1, min(int(max_attempts or 1), MAX_RECOVERY_ATTEMPTS))
    retry_on = set(retry_on or ["timeout", "connection", "transient"])
    backoff_seconds = backoff_seconds or [1.0, 3.0]
    effective_deadline = deadline if deadline is not None else (time.monotonic() + EXECUTION_BUDGET_SECONDS)
    last: Optional[ExecutionResult] = None

    for attempt in range(1, max_attempts + 1):
        if cancel_event is not None and cancel_event.is_set():
            now = time.time()
            return ExecutionResult(
                execution_id=execution_id or uuid.uuid4().hex, status="cancelled", success=False,
                exit_code=None, signal=None, command=command, shell=detect_shell()[0], shell_path=detect_shell()[1],
                os=platform.system(), architecture=platform.machine(), working_directory=working_directory or os.getcwd(),
                stdout="", stderr="Execution cancelled by scheduler/user.", output="Execution cancelled by scheduler/user.",
                duration_ms=0, timed_out=False, cancelled=True, risk_level=classify_command(command)["level"],
                risk_reasons=classify_command(command)["reasons"], started_at=now, finished_at=now,
                verification_passed=False, safety_decision="cancelled",
            )
        if time.monotonic() >= effective_deadline:
            break
        remaining = max(0.25, effective_deadline - time.monotonic())
        attempt_timeout = min(clamp_timeout(timeout), remaining)
        result = execute_command(
            command,
            working_directory=working_directory,
            approved=approved,
            timeout=attempt_timeout,
            expected_process=expected_process,
            expected_path=expected_path,
            expected_absent_path=expected_absent_path,
            environment=environment,
            dry_run=dry_run,
            execution_id=execution_id if attempt == 1 and execution_id else uuid.uuid4().hex,
            cancel_event=cancel_event,
        )
        result.attempt = attempt
        result.max_attempts = max_attempts
        result.idempotency_key = idempotency_key
        last = result
        if result.success:
            result.verification_passed = True
            _idempotency_put(idempotency_key, result)
            return result

        # Never retry policy/approval/critical failures.
        if result.status in {"approval_required", "cancelled", "syntax_error", "policy_blocked", "verification_failed"} or result.risk_level == "critical":
            break
        failure_class = "timeout" if result.timed_out else ("connection" if any(x in result.stderr.lower() for x in ["connection", "network", "temporarily unavailable"]) else "transient")
        if failure_class not in retry_on or attempt >= max_attempts:
            break
        delay = min(
            max(0.0, float(backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)])),
            max(0.0, effective_deadline - time.monotonic()),
        )
        if delay <= 0:
            break
        time.sleep(delay)

    if last is None:
        raise RuntimeError("Recovery executor produced no execution result.")

    # Diagnostics are observational and are not allowed to replace the primary failure.
    if diagnostic_command and not last.success:
        try:
            diag = execute_command(
                diagnostic_command,
                working_directory=working_directory,
                approved=approved,
                timeout=max(0.25, min(DEFAULT_TIMEOUT, 10, effective_deadline - time.monotonic())),
            )
            last.verification["diagnostic"] = asdict(diag)
        except Exception as exc:
            last.verification["diagnostic_error"] = str(exc)

    # Fallback is opt-in and only runs after the bounded primary retry loop.
    if (
        fallback_script
        and not last.success
        and last.risk_level not in {"critical", "high"}
        and time.monotonic() < effective_deadline
    ):
        try:
            fallback = execute_command(
                fallback_script,
                working_directory=working_directory,
                approved=approved,
                timeout=max(0.25, min(DEFAULT_TIMEOUT, effective_deadline - time.monotonic())),
            )
            last.verification["fallback"] = asdict(fallback)
            last.recovery_action = "fallback_executed"
            if fallback.success:
                last.success = True
                last.status = "recovered"
                _idempotency_put(idempotency_key, last)
                return last
        except Exception as exc:
            last.verification["fallback_error"] = str(exc)
            last.recovery_action = "fallback_failed"

    # Failed results are deliberately not cached: a caller may retry after the
    # transient condition has cleared. Successful results remain idempotent.
    return last


def execute_multi_step_workflow(
    steps: list[dict],
    working_directory: Optional[str] = None,
    continue_on_error: bool = False,
    approved: bool = False,
    max_attempts: int = 2,
    cancel_event: Optional[threading.Event] = None,
) -> dict:
    """Execute a validated sequence with explicit step success semantics."""
    if not isinstance(steps, list) or not steps:
        return {"success": False, "status": "invalid_plan", "steps_executed": 0, "total_steps": 0,
                "step_results": [], "output": "Multi-step plan is empty or invalid."}

    step_results = []
    completed_steps: list[dict] = []
    total_success = True
    combined_output = []

    for idx, step in enumerate(steps):
        if cancel_event is not None and cancel_event.is_set():
            total_success = False
            step_results.append({"step_id": idx + 1, "name": f"Step {idx + 1}", "status": "cancelled", "success": False,
                                 "reason": "Workflow cancelled before step execution."})
            break
        if not isinstance(step, dict):
            total_success = False
            step_results.append({"step_id": idx + 1, "name": f"Step {idx + 1}", "status": "invalid", "success": False,
                                 "reason": "Step must be an object."})
            if not continue_on_error: break
            continue
        step_id = step.get("step_id", step.get("step", idx + 1))
        step_name = str(step.get("name") or step.get("description") or f"Step {step_id}")
        command = str(step.get("command") or step.get("script") or "").strip()
        if not command:
            total_success = False
            step_results.append({"step_id": step_id, "name": step_name, "status": "invalid", "success": False,
                                 "reason": "No executable command provided.", "expected": step.get("expected")})
            if not continue_on_error: break
            continue

        try:
            result = execute_with_recovery(
                command, working_directory=working_directory, approved=approved,
                max_attempts=int(step.get("retry_limit", max_attempts) or max_attempts),
                retry_on=step.get("retry_on"), backoff_seconds=step.get("backoff_seconds"),
                expected_process=step.get("expected_process"), expected_path=step.get("expected_path"),
                expected_absent_path=step.get("expected_absent_path"), fallback_script=step.get("fallback_script"),
                diagnostic_command=step.get("diagnostic_command"), idempotency_key=step.get("idempotency_key"),
                cancel_event=cancel_event,
            )
        except Exception as exc:
            total_success = False
            res_dict = {"step_id": step_id, "name": step_name, "status": "exception", "success": False,
                        "error": str(exc), "expected": step.get("expected")}
            step_results.append(res_dict)
            if not continue_on_error: break
            continue

        res_dict = asdict(result)
        res_dict.update({"step_id": step_id, "name": step_name, "expected": step.get("expected"), "validation": step.get("validation")})
        step_results.append(res_dict)
        combined_output.append(f"--- [{step_name}] ---\n{result.output}")

        if result.success:
            completed_steps.append(step)
            continue

        total_success = False
        rollback_results = []
        if step.get("rollback_on_failure", True):
            for completed in reversed(completed_steps):
                rollback = completed.get("rollback_command") or completed.get("compensation_command")
                if not rollback: continue
                try:
                    rb = execute_command(rollback, working_directory=working_directory, approved=approved)
                    rollback_results.append({"step_id": completed.get("step_id", completed.get("step")), "result": asdict(rb)})
                except Exception as exc:
                    rollback_results.append({"step_id": completed.get("step_id", completed.get("step")), "error": str(exc)})
        if rollback_results:
            combined_output.append("--- [Rollback] ---\n" + json.dumps(rollback_results, default=str))
            res_dict["rollback_results"] = rollback_results
        if not continue_on_error: break

    # A skipped/invalid step can never make the whole pipeline successful.
    success = bool(steps) and total_success and len(step_results) == len(steps) and all(r.get("success") is True for r in step_results)
    return {
        "success": success,
        "status": "completed" if success else "failed",
        "steps_executed": len(step_results), "total_steps": len(steps),
        "step_results": step_results, "output": "\n\n".join(combined_output),
        "failure_policy": {"max_attempts": max_attempts, "continue_on_error": continue_on_error, "rollback_enabled": True},
    }


def execute_conditional_workflow(
    condition_script: str,
    on_success: Optional[str],
    on_failure: Optional[str] = None,
    working_directory: Optional[str] = None,
    approved: bool = False,
    condition_retries: int = 1,
    cancel_event: Optional[threading.Event] = None,
) -> dict:
    """Evaluate a strict predicate and execute at most one branch.

    Exit code 0 = true, 1 = false. Any other non-zero code means the predicate
    itself failed and no branch is executed. This prevents an evaluator error
    from being silently interpreted as a normal false condition.
    """
    if not condition_script or not condition_script.strip():
        return {"success": False, "status": "invalid_condition", "condition_met": False,
                "branch_executed": "none", "condition_output": "Condition script is empty."}

    attempts = max(1, min(3, int(condition_retries or 1)))
    cond_result = None
    for attempt in range(attempts):
        try:
            cond_result = execute_command(
                condition_script,
                working_directory=working_directory,
                approved=approved,
                timeout=min(DEFAULT_TIMEOUT, 30),
                cancel_event=cancel_event,
            )
        except Exception as exc:
            return {"success": False, "status": "condition_exception", "condition_met": False,
                    "branch_executed": "none", "condition_output": str(exc)}
        if cond_result.exit_code in (0, 1) or cond_result.status in {"syntax_error", "policy_blocked", "approval_required", "cancelled", "timeout"}:
            break

    if cond_result is None:
        return {"success": False, "status": "condition_no_result", "condition_met": False, "branch_executed": "none"}

    if cond_result.status in {"syntax_error", "policy_blocked", "approval_required", "cancelled", "timeout"}:
        return {"success": False, "status": "condition_evaluation_failed", "condition_met": False,
                "branch_executed": "none", "condition_output": cond_result.output,
                "condition_result": asdict(cond_result)}

    if cond_result.exit_code not in (0, 1):
        return {"success": False, "status": "condition_evaluation_failed", "condition_met": False,
                "branch_executed": "none", "condition_output": cond_result.output,
                "condition_result": asdict(cond_result),
                "error": f"Condition exited with unsupported code {cond_result.exit_code}; expected 0 or 1."}

    condition_met = cond_result.exit_code == 0
    branch_script = on_success if condition_met else on_failure
    if not branch_script:
        return {"success": True, "status": "condition_true_no_branch" if condition_met else "condition_false_no_branch",
                "condition_met": condition_met, "branch_executed": "none",
                "condition_output": cond_result.output, "condition_result": asdict(cond_result), "output": cond_result.output}

    try:
        branch_result = execute_with_recovery(branch_script, working_directory=working_directory, approved=approved, max_attempts=2, cancel_event=cancel_event)
    except Exception as exc:
        return {"success": False, "status": "branch_exception", "condition_met": condition_met,
                "branch_executed": "on_success" if condition_met else "on_failure",
                "condition_output": cond_result.output, "condition_result": asdict(cond_result), "error": str(exc)}
    return {
        "success": branch_result.success,
        "status": "completed" if branch_result.success else "failed",
        "condition_met": condition_met,
        "branch_executed": "on_success" if condition_met else "on_failure",
        "condition_output": cond_result.output,
        "condition_result": asdict(cond_result),
        "branch_result": asdict(branch_result),
        "output": f"Condition ({'PASS' if condition_met else 'FALSE'}):\n{cond_result.output}\n\nBranch Output:\n{branch_result.output}",
    }


# ============================================================
# PROCESS INSPECTION
# ============================================================

def process_to_dict(proc) -> dict[str, Any]:
    try:
        with proc.oneshot():
            return {
                "pid": proc.pid,
                "name": proc.info.get("name"),
                "status": proc.info.get("status"),
                "username": proc.info.get("username"),
                "cpu_percent": proc.cpu_percent(None),
                "memory_rss": (
                    proc.memory_info().rss
                ),
                "cmdline": proc.info.get("cmdline"),
            }

    except Exception as exc:
        return {
            "pid": proc.pid,
            "error": str(exc),
        }


def list_processes(
    query: Optional[str] = None,
) -> list[dict[str, Any]]:

    processes = []

    query_lower = (
        query.lower()
        if query
        else None
    )

    try:
        import psutil
    except ImportError:
        return []

    for proc in psutil.process_iter(
        [
            "pid",
            "name",
            "status",
            "username",
            "cmdline",
        ]
    ):
        try:
            info = proc.info

            if query_lower:

                haystack = " ".join(
                    [
                        str(info.get("name") or ""),
                        str(info.get("cmdline") or ""),
                    ]
                ).lower()

                if query_lower not in haystack:
                    continue

            processes.append(
                process_to_dict(proc)
            )

        except Exception:
            continue

    return processes


def verify_process(
    process_name: Optional[str],
) -> bool:

    if not process_name:
        return False

    query = process_name.lower()

    try:
        import psutil
    except ImportError:
        return False

    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info.get("name")

            if (
                name
                and query in name.lower()
            ):
                return True

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            continue

    return False


# ============================================================
# SECURITY / RISK CLASSIFICATION
# ============================================================

RISK_PATTERNS: list[tuple[str, str, str]] = [
    (
        "critical",
        "weapon/explosive construction or deployment",
        r"\b(atom(?:ic)?\s+bomb|nuclear\s+(?:weapon|device)|thermonuclear|explosive|detonator|warhead|bioweapon|chemical\s+weapon|nerve\s+agent)\b",
    ),
    (
        "critical",
        "malware/credential theft tooling",
        r"\b(ransomware|keylogger|credential\s+stealer|cookie\s+stealer|reverse\s+shell|meterpreter|rootkit|remote\s+access\s+trojan)\b",
    ),
    (
        "critical",
        "browser credential database access",
        r"(login\s+data|cookies\.sqlite|logins\.json|web\s+data|key4\.db|credentials\.db).{0,80}(chrome|chromium|brave|firefox|edge)|(?:chrome|chromium|brave|firefox|edge).{0,80}(login\s+data|cookies\.sqlite|logins\.json|web\s+data|key4\.db|credentials\.db)",
    ),
    (
        "critical",
        "security bypass or unauthorized exploitation",
        r"\b(disable\s+(?:defender|firewall|antivirus)|privilege\s+escalation|persistence|bypass\s+(?:security|guardrail|approval)|ddos|arp\s+spoof|dns\s+poison)\b",
    ),

    (
        "critical",
        "disk destruction",
        r"\b(mkfs|fdisk|parted|gdisk|dd\s+if=|wipefs)\b",
    ),
    (
        "critical",
        "system shutdown/reboot",
        r"\b(shutdown|reboot|poweroff|halt)\b",
    ),
    (
        "high",
        "filesystem deletion",
        r"\brm\s+(?:-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\b",
    ),
    (
        "critical",
        "recursive root deletion",
        r"\brm\s+-[^\s]*r[^\s]*f[^\s]*\s+/(?:\s|$|\*)",
    ),
    (
        "critical",
        "privileged command",
        r"\bsudo\b|\bdoas\b",
    ),
    (
        "critical",
        "permission ownership modification",
        r"\b(chmod|chown)\b",
    ),
    (
        "high",
        "recursive deletion",
        r"\brm\s+-[^\n]*r\b",
    ),
    (
        "high",
        "package installation/removal",
        r"\b(apt|apt-get|dnf|yum|pacman|brew|pip|pip3|npm|pnpm|yarn)\b",
    ),
    (
        "high",
        "service management",
        r"\b(systemctl|service)\b",
    ),
    (
        "high",
        "network/firewall modification",
        r"\b(iptables|ufw|firewall-cmd|nmcli)\b",
    ),
    (
        "medium",
        "file mutation",
        r"\b(cp|mv|mkdir|touch|truncate|sed\s+-i|tee)\b",
    ),
    (
        "medium",
        "process termination",
        r"\b(kill|pkill|killall)\b",
    ),
]


def classify_command(command: str) -> dict[str, Any]:
    matched: list[dict[str, str]] = []

    highest = "low"

    order = {
        "low": 0,
        "medium": 1,
        "high": 2,
        "critical": 3,
    }

    for level, reason, pattern in RISK_PATTERNS:

        if re.search(
            pattern,
            command,
            flags=re.IGNORECASE,
        ):

            matched.append(
                {
                    "level": level,
                    "reason": reason,
                }
            )

            if order[level] > order[highest]:
                highest = level

    return {
        "level": highest,
        "reasons": [
            item["reason"]
            for item in matched
        ],
        "matches": matched,
        "requires_confirmation": (
            highest in {"high", "critical"}
        ),
    }


# ============================================================
# PROCESS TREE MANAGEMENT
# ============================================================

def terminate_process_tree(
    process: subprocess.Popen,
    force: bool = False,
) -> None:

    if process.poll() is not None:
        return

    try:
        import psutil

        parent = psutil.Process(
            process.pid
        )

        children = parent.children(
            recursive=True
        )

        for child in children:
            try:
                if force:
                    child.kill()
                else:
                    child.terminate()
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                pass

        try:
            if force:
                parent.kill()
            else:
                parent.terminate()
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            pass

        _, alive = psutil.wait_procs(
            children + [parent],
            timeout=2,
        )

        if force:
            for proc in alive:
                try:
                    proc.kill()
                except Exception:
                    pass

    except ImportError:

        try:
            if force:
                process.kill()
            else:
                process.terminate()
        except Exception:
            pass

    except Exception:

        try:
            if force:
                process.kill()
            else:
                process.terminate()
        except Exception:
            pass


# ============================================================
# COMMAND EXECUTION
# ============================================================

def build_command(
    command: str,
    shell_name: str,
    shell_path: str,
) -> list[str]:

    system = platform.system().lower()

    if system == "windows":

        if "powershell" in shell_name.lower():

            return [
                shell_path,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ]

        return [
            shell_path,
            "/D",
            "/S",
            "/C",
            command,
        ]

    return [
        shell_path,
        "-c",
        command,
    ]


def validate_command_syntax(command: str, shell_name: str, shell_path: str) -> tuple[bool, str]:
    """Preflight shell syntax without executing the command."""
    if platform.system().lower() == "windows":
        if "powershell" in shell_name.lower():
            checker = shutil.which("pwsh") or shutil.which("powershell")
            if not checker:
                return True, ""
            try:
                # PowerShell parser errors are written to stderr and return non-zero.
                result = subprocess.run(
                    [checker, "-NoProfile", "-NonInteractive", "-Command", f"$null = [System.Management.Automation.Language.Parser]::ParseInput(@'\n{command}\n'@, [ref]$null, [ref]$null)"],
                    capture_output=True, text=True, timeout=3,
                )
                if result.returncode != 0:
                    return False, (result.stderr or result.stdout or "PowerShell syntax validation failed").strip()
            except Exception:
                # Syntax validation must never prevent otherwise valid commands when
                # the host parser is unavailable.
                return True, ""
        return True, ""

    # Bash/sh validation is deterministic and catches the exact class of malformed
    # generated commands seen in conditional workflows before they mutate the host.
    checker = "/bin/bash" if os.path.exists("/bin/bash") else shell_path
    if not checker or not os.path.exists(checker):
        return True, ""
    try:
        result = subprocess.run(
            [checker, "-n", "-c", command],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "Shell syntax validation failed").strip()
    except subprocess.TimeoutExpired:
        return False, "Shell syntax validation timed out."
    except Exception:
        return True, ""
    return True, ""


def _background_command(command: str) -> bool:
    """Detect commands intended to return after launching a detached/background task."""
    compact = re.sub(r"\s+", " ", command.strip())
    return bool(re.search(r"(?:^|[;&])\s*(?:[^;&]+\s+)?&\s*$", compact)) or compact.endswith("&")


def execute_command(
    command: str,
    *,
    execution_id: Optional[str] = None,
    working_directory: Optional[str] = None,
    environment: Optional[dict[str, Any]] = None,
    timeout: Any = None,
    expected_process: Optional[str] = None,
    expected_path: Optional[str] = None,
    expected_absent_path: Optional[str] = None,
    dry_run: bool = False,
    approved: bool = False,
    output_callback: Optional[
        Callable[[str, str], None]
    ] = None,
    cancel_event: Optional[threading.Event] = None,
) -> ExecutionResult:

    if not command or not command.strip():

        raise ValueError(
            "Command cannot be empty."
        )

    execution_id = (
        execution_id
        or uuid.uuid4().hex
    )

    task = REGISTRY.create(command, execution_id=execution_id)
    setup_started = time.time()
    try:
        shell_name, shell_path = detect_shell()
        cwd = normalize_working_directory(working_directory)
        env = sanitize_environment(environment)
        timeout_seconds = min(clamp_timeout(timeout), EXECUTION_BUDGET_SECONDS)
    except Exception as exc:
        finished = time.time()
        shell_name, shell_path = detect_shell()
        result = ExecutionResult(
            execution_id=execution_id, status="setup_failed", success=False,
            exit_code=None, signal=None, command=command, shell=shell_name, shell_path=shell_path,
            os=platform.system(), architecture=platform.machine(), working_directory=working_directory or os.getcwd(),
            stdout="", stderr=str(exc), output=str(exc), duration_ms=int((finished-setup_started)*1000),
            timed_out=False, cancelled=False, risk_level="unknown", risk_reasons=[],
            started_at=setup_started, finished_at=finished, verification_passed=False,
            safety_decision="setup_error",
        )
        REGISTRY.finish(execution_id, result)
        return result
    if _background_command(command):
        timeout_seconds = min(timeout_seconds, 10.0)

    risk = classify_command(
        command
    )

    started = time.time()

    syntax_ok, syntax_error = validate_command_syntax(command, shell_name, shell_path)
    if platform.system().lower() != "windows" and re.search(r"if\s*\(\(\s*\$\(echo\b", command, re.I):
        syntax_ok = False
        syntax_error = "Unsupported generated shell construct: nested echo/command substitution inside Bash arithmetic. Use an integer test or awk predicate instead."
    if not syntax_ok:
        finished = time.time()
        result = ExecutionResult(
            execution_id=execution_id, status="syntax_error", success=False,
            exit_code=2, signal=None, command=command, shell=shell_name,
            shell_path=shell_path, os=platform.system(), architecture=platform.machine(),
            working_directory=cwd, stdout="", stderr=syntax_error,
            output=syntax_error, duration_ms=int((finished - started) * 1000),
            timed_out=False, cancelled=False, risk_level=risk["level"],
            risk_reasons=risk["reasons"], expected_process=expected_process,
            started_at=started, finished_at=finished, verification_passed=False,
            safety_decision="syntax_rejected",
        )
        REGISTRY.finish(execution_id, result)
        return result

    # V4 hard deny: explicit critical safety categories can never be approved
    # through the generic execution flag. Human approval is for authorized
    # high-impact host mutations, not for prohibited harmful capabilities.
    if risk["level"] == "critical" and any(
        reason in {
            "weapon/explosive construction or deployment",
            "malware/credential theft tooling",
            "security bypass or unauthorized exploitation",
        }
        for reason in risk["reasons"]
    ):
        finished = time.time()
        result = ExecutionResult(
            execution_id=execution_id,
            status="policy_blocked",
            success=False,
            exit_code=None,
            signal=None,
            command=command,
            shell=shell_name,
            shell_path=shell_path,
            os=platform.system(),
            architecture=platform.machine(),
            working_directory=cwd,
            stdout="",
            stderr="",
            output="Execution blocked by OmniShell V4 safety policy.",
            duration_ms=int((finished - started) * 1000),
            timed_out=False,
            cancelled=False,
            risk_level=risk["level"],
            risk_reasons=risk["reasons"],
            expected_process=expected_process,
            started_at=started,
            finished_at=finished,
            verification_passed=False,
            safety_decision="block",
        )
        REGISTRY.finish(execution_id, result)
        return result

    if (
        (ENFORCE_POLICY or REQUIRE_RISK_APPROVAL)
        and risk["requires_confirmation"]
        and not approved
    ):

        finished = time.time()

        result = ExecutionResult(
            execution_id=execution_id,
            status="approval_required",
            success=False,
            exit_code=None,
            signal=None,
            command=command,
            shell=shell_name,
            shell_path=shell_path,
            os=platform.system(),
            architecture=platform.machine(),
            working_directory=cwd,
            stdout="",
            stderr=(
                "Execution requires explicit approval."
            ),
            output=(
                "Execution blocked by OmniShell "
                "execution policy."
            ),
            duration_ms=int(
                (finished - started) * 1000
            ),
            timed_out=False,
            cancelled=False,
            risk_level=risk["level"],
            risk_reasons=risk["reasons"],
            expected_process=expected_process,
            started_at=started,
            finished_at=finished,
        )

        REGISTRY.finish(
            execution_id,
            result,
        )

        return result

    if dry_run:

        finished = time.time()

        result = ExecutionResult(
            execution_id=execution_id,
            status="dry_run",
            success=True,
            exit_code=0,
            signal=None,
            command=command,
            shell=shell_name,
            shell_path=shell_path,
            os=platform.system(),
            architecture=platform.machine(),
            working_directory=cwd,
            stdout="",
            stderr="",
            output=(
                "DRY RUN: command was validated "
                "but not executed."
            ),
            duration_ms=int(
                (finished - started) * 1000
            ),
            timed_out=False,
            cancelled=False,
            risk_level=risk["level"],
            risk_reasons=risk["reasons"],
            expected_process=expected_process,
            started_at=started,
            finished_at=finished,
        )

        REGISTRY.finish(
            execution_id,
            result,
        )

        return result

    command_args = build_command(
        command,
        shell_name,
        shell_path,
    )

    process: Optional[subprocess.Popen] = None

    stdout_text = ""
    stderr_text = ""
    timed_out = False
    cancelled = False
    exit_code: Optional[int] = None
    process_pid: Optional[int] = None

    try:

        process = subprocess.Popen(
            command_args,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=(
                platform.system().lower()
                != "windows"
            ),
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP
                if platform.system().lower()
                == "windows"
                else 0
            ),
        )

        task.process = process
        process_pid = process.pid

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        stdout_done = threading.Event()
        stderr_done = threading.Event()

        output_sizes = {"stdout": 0, "stderr": 0}
        output_lock = threading.Lock()

        def read_stream(
            stream,
            chunks,
            stream_name,
            done_event,
        ):
            try:
                for line in iter(stream.readline, ""):
                    encoded_size = len(line.encode("utf-8", errors="ignore"))
                    with output_lock:
                        if output_sizes[stream_name] < MAX_OUTPUT_BYTES:
                            remaining = MAX_OUTPUT_BYTES - output_sizes[stream_name]
                            if encoded_size <= remaining:
                                chunks.append(line)
                                output_sizes[stream_name] += encoded_size
                            else:
                                chunks.append(line.encode("utf-8", errors="ignore")[:remaining].decode("utf-8", errors="ignore"))
                                output_sizes[stream_name] = MAX_OUTPUT_BYTES
                            if len(task.output_lines) < 10000:
                                task.output_lines.append(line.rstrip("\n")[:10000])
                    if output_callback:
                        try:
                            output_callback(stream_name, line)
                        except Exception:
                            pass
            finally:
                done_event.set()

        stdout_thread = threading.Thread(
            target=read_stream,
            args=(
                process.stdout,
                stdout_chunks,
                "stdout",
                stdout_done,
            ),
            daemon=True,
        )

        stderr_thread = threading.Thread(
            target=read_stream,
            args=(
                process.stderr,
                stderr_chunks,
                "stderr",
                stderr_done,
            ),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        deadline = (
            time.monotonic()
            + timeout_seconds
        )

        while process.poll() is None:

            if (cancel_event is not None and cancel_event.is_set()) or task.cancelled:
                cancelled = True

                terminate_process_tree(
                    process
                )

                break

            if time.monotonic() >= deadline:
                timed_out = True

                terminate_process_tree(
                    process,
                    force=False,
                )

                time.sleep(0.5)

                if process.poll() is None:
                    terminate_process_tree(
                        process,
                        force=True,
                    )

                break

            time.sleep(0.05)

        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            terminate_process_tree(
                process,
                force=True,
            )
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                # Never remain attached to an uncooperative child process.
                timed_out = True

        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        stdout_text = "".join(
            stdout_chunks
        )

        stderr_text = "".join(
            stderr_chunks
        )

        exit_code = process.returncode

    except Exception as exc:

        stderr_text = str(exc)

        if process:
            try:
                terminate_process_tree(
                    process,
                    force=True,
                )
            except Exception:
                pass

        exit_code = -1

    finished = time.time()

    # --------------------------------------------------------
    # Verification
    # --------------------------------------------------------

    verification: dict[str, Any] = {}

    if expected_process:
        # GUI applications may take a moment to register their process after the
        # launcher exits. Poll briefly before declaring verification failure.
        detected = False
        for _ in range(10):
            if verify_process(expected_process):
                detected = True
                break
            time.sleep(0.15)
        verification["process_detected"] = detected
        verification["process_verification"] = "observed" if detected else "not_observed"

    if expected_path:

        expanded = os.path.abspath(
            os.path.expanduser(
                os.path.expandvars(
                    expected_path
                )
            )
        )

        verification[
            "expected_path"
        ] = {
            "path": expanded,
            "exists": os.path.exists(expanded),
        }

    if expected_absent_path:

        expanded = os.path.abspath(
            os.path.expanduser(
                os.path.expandvars(
                    expected_absent_path
                )
            )
        )

        verification[
            "expected_absent_path"
        ] = {
            "path": expanded,
            "exists": os.path.exists(expanded),
        }

    # Verification is part of success, not a best-effort decoration.
    verification_passed = True
    verification_failures = []
    if expected_process and not verification.get("process_detected", False):
        verification_passed = False
        verification_failures.append(f"Expected process was not observed: {expected_process}")
    if expected_path and not verification.get("expected_path", {}).get("exists", False):
        verification_passed = False
        verification_failures.append(f"Expected path does not exist: {expected_path}")
    if expected_absent_path and verification.get("expected_absent_path", {}).get("exists", False):
        verification_passed = False
        verification_failures.append(f"Path still exists: {expected_absent_path}")
    if verification_failures:
        verification["failures"] = verification_failures

    if cancelled:
        status = "cancelled"
    elif timed_out:
        status = "timeout"
    elif exit_code == 0 and verification_passed:
        status = "success"
    elif exit_code == 0 and not verification_passed:
        status = "verification_failed"
    else:
        status = "failed"

    success = status == "success"

    combined_output = ""

    if stdout_text:
        combined_output += stdout_text

    if stderr_text:

        if combined_output:
            combined_output += "\n"

        combined_output += stderr_text

    result = ExecutionResult(
        execution_id=execution_id,
        status=status,
        success=success,
        exit_code=exit_code,
        signal=(
            -exit_code
            if exit_code is not None
            and exit_code < 0
            else None
        ),
        command=command,
        shell=shell_name,
        shell_path=shell_path,
        os=platform.system(),
        architecture=platform.machine(),
        working_directory=cwd,
        stdout=stdout_text,
        stderr=stderr_text,
        output=combined_output.strip(),
        duration_ms=int(
            (finished - started) * 1000
        ),
        timed_out=timed_out,
        cancelled=cancelled,
        risk_level=risk["level"],
        risk_reasons=risk["reasons"],
        process_pid=process_pid,
        process_detected=(
            verification.get(
                "process_detected",
                False,
            )
        ),
        expected_process=expected_process,
        verification=verification,
        started_at=started,
        finished_at=finished,
        verification_passed=verification_passed,
    )

    REGISTRY.finish(
        execution_id,
        result,
    )

    return result


# ============================================================
# ASYNC EXECUTION
# ============================================================

def start_async_execution(
    request: dict[str, Any],
) -> str:

    command = request.get(
        "script"
    ) or request.get(
        "command"
    )

    if not command:
        raise ValueError(
            "Missing script/command."
        )

    execution_id = uuid.uuid4().hex

    task = ExecutionTask(
        execution_id=execution_id,
        command=command,
        started_at=time.time(),
    )

    with REGISTRY._lock:
        REGISTRY._tasks[execution_id] = task

    def runner():

        try:

            result = execute_with_recovery(
                command,
                execution_id=execution_id,
                working_directory=request.get("working_directory"),
                environment=request.get("environment"),
                timeout=request.get("timeout"),
                expected_process=request.get("expected_process"),
                expected_path=request.get("expected_path"),
                expected_absent_path=request.get("expected_absent_path"),
                dry_run=bool(request.get("dry_run", False)),
                approved=bool(request.get("approved", False)),
                max_attempts=int(request.get("max_attempts", 2)),
                retry_on=request.get("retry_on"),
                backoff_seconds=request.get("backoff_seconds"),
                fallback_script=request.get("fallback_script"),
                diagnostic_command=request.get("diagnostic_command"),
                idempotency_key=request.get("idempotency_key"),
            )

            task.finished = True
            task.result = result

        except Exception as exc:

            finished = time.time()

            result = ExecutionResult(
                execution_id=execution_id,
                status="failed",
                success=False,
                exit_code=-1,
                signal=None,
                command=command,
                shell=detect_shell()[0],
                shell_path=detect_shell()[1],
                os=platform.system(),
                architecture=platform.machine(),
                working_directory=os.getcwd(),
                stdout="",
                stderr=str(exc),
                output=str(exc),
                duration_ms=int(
                    (finished - task.started_at)
                    * 1000
                ),
                timed_out=False,
                cancelled=False,
                risk_level="unknown",
                risk_reasons=[],
                started_at=task.started_at,
                finished_at=finished,
            )

            REGISTRY.finish(
                execution_id,
                result,
            )

    thread = threading.Thread(
        target=runner,
        daemon=True,
        name=f"omnishell-{execution_id[:8]}",
    )

    thread.start()

    return execution_id


# ============================================================
# HTTP SERVER
# ============================================================

class ExecutionHandler(
    http.server.BaseHTTPRequestHandler
):

    server_version = "OmniShellHost/4.0"

    # --------------------------------------------------------
    # Common headers
    # --------------------------------------------------------

    def _headers(self):
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS",
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Requested-With",
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

    # --------------------------------------------------------
    # JSON response
    # --------------------------------------------------------

    def _json_response(
        self,
        payload: dict[str, Any],
        status: int = 200,
    ):

        body = json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")

        try:

            self.send_response(status)
            self._headers()
            self.send_header(
                "Content-Length",
                str(len(body)),
            )
            self.end_headers()

            self.wfile.write(body)

        except BrokenPipeError:

            print(
                "[HOST AGENT] Client disconnected "
                "before response was sent."
            )

    # --------------------------------------------------------
    # Read JSON
    # --------------------------------------------------------

    def _read_json(self) -> dict[str, Any]:

        content_length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        if content_length <= 0:
            return {}

        raw = self.rfile.read(
            content_length
        )

        data = json.loads(
            raw.decode(
                "utf-8"
            )
        )

        if not isinstance(data, dict):
            raise ValueError(
                "Request body must be a JSON object."
            )

        return data

    # --------------------------------------------------------
    # OPTIONS
    # --------------------------------------------------------

    def do_OPTIONS(self):

        self._json_response(
            {
                "status": "ok"
            }
        )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    def do_GET(self):

        try:

            if self.path in {
                "/",
                "/health",
            }:
                self._json_response(
                    {
                        "status": "ok",
                        "service": "OmniShell Host Executor",
                        "version": "4.0",
                        "os": platform.system(),
                        "port": PORT,
                        "capabilities_supported": 19,
                    }
                )
                return

            if self.path == "/scheduler/status":
                state=_scheduler_state_snapshot()
                state.update({
                    "enabled": SCHEDULER_ENABLED,
                    "interval_seconds": SCHEDULER_INTERVAL,
                    "backend_url": BACKEND_URL,
                    "approval_ui_base": APPROVAL_UI_BASE,
                    "approval_backend_base": APPROVAL_BACKEND_BASE,
                    "gui_available": _gui_available(),
                })
                self._json_response(state)
                return

            if self.path == "/system":
                self._json_response(get_system_info())
                return

            if self.path == "/system/metrics":
                self._json_response(get_realtime_metrics())
                return

            if self.path == "/capabilities":
                self._json_response({
                    "service": "OmniShell Host Execution Agent V4",
                    "supported_capabilities": [
                        "Questions and answers", "Information requests", "System inspection",
                        "Analysis", "Application operations", "Browser operations", "File operations",
                        "Shell operations", "Multi-step tasks", "Interactive workflows", "Scheduled workflows",
                        "Recurring workflows", "Conditional workflows", "Reminders", "Research tasks",
                        "Planning-only requests", "Tasks requiring human approval", "Tasks requiring clarification",
                        "Tasks requiring recovery after failure"
                    ]
                })
                return

            if self.path == "/browsers":
                self._json_response({"browsers": get_installed_browsers()})
                return

            if self.path == "/processes":
                self._json_response({"processes": list_processes()})
                return

            if self.path == "/executions":
                history = [asdict(result) for result in REGISTRY.all_history()]
                self._json_response({"executions": history})
                return

            if self.path.startswith("/executions/"):
                execution_id = self.path.split("/executions/", 1)[1].split("/", 1)[0]
                task = REGISTRY.get(execution_id)
                if not task:
                    self._json_response({"error": "Execution not found."}, 404)
                    return
                self._json_response({
                    "execution_id": execution_id,
                    "finished": task.finished,
                    "cancelled": task.cancelled,
                    "result": asdict(task.result) if task.result else None,
                    "output_lines": task.output_lines[-500:],
                })
                return

            self._json_response({"error": "Not found."}, 404)

        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    def do_POST(self):
        try:
            if self.path == "/execute":
                data = self._read_json()
                command = data.get("script") or data.get("command")
                if not command:
                    self._json_response({"status": "error", "error": "Missing script/command."}, 400)
                    return

                risk = classify_command(command)
                async_mode = bool(data.get("async", False))
                if async_mode:
                    execution_id = start_async_execution(data)
                    self._json_response({"status": "accepted", "execution_id": execution_id, "risk": risk}, 202)
                    return

                cached = _idempotency_get(data.get("idempotency_key"))
                if cached:
                    response = asdict(cached)
                    response["deduplicated"] = True
                    self._json_response(response, 200)
                    return

                result = execute_with_recovery(
                    command,
                    max_attempts=int(data.get("max_attempts", 2)),
                    retry_on=data.get("retry_on"),
                    backoff_seconds=data.get("backoff_seconds"),
                    fallback_script=data.get("fallback_script"),
                    diagnostic_command=data.get("diagnostic_command"),
                    idempotency_key=data.get("idempotency_key"),
                    working_directory=data.get("working_directory"),
                    environment=data.get("environment"),
                    timeout=data.get("timeout"),
                    expected_process=data.get("expected_process"),
                    expected_path=data.get("expected_path"),
                    expected_absent_path=data.get("expected_absent_path"),
                    dry_run=bool(data.get("dry_run", False)),
                    approved=bool(data.get("approved", False)),
                )
                response = asdict(result)
                response["validated"] = result.success
                response["status"] = result.status
                self._json_response(response, 200)
                return

            if self.path == "/execute/multi-step":
                data = self._read_json()
                steps = data.get("steps") or []
                if not isinstance(steps, list) or not steps:
                    self._json_response({"status": "error", "error": "steps list required."}, 400)
                    return
                res = execute_multi_step_workflow(
                    steps=steps,
                    working_directory=data.get("working_directory"),
                    continue_on_error=bool(data.get("continue_on_error", False)),
                    approved=bool(data.get("approved", False)),
                )
                self._json_response(res, 200)
                return

            if self.path == "/execute/conditional":
                data = self._read_json()
                cond_script = data.get("condition_script")
                on_succ = data.get("on_success")
                on_fail = data.get("on_failure")
                if not cond_script or not on_succ:
                    self._json_response({"status": "error", "error": "condition_script and on_success are required."}, 400)
                    return
                res = execute_conditional_workflow(
                    condition_script=cond_script,
                    on_success=on_succ,
                    on_failure=on_fail,
                    working_directory=data.get("working_directory"),
                    approved=bool(data.get("approved", False)),
                )
                self._json_response(res, 200)
                return

            if self.path == "/notify":
                data = self._read_json()
                title = str(data.get("title") or "OmniShell Notification")
                msg = str(data.get("message") or "")
                sent = send_desktop_notification(title, msg)
                self._json_response({"status": "sent" if sent else "unsupported", "title": title, "message": msg}, 200)
                return

            if self.path == "/cancel":
                data = self._read_json()
                execution_id = data.get("execution_id")
                if not execution_id:
                    self._json_response({"error": "execution_id is required."}, 400)
                    return
                cancelled = REGISTRY.cancel(execution_id)
                self._json_response({"execution_id": execution_id, "cancelled": cancelled})
                return

            if self.path == "/classify":
                data = self._read_json()
                command = data.get("script") or data.get("command")
                if not command:
                    self._json_response({"error": "Missing script/command."}, 400)
                    return
                self._json_response(classify_command(command))
                return

            if self.path == "/dry-run":
                data = self._read_json()
                command = data.get("script") or data.get("command")
                if not command:
                    self._json_response({"error": "Missing script/command."}, 400)
                    return
                self._json_response({
                    "command": command,
                    "risk": classify_command(command),
                    "working_directory": normalize_working_directory(data.get("working_directory")),
                    "will_execute": False,
                })
                return

            self._json_response(
                {
                    "error": "Not found."
                },
                404,
            )

        except json.JSONDecodeError as exc:

            self._json_response(
                {
                    "status": "error",
                    "error": (
                        f"Invalid JSON: {exc}"
                    ),
                },
                400,
            )

        except ValueError as exc:

            self._json_response(
                {
                    "status": "error",
                    "error": str(exc),
                },
                400,
            )

        except Exception as exc:

            print(
                "[HOST AGENT] Request exception:"
            )

            traceback.print_exc()

            self._json_response(
                {
                    "status": "error",
                    "error": str(exc),
                },
                500,
            )

    # --------------------------------------------------------
    # Logging
    # --------------------------------------------------------

    def log_message(
        self,
        format_string: str,
        *args,
    ):
        print(
            f"[HOST AGENT] "
            f"{self.address_string()} - "
            f"{format_string % args}"
        )


# ============================================================
# THREADED SERVER
# ============================================================

class ThreadedHTTPServer(
    socketserver.ThreadingMixIn,
    socketserver.TCPServer,
):

    allow_reuse_address = True
    daemon_threads = True


# ============================================================
# MAIN
# ============================================================



# ============================================================
# SCHEDULED EXECUTION ENGINE
# ============================================================

import threading
import requests
import webbrowser
from urllib.parse import urlparse

SCHEDULER_ENABLED = os.getenv("OMNISHELL_SCHEDULER_ENABLED", "true").lower() in {"1","true","yes","on"}
SCHEDULER_INTERVAL = max(1, int(os.getenv("OMNISHELL_SCHEDULER_INTERVAL_SECONDS", "2")))
APPROVAL_TIMEOUT = max(30, int(os.getenv("OMNISHELL_APPROVAL_TIMEOUT_SECONDS", "300")))
BACKEND_URL = os.getenv("OMNISHELL_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
APPROVAL_UI_BASE = os.getenv("OMNISHELL_APPROVAL_UI_BASE", "http://127.0.0.1:3000/scheduled-approval").rstrip("/")
APPROVAL_BACKEND_BASE = os.getenv("OMNISHELL_APPROVAL_BACKEND_BASE", f"{BACKEND_URL}/api/scheduled-tasks").rstrip("/")
SCHEDULER_HTTP_TIMEOUT = float(os.getenv("OMNISHELL_SCHEDULER_HTTP_TIMEOUT", "5"))
SCHEDULER_MAX_WORKERS = max(1, int(os.getenv("OMNISHELL_SCHEDULER_MAX_WORKERS", "4")))

_scheduler_stop=threading.Event()
_scheduler_workers=threading.BoundedSemaphore(SCHEDULER_MAX_WORKERS)
_scheduler_active_ids:set[int]=set()
_scheduler_active_lock=threading.RLock()
_scheduler_state_lock=threading.RLock()
_scheduler_state={
    "started_at": time.time(),
    "last_poll_at": None,
    "last_poll_status": None,
    "last_task_id": None,
    "last_task_status": None,
    "last_approval_at": None,
    "last_approval_result": None,
    "last_error": None,
    "poll_count": 0,
}

def _scheduler_state_update(**values):
    with _scheduler_state_lock:
        _scheduler_state.update(values)


def _scheduler_state_snapshot():
    with _scheduler_state_lock:
        return dict(_scheduler_state)


def _http_json(method,url,**kwargs):
    response=requests.request(method,url,timeout=SCHEDULER_HTTP_TIMEOUT,**kwargs)
    try: payload=response.json()
    except Exception: payload={}
    return response.status_code,payload


def _browser_candidates(url):
    system=platform.system().lower()
    if system=="windows":
        return [("msedge", ["--new-window", url]), ("chrome", ["--new-window", url]),
                ("brave", ["--new-window", url]), ("firefox", ["--new-window", url])]
    if system=="darwin":
        return [("open", ["-na", "Google Chrome", "--args", "--new-window", url]),
                ("open", ["-na", "Brave Browser", "--args", "--new-window", url]),
                ("open", ["-na", "Firefox", "--args", "--new-window", url])]
    return [("brave-browser", ["--new-window", url]), ("google-chrome", ["--new-window", url]),
            ("google-chrome-stable", ["--new-window", url]), ("chromium", ["--new-window", url]),
            ("chromium-browser", ["--new-window", url]), ("firefox", ["--new-window", url]),
            ("xdg-open", [url]), ("x-www-browser", [url]), ("gnome-open", [url])]


def _gui_available():
    system=platform.system().lower()
    if system == "windows" or system == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _approval_urls(task_id: int, token: str):
    from urllib.parse import quote
    encoded=quote(token, safe="")
    return [
        f"{APPROVAL_UI_BASE}/{encoded}?taskId={task_id}",
        f"{APPROVAL_BACKEND_BASE}/{task_id}/approval-document?token={encoded}",
    ]


def _probe_url(url):
    try:
        status, _ = _http_json("GET", url)
        return status < 500
    except Exception:
        return False


def open_new_browser_window(url):
    parsed=urlparse(url)
    if parsed.scheme in {"http", "https"}:
        if not parsed.netloc:
            raise ValueError("Browser URL must include a host.")
    elif parsed.scheme != "file":
        raise ValueError("Browser URL must use http/https or a local file fallback.")
    if not _gui_available():
        raise RuntimeError("No desktop GUI session is available (DISPLAY/WAYLAND_DISPLAY is missing).")
    errors=[]
    system=platform.system().lower()
    env=os.environ.copy()
    for executable,args in _browser_candidates(url):
        resolved=shutil.which(executable)
        if not resolved:
            continue
        try:
            proc=subprocess.Popen([resolved,*args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  stdin=subprocess.DEVNULL, start_new_session=system!="windows",
                                  creationflags=(subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP if system=="windows" else 0), env=env)
            time.sleep(0.35)
            if proc.poll() is not None and proc.returncode not in (0,):
                err=proc.stderr.read().decode("utf-8",errors="replace").strip()[:500]
                errors.append(f"{executable}: exited {proc.returncode}{': '+err if err else ''}")
                continue
            return {"opened":True,"browser":executable,"method":"native-new-window","url":url}
        except Exception as exc:
            errors.append(f"{executable}: {exc}")
    try:
        if webbrowser.open_new(url):
            return {"opened":True,"browser":"system-default","method":"webbrowser.open_new","url":url}
    except Exception as exc:
        errors.append(f"webbrowser: {exc}")
    raise RuntimeError("Could not launch a browser approval window." + (f" {' | '.join(errors)}" if errors else ""))


def open_approval_document(task_id: int, token: str):
    if not token:
        raise ValueError(f"Task {task_id} has no approval token.")
    candidates=_approval_urls(task_id, token)
    errors=[]
    for url in candidates:
        if not _probe_url(url):
            errors.append(f"unreachable: {url.split('?')[0]}")
            continue
        try:
            result=open_new_browser_window(url)
            result["approval_urls_tried"]=candidates
            return result
        except Exception as exc:
            errors.append(f"{url.split('?')[0]}: {exc}")
    try:
        fallback_path=_write_local_approval_fallback(task_id, token)
        fallback_result=open_new_browser_window(fallback_path.as_uri())
        fallback_result["fallback_document"]=str(fallback_path)
        fallback_result["approval_urls_tried"]=candidates
        return fallback_result
    except Exception as exc:
        errors.append(f"local fallback: {exc}")
    raise RuntimeError("Approval document could not be opened. " + " | ".join(errors))


def _write_local_approval_fallback(task_id: int, token: str):
    """Create a host-local approval document when the frontend route is unavailable."""
    from pathlib import Path
    from urllib.parse import quote
    safe_token=quote(token, safe="")
    base=APPROVAL_BACKEND_BASE
    html=f"""<!doctype html><html><head><meta charset='utf-8'><title>OmniShell Approval #{task_id}</title>
<style>body{{font-family:system-ui;background:#0b1020;color:#eef2ff;padding:40px}}main{{max-width:760px;margin:auto;background:#121a2f;padding:28px;border-radius:16px}}button{{padding:14px 22px;border:0;border-radius:8px;font-weight:700;cursor:pointer}}.a{{background:#22c55e}}.d{{background:#ef4444;color:white}}form{{display:inline-block;margin-right:10px}}</style></head>
<body><main><h1>🔒 OmniShell Approval Required</h1><p>Task <b>#{task_id}</b> is waiting for human authorization.</p>
<form method='post' action='{base}/{task_id}/approve'><input type='hidden' name='token' value='{safe_token}'><button class='a'>✓ Approve &amp; Execute</button></form>
<form method='post' action='{base}/{task_id}/deny'><input type='hidden' name='token' value='{safe_token}'><button class='d'>✕ Deny &amp; Cancel</button></form>
<p>Approval expires automatically. You may close this window after choosing an action.</p></main></body></html>"""
    path=Path(tempfile.gettempdir()) / f"omnishell-approval-{task_id}.html"
    path.write_text(html, encoding="utf-8")
    return path


def _upload_result_with_retry(task_id, payload):
    """Best-effort bounded telemetry upload; never holds execution hostage."""
    started = time.monotonic()
    for attempt in range(SCHEDULER_UPLOAD_MAX_ATTEMPTS):
        if time.monotonic() - started >= SCHEDULER_UPLOAD_BUDGET_SECONDS:
            print(f"[SCHEDULER] Result upload budget exhausted for task {task_id}")
            return False
        try:
            status, _ = _http_json(
                "POST",
                f"{BACKEND_URL}/api/scheduled-tasks/{task_id}/result",
                json=payload,
            )
            if status in {200, 400, 404, 409}:
                return True
        except Exception as e:
            print(f"[SCHEDULER] Result upload failed (attempt {attempt+1}): {e}")
        remaining = SCHEDULER_UPLOAD_BUDGET_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            break
        time.sleep(min(2.0 * (attempt + 1), remaining))
    return False

def _start_scheduler_heartbeat(task_id: int, execution_id: str, cancel_event: threading.Event):
    stop = threading.Event()
    def loop():
        while not stop.wait(15.0):
            try:
                status, payload = _http_json(
                    "POST", f"{BACKEND_URL}/api/scheduled-tasks/{task_id}/heartbeat",
                    json={"execution_id": execution_id},
                )
                if status == 200 and isinstance(payload, dict) and payload.get("status") == "cancelled":
                    cancel_event.set()
                    break
                if status in {404, 409}:
                    break
            except Exception:
                # A temporary backend outage must not kill host execution.
                continue
    thread = threading.Thread(target=loop, daemon=True, name=f"scheduled-heartbeat-{task_id}")
    thread.start()
    return stop, thread


def _report_scheduled_result(task_id: int, execution_id: str, success: bool, result: dict, *, failure_reason=None, is_permanent=False):
    payload = {
        "status": "completed" if success else "failed",
        "execution_id": execution_id,
        "execution_result": result,
    }
    if not success:
        payload["failure_reason"] = failure_reason or result.get("stderr") or result.get("error") or result.get("output") or "Scheduled execution failed"
        payload["is_permanent"] = bool(is_permanent)
    uploaded = _upload_result_with_retry(task_id, payload)
    if not uploaded:
        print(f"[SCHEDULER] Could not persist result for task {task_id}; execution lease will fail closed on the backend.")
    return uploaded


def execute_scheduled_workflow(task):
    task_id = int(task["id"])
    execution_id = uuid.uuid4().hex

    status, response = _http_json(
        "POST", f"{BACKEND_URL}/api/scheduled-tasks/{task_id}/mark-executing",
        json={"execution_token": execution_id},
    )
    if status != 200:
        detail = response.get("detail", response) if isinstance(response, dict) else response
        raise RuntimeError(f"Task {task_id} could not enter executing state: {detail}")

    cancel_event = threading.Event()
    heartbeat_stop, heartbeat_thread = _start_scheduler_heartbeat(task_id, execution_id, cancel_event)
    try:
        raw_wf = task.get("raw_workflow") or {}
        if isinstance(raw_wf, str):
            try: raw_wf = json.loads(raw_wf)
            except Exception: raw_wf = {}
        cap_type = task.get("capability_type") or raw_wf.get("capability_type")

        if cap_type == "reminder" or task.get("is_reminder") or raw_wf.get("is_reminder"):
            msg = task.get("reminder_message") or raw_wf.get("reminder_message") or task.get("original_prompt")
            if not msg:
                raise ValueError("Scheduled reminder has no message")
            notified = send_desktop_notification("OmniShell Scheduled Reminder", str(msg))
            result = {"execution_id": execution_id, "status": "completed", "success": bool(notified),
                      "mode": "desktop_notification", "message": msg, "notification_sent": bool(notified), "scheduled_task_id": task_id}
            _report_scheduled_result(task_id, execution_id, bool(notified), result,
                                     failure_reason="Desktop notification could not be delivered", is_permanent=False)
            return result

        if task.get("requires_browser") or raw_wf.get("requires_browser"):
            target_url = str(task.get("target_url") or raw_wf.get("target_url") or "").strip()
            if not target_url: raise ValueError("Scheduled browser task has no target_url.")
            parsed = urlparse(target_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("Scheduled browser target must be a valid http/https URL.")
            browser_result = open_new_browser_window(target_url)
            result = {"execution_id": execution_id, "status": "completed", "success": True,
                      "mode": "browser_new_window", "target_url": target_url,
                      "browser_launch": browser_result, "scheduled_task_id": task_id}
            _report_scheduled_result(task_id, execution_id, True, result)
            return result

        multi_step = task.get("multi_step_plan") or raw_wf.get("multi_step_plan")
        if multi_step:
            if isinstance(multi_step, str):
                try: multi_step = json.loads(multi_step)
                except Exception: multi_step = None
            if isinstance(multi_step, list) and multi_step:
                cleaned_steps = []
                for step in multi_step:
                    if not isinstance(step, dict):
                        continue
                    cmd = str(step.get("command") or step.get("script") or "").strip()
                    if re.fullmatch(r"sleep\s+\d+", cmd):
                        continue
                    cleaned_steps.append(step)
                if cleaned_steps:
                    exec_steps = cleaned_steps
                    res = execute_multi_step_workflow(exec_steps, approved=True, cancel_event=cancel_event)
                    _report_scheduled_result(task_id, execution_id, bool(res.get("success")),
                                             {**res, "scheduled_task_id": task_id},
                                             failure_reason=res.get("output") or "One or more scheduled steps failed",
                                             is_permanent=False)
                    return res

        cond_logic = task.get("conditional_logic") or raw_wf.get("conditional_logic")
        if cond_logic:
            if isinstance(cond_logic, str):
                try: cond_logic = json.loads(cond_logic)
                except Exception: cond_logic = None
            if isinstance(cond_logic, dict) and str(cond_logic.get("condition_script") or "").strip():
                res = execute_conditional_workflow(
                    condition_script=str(cond_logic["condition_script"]),
                    on_success=cond_logic.get("on_success"),
                    on_failure=cond_logic.get("on_failure"),
                    approved=True,
                    cancel_event=cancel_event,
                )
                _report_scheduled_result(task_id, execution_id, bool(res.get("success")),
                                         {**res, "scheduled_task_id": task_id},
                                         failure_reason=res.get("error") or res.get("output") or "Conditional workflow failed",
                                         is_permanent=res.get("status") in {"invalid_condition", "condition_evaluation_failed"})
                return res

        command = str(task.get("shell_script") or raw_wf.get("shell_script") or "").strip()
        if not command:
            raise ValueError("Scheduled shell task has no shell_script.")
        command = re.sub(r'^\s*sleep\s+\d+\s*(?:;|&&)\s*', '', command).strip()
        if not command:
            raise ValueError("Scheduled shell task became empty after removing scheduler delay.")

        risk = classify_command(command)
        if re.search(r"\brm\s+-[^\n]*r[^\n]*f[^\n]*\s+/(?:\s|\*|$)", command) or re.search(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", command):
            raise PermissionError("Scheduled execution blocked by host risk policy: destructive root operations are prohibited.")

        recovery = task.get("recovery_strategy") or raw_wf.get("recovery_strategy") or {}
        if isinstance(recovery, str):
            try: recovery = json.loads(recovery)
            except Exception: recovery = {}
        result = execute_with_recovery(
            command,
            max_attempts=max(1, min(10, int(recovery.get("retry_limit", 2) or 2))),
            retry_on=recovery.get("retry_on", ["timeout", "connection", "transient"]),
            backoff_seconds=recovery.get("retry_backoff_seconds", [1, 3, 8]),
            fallback_script=recovery.get("fallback_script"),
            diagnostic_command=recovery.get("diagnostic_command"),
            expected_process=task.get("expected_process") or raw_wf.get("expected_process"),
            approved=True,
            idempotency_key=f"scheduled:{task_id}:{execution_id}",
            cancel_event=cancel_event,
        )
        payload = asdict(result)
        _report_scheduled_result(task_id, execution_id, bool(result.success),
                                 {**payload, "scheduled_task_id": task_id, "risk_recheck": risk},
                                 failure_reason=result.stderr or result.output,
                                 is_permanent=result.status in {"syntax_error", "policy_blocked", "approval_required"})
        return payload
    except Exception as exc:
        error_result = {
            "execution_id": execution_id,
            "status": "failed",
            "success": False,
            "error": str(exc),
            "scheduled_task_id": task_id,
        }
        _report_scheduled_result(task_id, execution_id, False, error_result,
                                 failure_reason=str(exc),
                                 is_permanent=isinstance(exc, (ValueError, PermissionError)))
        raise
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2)


def handle_claimed_task(task):
    task_id = int(task["id"])
    with _scheduler_active_lock:
        if task_id in _scheduler_active_ids:
            return
        _scheduler_active_ids.add(task_id)
    try:
        status = str(task.get("status") or "")
        token = str(task.get("approval_token") or "")
        if status == "awaiting_approval":
            if not token:
                print(f"[SCHEDULER] Task {task_id} entered approval state without a token; backend will expire it.")
                return
            try:
                prompt_preview = str(task.get("original_prompt") or "Action authorization required")[:120]
                send_desktop_notification("OmniShell Scheduled Approval", f"Task #{task_id}: {prompt_preview}")
            except Exception as exc:
                print(f"[SCHEDULER] Approval notification failed for {task_id}: {exc}")
            try:
                approval_result = open_approval_document(task_id, token)
                _scheduler_state_update(last_approval_at=time.time(), last_approval_result=approval_result, last_task_id=task_id, last_task_status="awaiting_approval")
                print(f"[SCHEDULER] Approval document opened for task {task_id}: {approval_result}")
            except Exception as exc:
                _scheduler_state_update(last_approval_at=time.time(), last_approval_result={"opened":False,"error":str(exc)}, last_task_id=task_id, last_task_status="awaiting_approval", last_error=str(exc))
                print(f"[SCHEDULER] Approval document launch FAILED for task {task_id}: {exc}")
                # Do not silently leave the task waiting forever. Keep it awaiting approval
                # so the user can use the URL from logs/dashboard, but make the failure explicit.
                try:
                    print(f"[SCHEDULER] Manual approval URL: {_approval_urls(task_id, token)[-1]}")
                except Exception:
                    pass
            # Do not hold a worker open. The backend changes awaiting_approval ->
            # approved, and a later poll claims the approved task.
            return

        if status == "approved":
            try:
                execute_scheduled_workflow(task)
            except Exception as exc:
                print(f"[SCHEDULER] Approved scheduled execution failed for {task_id}: {exc}")
            return

        print(f"[SCHEDULER] Ignoring unexpected claimed task state {status!r} for {task_id}")
    finally:
        with _scheduler_active_lock:
            _scheduler_active_ids.discard(task_id)


def _task_worker(task):
    try: handle_claimed_task(task)
    finally: _scheduler_workers.release()


def scheduler_loop():
    print(f"[SCHEDULER] Started | interval={SCHEDULER_INTERVAL}s workers={SCHEDULER_MAX_WORKERS} backend={BACKEND_URL}")
    consecutive_errors=0
    while not _scheduler_stop.is_set():
        try:
            poll_at=time.time()
            status,data=_http_json("GET",f"{BACKEND_URL}/api/scheduled-tasks/internal/poll")
            _scheduler_state_update(last_poll_at=poll_at, last_poll_status=status, poll_count=_scheduler_state_snapshot()["poll_count"]+1, last_error=None)
            if status==200:
                consecutive_errors=0
                task=data.get("task")
                if task:
                    _scheduler_state_update(last_task_id=task.get("id"), last_task_status=task.get("status"))
                if task and _scheduler_workers.acquire(blocking=False):
                    threading.Thread(target=_task_worker,args=(task,),daemon=True,name=f"scheduled-task-{task.get('id')}").start()
            else:
                consecutive_errors+=1
        except Exception as exc:
            consecutive_errors+=1
            _scheduler_state_update(last_error=str(exc))
            if consecutive_errors in {1,5,20} or consecutive_errors%50==0:
                print(f"[SCHEDULER] Backend unavailable ({consecutive_errors}): {exc}")
        _scheduler_stop.wait(min(max(SCHEDULER_INTERVAL,1)*(2 if consecutive_errors>=5 else 1),15))


def stop_scheduler():
    _scheduler_stop.set()


def main():
    print()
    print("="*60)
    print("        OMNISHELL HOST EXECUTION AGENT V3")
    print("="*60)
    print(f"OS:           {platform.system()}")
    print(f"Architecture: {platform.machine()}")
    shell_name,shell_path=detect_shell()
    print(f"Shell:        {shell_name}")
    print(f"Shell path:   {shell_path}")
    print(f"Host:         {HOST}")
    print(f"Port:         {PORT}")
    print(f"Policy:       {'ENFORCED' if ENFORCE_POLICY else 'PERMISSIVE'}")
    print(f"Scheduler:    {'ENABLED' if SCHEDULER_ENABLED else 'DISABLED'}")
    if platform.system().lower()!="windows":
        print(f"Terminal:     {find_terminal() or 'none'}")
    print("="*60)
    print(f"Health:       http://{HOST}:{PORT}/health")
    print(f"System:       http://{HOST}:{PORT}/system")
    print(f"Executions:   http://{HOST}:{PORT}/executions")
    print(f"Backend:      {BACKEND_URL}")
    print("="*60)
    print()

    if SCHEDULER_ENABLED:
        threading.Thread(target=scheduler_loop,daemon=True,name="omnishell-scheduler").start()
    server=ThreadedHTTPServer((HOST,PORT),ExecutionHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\\n[HOST AGENT] Shutdown requested.")
    finally:
        stop_scheduler()
        for task in REGISTRY.active():
            if task.process:
                try: terminate_process_tree(task.process,force=True)
                except Exception: pass
        server.server_close()
        print("[HOST AGENT] Server stopped.")


if __name__=="__main__":
    main()