#!/usr/bin/env python3
"""
OmniShell Host Execution Agent V3

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

    def create(self, command: str) -> ExecutionTask:
        execution_id = uuid.uuid4().hex

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
) -> ExecutionResult:
    """Execute a command with bounded retries, diagnostics and optional fallback.

    Retries are only attempted for transient failures. Destructive/critical
    commands are never blindly retried. A successful result is cached by the
    optional idempotency key so network-level retries cannot duplicate work.
    """
    cached = _idempotency_get(idempotency_key)
    if cached:
        return cached

    max_attempts = max(1, min(int(max_attempts or 1), 5))
    retry_on = set(retry_on or ["timeout", "connection", "transient"])
    backoff_seconds = backoff_seconds or [1.0, 3.0, 8.0]
    last: Optional[ExecutionResult] = None

    for attempt in range(1, max_attempts + 1):
        result = execute_command(
            command,
            working_directory=working_directory,
            approved=approved,
            expected_process=expected_process,
            expected_path=expected_path,
            expected_absent_path=expected_absent_path,
            environment=environment,
            timeout=timeout,
            dry_run=dry_run,
            execution_id=execution_id if attempt == 1 and execution_id else uuid.uuid4().hex,
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
        if result.status in {"approval_required", "cancelled"} or result.risk_level == "critical":
            break
        failure_class = "timeout" if result.timed_out else ("connection" if any(x in result.stderr.lower() for x in ["connection", "network", "temporarily unavailable"]) else "transient")
        if failure_class not in retry_on or attempt >= max_attempts:
            break
        delay = backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)]
        time.sleep(max(0.0, float(delay)))

    if last is None:
        raise RuntimeError("Recovery executor produced no execution result.")

    # Diagnostics are observational and are not allowed to replace the primary failure.
    if diagnostic_command and not last.success:
        try:
            diag = execute_command(diagnostic_command, working_directory=working_directory, approved=approved, timeout=min(DEFAULT_TIMEOUT, 30))
            last.verification["diagnostic"] = asdict(diag)
        except Exception as exc:
            last.verification["diagnostic_error"] = str(exc)

    # Fallback is opt-in and only runs after the bounded primary retry loop.
    if fallback_script and not last.success and last.risk_level not in {"critical", "high"}:
        try:
            fallback = execute_command(fallback_script, working_directory=working_directory, approved=approved)
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

    _idempotency_put(idempotency_key, last)
    return last


def execute_multi_step_workflow(
    steps: list[dict],
    working_directory: Optional[str] = None,
    continue_on_error: bool = False,
    approved: bool = False,
    max_attempts: int = 2,
) -> dict:
    """Execute structured steps with per-step validation, retries and compensation."""
    step_results = []
    completed_steps: list[dict] = []
    total_success = True
    combined_output = []

    for idx, step in enumerate(steps):
        step_id = step.get("step_id", step.get("step", idx + 1))
        step_name = step.get("name") or step.get("description") or f"Step {step_id}"
        command = step.get("command") or step.get("script") or ""
        if not command:
            step_results.append({"step_id": step_id, "name": step_name, "status": "skipped", "reason": "No executable command provided."})
            continue

        result = execute_with_recovery(
            command,
            working_directory=working_directory,
            approved=approved,
            max_attempts=int(step.get("retry_limit", max_attempts)),
            retry_on=step.get("retry_on"),
            backoff_seconds=step.get("backoff_seconds"),
            expected_process=step.get("expected_process"),
            expected_path=step.get("expected_path"),
            expected_absent_path=step.get("expected_absent_path"),
            fallback_script=step.get("fallback_script"),
            diagnostic_command=step.get("diagnostic_command"),
            idempotency_key=step.get("idempotency_key"),
        )
        res_dict = asdict(result)
        res_dict.update({"step_id": step_id, "name": step_name, "expected": step.get("expected"), "validation": step.get("validation")})
        step_results.append(res_dict)
        combined_output.append(f"--- [{step_name}] ---\n{result.output}")

        if result.success:
            completed_steps.append(step)
            continue

        total_success = False
        # Optional compensation/rollback for already completed steps, in reverse order.
        rollback_results = []
        if step.get("rollback_on_failure", True):
            for completed in reversed(completed_steps):
                rollback = completed.get("rollback_command") or completed.get("compensation_command")
                if not rollback:
                    continue
                try:
                    rb = execute_command(rollback, working_directory=working_directory, approved=approved)
                    rollback_results.append({"step_id": completed.get("step_id", completed.get("step")), "result": asdict(rb)})
                except Exception as exc:
                    rollback_results.append({"step_id": completed.get("step_id", completed.get("step")), "error": str(exc)})
        if rollback_results:
            combined_output.append("--- [Rollback] ---\n" + json.dumps(rollback_results, default=str))
            res_dict["rollback_results"] = rollback_results
        if not continue_on_error:
            break

    return {
        "success": total_success,
        "status": "completed" if total_success else "failed_or_recovered",
        "steps_executed": len(step_results),
        "total_steps": len(steps),
        "step_results": step_results,
        "output": "\n\n".join(combined_output),
        "failure_policy": {"max_attempts": max_attempts, "continue_on_error": continue_on_error, "rollback_enabled": True},
    }


def execute_conditional_workflow(
    condition_script: str,
    on_success: str,
    on_failure: Optional[str] = None,
    working_directory: Optional[str] = None,
    approved: bool = False,
    condition_retries: int = 2,
) -> dict:
    """Evaluate a condition, execute exactly one branch, and preserve evidence."""
    cond_result = execute_with_recovery(
        condition_script,
        working_directory=working_directory,
        approved=approved,
        max_attempts=condition_retries,
    )
    condition_met = cond_result.success and cond_result.exit_code == 0
    branch_script = on_success if condition_met else on_failure
    if not branch_script:
        return {"success": True, "status": "completed", "condition_met": condition_met, "branch_executed": "none", "condition_output": cond_result.output}
    branch_result = execute_with_recovery(branch_script, working_directory=working_directory, approved=approved, max_attempts=2)
    return {
        "success": branch_result.success,
        "status": "completed" if branch_result.success else "failed",
        "condition_met": condition_met,
        "branch_executed": "on_success" if condition_met else "on_failure",
        "condition_output": cond_result.output,
        "branch_result": asdict(branch_result),
        "output": f"Condition ({'PASS' if condition_met else 'FAIL'}):\n{cond_result.output}\n\nBranch Output:\n{branch_result.output}",
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
) -> ExecutionResult:

    if not command or not command.strip():

        raise ValueError(
            "Command cannot be empty."
        )

    execution_id = (
        execution_id
        or uuid.uuid4().hex
    )

    task = REGISTRY.create(command)

    shell_name, shell_path = detect_shell()

    cwd = normalize_working_directory(
        working_directory
    )

    env = sanitize_environment(
        environment
    )

    timeout_seconds = clamp_timeout(
        timeout
    )

    risk = classify_command(
        command
    )

    started = time.time()

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

        def read_stream(
            stream,
            chunks,
            stream_name,
            done_event,
        ):
            try:

                for line in iter(
                    stream.readline,
                    "",
                ):

                    chunks.append(line)

                    task.output_lines.append(
                        line.rstrip("\n")
                    )

                    if output_callback:
                        try:
                            output_callback(
                                stream_name,
                                line,
                            )
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

            if task.cancelled:
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
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            terminate_process_tree(
                process,
                force=True,
            )
            process.wait(timeout=3)

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

        # Short-lived processes are validated using exit code.
        # Process presence is only an additional signal.
        verification[
            "process_detected"
        ] = verify_process(
            expected_process
        )

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

    server_version = "OmniShellHost/3.0"

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
                        "version": "3.0",
                        "os": platform.system(),
                        "port": PORT,
                        "capabilities_supported": 19,
                    }
                )
                return

            if self.path == "/system":
                self._json_response(get_system_info())
                return

            if self.path == "/system/metrics":
                self._json_response(get_realtime_metrics())
                return

            if self.path == "/capabilities":
                self._json_response({
                    "service": "OmniShell Host Execution Agent V3",
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
SCHEDULER_HTTP_TIMEOUT = float(os.getenv("OMNISHELL_SCHEDULER_HTTP_TIMEOUT", "5"))
SCHEDULER_MAX_WORKERS = max(1, int(os.getenv("OMNISHELL_SCHEDULER_MAX_WORKERS", "4")))

_scheduler_stop=threading.Event()
_scheduler_workers=threading.BoundedSemaphore(SCHEDULER_MAX_WORKERS)
_scheduler_active_ids:set[int]=set()
_scheduler_active_lock=threading.RLock()


def _http_json(method,url,**kwargs):
    response=requests.request(method,url,timeout=SCHEDULER_HTTP_TIMEOUT,**kwargs)
    try: payload=response.json()
    except Exception: payload={}
    return response.status_code,payload


def _browser_candidates():
    system=platform.system().lower()
    if system=="windows":
        return [("msedge",["--new-window"]),("chrome",["--new-window"]),("brave",["--new-window"]),("firefox",["--new-window"])]
    if system=="darwin":
        return [("open",["-na","Google Chrome","--args","--new-window"]),("open",["-na","Brave Browser","--args","--new-window"]),("open",["-na","Firefox","--args","--new-window"])]
    return [
        ("brave-browser", ["--new-window"]),
        ("firefox", ["--new-window"]),
        ("google-chrome", ["--new-window"]),
        ("google-chrome-stable", ["--new-window"]),
        ("chromium", ["--new-window"]),
        ("chromium-browser", ["--new-window"]),
        ("xdg-open", []),
        ("x-www-browser", []),
        ("gnome-open", []),
    ]


def open_new_browser_window(url):
    parsed=urlparse(url)
    if parsed.scheme not in {"http","https"}:
        raise ValueError("Browser URL must use http/https.")
    errors=[]
    system=platform.system().lower()
    env = os.environ.copy()
    for executable,args in _browser_candidates():
        resolved=shutil.which(executable)
        if not resolved: continue
        try:
            subprocess.Popen(
                [resolved,*args,url],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,
                start_new_session=system!="windows",
                creationflags=(subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP if system=="windows" else 0),
                env=env,
            )
            return {"opened":True,"browser":executable,"method":"native-new-window","url":url}
        except Exception as exc:
            errors.append(f"{executable}: {exc}")
    try:
        if webbrowser.open_new(url):
            return {"opened":True,"browser":"system-default","method":"webbrowser.open_new","url":url}
    except Exception as exc:
        errors.append(f"webbrowser: {exc}")
    raise RuntimeError("Could not launch a browser approval window." + (f" {' | '.join(errors)}" if errors else ""))


def _upload_result_with_retry(task_id, payload):
    for attempt in range(100):
        try:
            status, _ = _http_json("POST", f"{BACKEND_URL}/api/scheduled-tasks/{task_id}/result", json=payload)
            if status in {200, 400, 404, 409}: return
        except Exception as e:
            print(f"[SCHEDULER] Result upload failed (attempt {attempt+1}): {e}")
        time.sleep(min(5 * (2 ** attempt), 60))

def execute_scheduled_workflow(task):
    task_id = int(task["id"])
    execution_id = uuid.uuid4().hex

    status, response = _http_json(
        "POST", f"{BACKEND_URL}/api/scheduled-tasks/{task_id}/mark-executing",
        json={"execution_token": execution_id},
    )
    if status != 200:
        raise RuntimeError(f"Task {task_id} could not enter executing state: {response.get('detail', response)}")

    raw_wf = task.get("raw_workflow") or {}
    if isinstance(raw_wf, str):
        try: raw_wf = json.loads(raw_wf)
        except Exception: raw_wf = {}

    cap_type = task.get("capability_type") or raw_wf.get("capability_type")

    # 1. Reminder Notification Workflow
    if cap_type == "reminder" or task.get("is_reminder") or raw_wf.get("is_reminder"):
        msg = task.get("reminder_message") or raw_wf.get("reminder_message") or task.get("original_prompt")
        title = "OmniShell Scheduled Reminder"
        send_desktop_notification(title, msg)
        result = {"execution_id": execution_id, "status": "completed", "success": True, "mode": "desktop_notification", "message": msg, "scheduled_task_id": task_id}
        _upload_result_with_retry(task_id, {"status": "completed", "execution_id": execution_id, "execution_result": result})
        return result

    # 2. Browser Operations
    if task.get("requires_browser") or raw_wf.get("requires_browser"):
        target_url = str(task.get("target_url") or raw_wf.get("target_url") or "").strip()
        if not target_url: raise ValueError("Scheduled browser task has no target_url.")
        if urlparse(target_url).scheme not in {"http", "https"}:
            raise ValueError("Scheduled browser target must use http/https.")
        browser_result = open_new_browser_window(target_url)
        result = {"execution_id": execution_id, "status": "completed", "success": True, "mode": "browser_new_window", "target_url": target_url, "browser_launch": browser_result, "scheduled_task_id": task_id}
        _upload_result_with_retry(task_id, {"status": "completed", "execution_id": execution_id, "execution_result": result})
        return result

    # 3. Multi-Step Execution
    multi_step = task.get("multi_step_plan") or raw_wf.get("multi_step_plan")
    if multi_step and isinstance(multi_step, list) and len(multi_step) > 0:
        cleaned_steps = []
        for step in multi_step:
            cmd = (step.get("command") or step.get("script") or "").strip()
            # If the step is only a redundant 'sleep <N>' delay, omit it since the scheduler already waited
            if re.match(r"^sleep\s+\d+$", cmd):
                continue
            cleaned_steps.append(step)
        exec_steps = cleaned_steps if cleaned_steps else multi_step
        res = execute_multi_step_workflow(exec_steps, approved=True)
        final_status = "completed" if res["success"] else "failed"
        _upload_result_with_retry(task_id, {"status": final_status, "execution_id": execution_id, "execution_result": {**res, "scheduled_task_id": task_id}})
        return res

    # 4. Conditional Workflow
    cond_logic = task.get("conditional_logic") or raw_wf.get("conditional_logic")
    if cond_logic and isinstance(cond_logic, dict) and cond_logic.get("condition_script"):
        res = execute_conditional_workflow(
            condition_script=cond_logic["condition_script"],
            on_success=cond_logic.get("on_success", "echo 'Condition passed'"),
            on_failure=cond_logic.get("on_failure"),
            approved=True,
        )
        final_status = "completed" if res["success"] else "failed"
        _upload_result_with_retry(task_id, {"status": final_status, "execution_id": execution_id, "execution_result": {**res, "scheduled_task_id": task_id}})
        return res

    # 5. Standard Shell Execution
    command = str(task.get("shell_script") or raw_wf.get("shell_script") or "").strip()
    if not command: raise ValueError("Scheduled shell task has no shell_script.")
    
    # Strip any redundant leading sleep command since the scheduler handles timing
    command = re.sub(r'^\s*sleep\s+\d+\s*(?:;|&&)\s*', '', command)
    
    risk = classify_command(command)
    # Block only truly catastrophic root filesystem destruction
    if re.search(r"\brm\s+-[^\n]*r[^\n]*f[^\n]*\s+/(?:\s|\*|$)", command) or re.search(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", command):
        raise PermissionError("Scheduled execution blocked by host risk policy: destructive root operations are prohibited.")

    recovery = task.get("recovery_strategy") or raw_wf.get("recovery_strategy") or {}
    result = execute_with_recovery(
        command,
        max_attempts=int(recovery.get("retry_limit", 2)),
        retry_on=recovery.get("retry_on", ["timeout", "connection", "transient"]),
        backoff_seconds=recovery.get("retry_backoff_seconds", [1, 3, 8]),
        fallback_script=recovery.get("fallback_script"),
        diagnostic_command=recovery.get("diagnostic_command"),
        expected_process=task.get("expected_process") or raw_wf.get("expected_process"),
        approved=True,
        idempotency_key=f"scheduled:{task_id}:{execution_id}",
    )
    payload = asdict(result)
    final_status = "completed" if result.success else "failed"
    _upload_result_with_retry(task_id, {"status": final_status, "execution_id": execution_id,
                     "execution_result": {**payload, "scheduled_task_id": task_id, "risk_recheck": risk},
                     "failure_reason": None if result.success else result.stderr or result.output})
    return payload


def handle_claimed_task(task):
    task_id=int(task["id"])
    with _scheduler_active_lock:
        if task_id in _scheduler_active_ids: return
        _scheduler_active_ids.add(task_id)
    try:
        token=str(task.get("approval_token") or "")
        # Safe scheduled work is pre-approved by the backend. Only approval-gated
        # work receives an approval token and opens the approval UI.
        if not token and task.get("status") == "approved":
            try:
                execute_scheduled_workflow(task)
            except Exception as exc:
                print(f"[SCHEDULER] Approved scheduled execution failed: {exc}")
                _upload_result_with_retry(task_id, {"status":"failed","execution_id":None,"failure_reason":str(exc),"is_permanent":isinstance(exc,(ValueError,PermissionError)),"execution_result":{"scheduled_task_id":task_id}})
            return
        if not token: raise RuntimeError("No approval token was returned for approval-gated task.")
        approval_url=f"{APPROVAL_UI_BASE}/{token}?taskId={task_id}"
        print(f"[SCHEDULER] Task {task_id} due; opening approval window.")
        try: open_new_browser_window(approval_url)
        except Exception as exc: print(f"[SCHEDULER] Approval browser launch failed: {exc}")

        started=time.monotonic()
        resolved=False
        while not _scheduler_stop.is_set():
            if time.monotonic()-started>=APPROVAL_TIMEOUT: break
            try:
                status,data=_http_json("GET",f"{BACKEND_URL}/api/scheduled-tasks/{task_id}")
                if status==200:
                    current=data.get("status")
                    if current in {"approved", "executing"}:
                        resolved=True
                        if current == "approved":
                            try: execute_scheduled_workflow(task)
                            except Exception as exc:
                                print(f"[SCHEDULER] Execution failed: {exc}")
                                _upload_result_with_retry(task_id, {"status":"failed","execution_id":None,"failure_reason":str(exc),"is_permanent":isinstance(exc, (ValueError, PermissionError)),"execution_result":{"scheduled_task_id":task_id}})
                        break
                    if current in {"denied","cancelled","expired","completed","failed"}:
                        resolved=True
                        break
                elif status==404:
                    resolved=True
                    break
            except Exception as exc:
                print(f"[SCHEDULER] Temporary status error for {task_id}: {exc}")
            _scheduler_stop.wait(1.0)

        if not resolved and not _scheduler_stop.is_set():
            try: _http_json("POST",f"{BACKEND_URL}/api/scheduled-tasks/{task_id}/expire")
            except Exception as exc: print(f"[SCHEDULER] Expiry update failed: {exc}")
    finally:
        with _scheduler_active_lock: _scheduler_active_ids.discard(task_id)


def _task_worker(task):
    try: handle_claimed_task(task)
    finally: _scheduler_workers.release()


def scheduler_loop():
    print(f"[SCHEDULER] Started | interval={SCHEDULER_INTERVAL}s workers={SCHEDULER_MAX_WORKERS} backend={BACKEND_URL}")
    consecutive_errors=0
    while not _scheduler_stop.is_set():
        try:
            status,data=_http_json("GET",f"{BACKEND_URL}/api/scheduled-tasks/internal/poll")
            if status==200:
                consecutive_errors=0
                task=data.get("task")
                if task and _scheduler_workers.acquire(blocking=False):
                    threading.Thread(target=_task_worker,args=(task,),daemon=True,name=f"scheduled-task-{task.get('id')}").start()
            else:
                consecutive_errors+=1
        except Exception as exc:
            consecutive_errors+=1
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