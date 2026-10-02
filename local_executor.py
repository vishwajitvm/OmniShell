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

import urllib.parse
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
import sys
import webbrowser


# Enable ANSI Virtual Terminal processing on Windows if applicable
if platform.system().lower() == "windows":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


HOST = os.getenv("OMNISHELL_HOST", "127.0.0.1")
PORT = int(os.getenv("OMNISHELL_PORT", "8003"))
DEFAULT_TIMEOUT = float(os.getenv("OMNISHELL_DEFAULT_TIMEOUT", "300"))
MAX_TIMEOUT = float(os.getenv("OMNISHELL_MAX_TIMEOUT", "3600"))
ENFORCE_POLICY = os.getenv("OMNISHELL_ENFORCE_POLICY", "false").lower() in {"1", "true", "yes", "on"}
REQUIRE_RISK_APPROVAL = os.getenv("OMNISHELL_REQUIRE_RISK_APPROVAL", "true").lower() in {"1", "true", "yes", "on"}
MAX_HISTORY = int(os.getenv("OMNISHELL_MAX_HISTORY", "500"))
MAX_RECOVERY_ATTEMPTS = int(os.getenv("OMNISHELL_MAX_RECOVERY_ATTEMPTS", "5"))
EXECUTION_BUDGET_SECONDS = float(os.getenv("OMNISHELL_EXECUTION_BUDGET_SECONDS", "300"))
MAX_OUTPUT_BYTES = int(os.getenv("OMNISHELL_MAX_OUTPUT_BYTES", str(10 * 1024 * 1024)))
SCHEDULER_ENABLED = os.getenv("OMNISHELL_SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
SCHEDULER_INTERVAL = max(1, int(os.getenv("OMNISHELL_SCHEDULER_INTERVAL_SECONDS", "2")))
APPROVAL_TIMEOUT = max(30, int(os.getenv("OMNISHELL_APPROVAL_TIMEOUT_SECONDS", "300")))
BACKEND_URL = os.getenv("OMNISHELL_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
APPROVAL_UI_BASE = os.getenv("OMNISHELL_APPROVAL_UI_BASE", "http://127.0.0.1:3000/scheduled-approval").rstrip("/")
APPROVAL_BACKEND_BASE = os.getenv("OMNISHELL_APPROVAL_BACKEND_BASE", f"{BACKEND_URL}/api/scheduled-tasks").rstrip("/")
SCHEDULER_HTTP_TIMEOUT = float(os.getenv("OMNISHELL_SCHEDULER_HTTP_TIMEOUT", "5"))
SCHEDULER_MAX_WORKERS = max(1, int(os.getenv("OMNISHELL_SCHEDULER_MAX_WORKERS", "4")))
SCHEDULER_UPLOAD_MAX_ATTEMPTS = int(os.getenv("OMNISHELL_UPLOAD_MAX_ATTEMPTS", "5"))
SCHEDULER_UPLOAD_BUDGET_SECONDS = float(os.getenv("OMNISHELL_UPLOAD_BUDGET_SECONDS", "30"))


# ============================================================
# RICH ANSI CONSOLE FORMATTER & LOGGER
# ============================================================

class ConsoleLogger:
    """Provides structured, high-readability terminal logs with ANSI styling."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    GRAY = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Rich Background Badges
    BG_GREEN = "\033[42;1m\033[30m"
    BG_RED = "\033[41;1m\033[97m"
    BG_YELLOW = "\033[43;1m\033[30m"
    BG_BLUE = "\033[44;1m\033[97m"
    BG_MAGENTA = "\033[45;1m\033[97m"
    BG_CYAN = "\033[46;1m\033[30m"

    # Dark background pills
    PILL_DARK = "\033[48;5;236m\033[37m"
    PILL_CYAN = "\033[48;5;24m\033[96m\033[1m"
    PILL_GREEN = "\033[48;5;22m\033[92m\033[1m"
    PILL_YELLOW = "\033[48;5;58m\033[93m\033[1m"
    PILL_RED = "\033[48;5;52m\033[91m\033[1m"
    PILL_PURPLE = "\033[48;5;54m\033[95m\033[1m"

    _lock = threading.Lock()

    @classmethod
    def timestamp(cls) -> str:
        return time.strftime("%H:%M:%S")

    @classmethod
    def _clean_len(cls, text: str) -> int:
        return len(re.sub(r'\033\[[0-9;]*m', '', text))

    @classmethod
    def banner(cls, info: dict[str, Any]):
        with cls._lock:
            w = 76
            print()
            print(f"{cls.BRIGHT_CYAN}╔{'═' * (w - 2)}╗{cls.RESET}")
            title = f"{cls.BOLD}{cls.BRIGHT_WHITE}OMNISHELL HOST EXECUTION ENGINE V4{cls.RESET}"
            title_clean = "OMNISHELL HOST EXECUTION ENGINE V4"
            print(f"{cls.BRIGHT_CYAN}║{cls.RESET}{' ' * ((w - 2 - len(title_clean)) // 2)}{title}{' ' * (w - 2 - len(title_clean) - (w - 2 - len(title_clean)) // 2)}{cls.BRIGHT_CYAN}║{cls.RESET}")
            sub = f"{cls.DIM}{cls.BRIGHT_BLUE}Intelligent Autonomous Host Bridge & Guarded Execution{cls.RESET}"
            sub_clean = "Intelligent Autonomous Host Bridge & Guarded Execution"
            print(f"{cls.BRIGHT_CYAN}║{cls.RESET}{' ' * ((w - 2 - len(sub_clean)) // 2)}{sub}{' ' * (w - 2 - len(sub_clean) - (w - 2 - len(sub_clean)) // 2)}{cls.BRIGHT_CYAN}║{cls.RESET}")
            print(f"{cls.BRIGHT_CYAN}╠{'═' * (w - 2)}╣{cls.RESET}")

            def row(k1, v1_colored, v1_clean, k2, v2_colored, v2_clean):
                col1 = f"  {cls.BRIGHT_CYAN}●{cls.RESET} {cls.BOLD}{k1}:{cls.RESET} {v1_colored}"
                col2 = f"{cls.BRIGHT_CYAN}●{cls.RESET} {cls.BOLD}{k2}:{cls.RESET} {v2_colored}"
                c1_len = 4 + len(k1) + 2 + len(v1_clean)
                c2_len = 2 + len(k2) + 2 + len(v2_clean)
                pad = max(2, w - 2 - c1_len - c2_len)
                print(f"{cls.BRIGHT_CYAN}║{cls.RESET}{col1}{' ' * pad}{col2} {cls.BRIGHT_CYAN}║{cls.RESET}")

            policy_colored = f"{cls.PILL_GREEN} PERMISSIVE (Guarded) {cls.RESET}" if not ENFORCE_POLICY else f"{cls.PILL_YELLOW} ENFORCED {cls.RESET}"
            policy_clean = " PERMISSIVE (Guarded) " if not ENFORCE_POLICY else " ENFORCED "

            sched_colored = f"{cls.PILL_GREEN} ACTIVE (Poll: {SCHEDULER_INTERVAL}s) {cls.RESET}" if SCHEDULER_ENABLED else f"{cls.PILL_DARK} DISABLED {cls.RESET}"
            sched_clean = f" ACTIVE (Poll: {SCHEDULER_INTERVAL}s) " if SCHEDULER_ENABLED else " DISABLED "

            os_clean = f"{info.get('os')} ({info.get('arch')})"
            row("OS", f"{cls.WHITE}{os_clean}{cls.RESET}", os_clean, "Shell", f"{cls.WHITE}{info.get('shell')}{cls.RESET}", str(info.get('shell')))
            host_clean = f"http://{info.get('host')}:{info.get('port')}"
            backend_clean = str(info.get('backend'))
            row("Host", f"{cls.CYAN}{host_clean}{cls.RESET}", host_clean, "Backend", f"{cls.CYAN}{backend_clean}{cls.RESET}", backend_clean)
            term_clean = str(info.get('terminal') or 'none')
            row("Policy", policy_colored, policy_clean, "Terminal", f"{cls.WHITE}{term_clean}{cls.RESET}", term_clean)
            row("Scheduler", sched_colored, sched_clean, "Workers", f"{cls.PILL_CYAN} {SCHEDULER_MAX_WORKERS} Threads {cls.RESET}", f" {SCHEDULER_MAX_WORKERS} Threads ")

            print(f"{cls.BRIGHT_CYAN}╠{'═' * (w - 2)}╣{cls.RESET}")
            head_title = "Available System Endpoints:"
            print(f"{cls.BRIGHT_CYAN}║{cls.RESET}  {cls.BOLD}{cls.BRIGHT_WHITE}{head_title}{cls.RESET}{' ' * (w - 4 - len(head_title))}{cls.BRIGHT_CYAN}║{cls.RESET}")

            def endpoint_row(name, url):
                clean_line = f"   ➜ {name}: {url}"
                pad = max(2, w - 2 - len(clean_line))
                print(f"{cls.BRIGHT_CYAN}║{cls.RESET}   {cls.BRIGHT_GREEN}➜{cls.RESET} {cls.BOLD}{name}:{cls.RESET} {cls.UNDERLINE}{cls.CYAN}{url}{cls.RESET}{' ' * pad}{cls.BRIGHT_CYAN}║{cls.RESET}")

            endpoint_row("Health", f"http://{info.get('host')}:{info.get('port')}/health")
            endpoint_row("System", f"http://{info.get('host')}:{info.get('port')}/system")
            endpoint_row("Executions", f"http://{info.get('host')}:{info.get('port')}/executions")
            print(f"{cls.BRIGHT_CYAN}╚{'═' * (w - 2)}╝{cls.RESET}")
            print()

    @classmethod
    def log_request(cls, method: str, path: str, status_code: int = 200, summary: str = "", duration_ms: Optional[int] = None):
        with cls._lock:
            ts = cls.timestamp()
            if method == "OPTIONS":
                print(f"{cls.GRAY}[{ts}] ⚙️  {cls.PILL_DARK} OPTIONS {cls.RESET} {cls.DIM}{path} → 200 OK (CORS Preflight){cls.RESET}")
                return

            if status_code < 300:
                s_color = f"{cls.PILL_GREEN} {status_code} OK {cls.RESET}"
            elif status_code < 400:
                s_color = f"{cls.PILL_CYAN} {status_code} {cls.RESET}"
            elif status_code < 500:
                s_color = f"{cls.PILL_YELLOW} {status_code} CLIENT ERROR {cls.RESET}"
            else:
                s_color = f"{cls.PILL_RED} {status_code} SERVER ERROR {cls.RESET}"

            dur_str = f" {cls.PILL_DARK} {duration_ms}ms {cls.RESET}" if duration_ms is not None else ""
            sum_str = f" {cls.GRAY}• {summary}{cls.RESET}" if summary else ""

            icon = "🌐" if "browser" in path else ("⚡" if "execute" in path else ("🔍" if method == "GET" else "📡"))
            print(f"{cls.GRAY}[{ts}]{cls.RESET} {icon} {cls.BOLD}{cls.BRIGHT_WHITE}{method:<5}{cls.RESET} {cls.CYAN}{path:<24}{cls.RESET} → {s_color}{dur_str}{sum_str}")

    @classmethod
    def log_execution(cls, res: Any):
        with cls._lock:
            ts = cls.timestamp()
            w = 80
            success = bool(getattr(res, "success", False) or (isinstance(res, dict) and res.get("success")))
            start_badge = f"{cls.BG_GREEN} ▶ START {cls.RESET}" if success else f"{cls.BG_RED} ▶ START {cls.RESET}"
            status_badge = f"{cls.PILL_GREEN} ✓ COMPLETED {cls.RESET}" if success else f"{cls.PILL_RED} ✕ FAILED {cls.RESET}"
            end_badge = f"{cls.BG_GREEN} ◀ END {cls.RESET}" if success else f"{cls.BG_RED} ◀ END {cls.RESET}"
            border_color = cls.BRIGHT_GREEN if success else cls.BRIGHT_RED

            cmd = getattr(res, "command", "") if hasattr(res, "command") else (res.get("command", "") if isinstance(res, dict) else "")
            exec_id = getattr(res, "execution_id", "") if hasattr(res, "execution_id") else (res.get("execution_id", "") if isinstance(res, dict) else "")
            dur = getattr(res, "duration_ms", 0) if hasattr(res, "duration_ms") else (res.get("duration_ms", 0) if isinstance(res, dict) else 0)
            exit_code = getattr(res, "exit_code", None) if hasattr(res, "exit_code") else (res.get("exit_code") if isinstance(res, dict) else None)
            work_dir = getattr(res, "working_directory", "") if hasattr(res, "working_directory") else (res.get("working_directory", "") if isinstance(res, dict) else "")
            risk_level = str(getattr(res, "risk_level", "safe") if hasattr(res, "risk_level") else (res.get("risk_level", "safe") if isinstance(res, dict) else "safe"))
            output_text = getattr(res, "output", "") if hasattr(res, "output") else (res.get("output", "") if isinstance(res, dict) else "")
            process_pid = getattr(res, "process_pid", None) if hasattr(res, "process_pid") else (res.get("process_pid") if isinstance(res, dict) else None)
            shell_name = getattr(res, "shell", "bash") if hasattr(res, "shell") else (res.get("shell", "bash") if isinstance(res, dict) else "bash")

            # Duration and Exit Code Badges
            dur_seconds = dur / 1000.0 if dur is not None else 0.0
            time_badge = f"{cls.PILL_CYAN} ⏱️  {dur}ms ({dur_seconds:.2f}s) {cls.RESET}"
            exit_badge = f"{cls.PILL_GREEN} Exit: 0 {cls.RESET}" if exit_code == 0 else f"{cls.PILL_RED} Exit: {exit_code} {cls.RESET}"

            # Risk Badge
            if risk_level.lower() in ("safe", "low"):
                risk_badge = f"{cls.PILL_GREEN} Risk: {risk_level.upper()} {cls.RESET}"
            elif risk_level.lower() in ("moderate", "medium"):
                risk_badge = f"{cls.PILL_YELLOW} Risk: {risk_level.upper()} {cls.RESET}"
            else:
                risk_badge = f"{cls.PILL_RED} Risk: {risk_level.upper()} {cls.RESET}"

            divider = f"{border_color}│{cls.RESET}  {cls.DIM}{'─' * (w - 6)}{cls.RESET}"
            top_bar = "─" * max(2, w - 50)
            bot_bar = "─" * max(2, w - 54)

            print()
            print(f"{border_color}┌───► {start_badge} {cls.BOLD}{cls.BRIGHT_WHITE}HOST COMMAND EXECUTION{cls.RESET}  {status_badge} {border_color}{top_bar}{cls.RESET}")
            pid_str = f"  {cls.GRAY}│{cls.RESET}  {cls.PILL_DARK} {shell_name} (PID: {process_pid}) {cls.RESET}" if process_pid else f"  {cls.GRAY}│{cls.RESET}  {cls.PILL_DARK} {shell_name} {cls.RESET}"
            print(f"{border_color}│{cls.RESET}  {cls.BOLD}Time:{cls.RESET} {cls.WHITE}{ts}{cls.RESET}  {cls.GRAY}│{cls.RESET}  {time_badge}  {cls.GRAY}│{cls.RESET}  {exit_badge}  {cls.GRAY}│{cls.RESET}  {risk_badge}{pid_str}")
            if exec_id:
                id_str = str(exec_id)[:24] + "..." if len(str(exec_id)) > 24 else str(exec_id)
                print(f"{border_color}│{cls.RESET}  {cls.GRAY}ID:{cls.RESET} {cls.DIM}{id_str}{cls.RESET}")

            prompt = getattr(res, "prompt", None) if hasattr(res, "prompt") else (res.get("prompt") if isinstance(res, dict) else None)
            if not prompt:
                prompt = getattr(res, "natural_language_prompt", None) if hasattr(res, "natural_language_prompt") else (res.get("natural_language_prompt") if isinstance(res, dict) else None)
            if not prompt:
                prompt = getattr(res, "original_prompt", None) if hasattr(res, "original_prompt") else (res.get("original_prompt") if isinstance(res, dict) else None)

            if prompt:
                print(divider)
                p_clean = str(prompt).strip()
                print(f"{border_color}│{cls.RESET}  {cls.PILL_PURPLE} 💬 USER PROMPT {cls.RESET}  {cls.BOLD}{cls.BRIGHT_WHITE}\"{p_clean}\"{cls.RESET}")

            print(divider)
            print(f"{border_color}│{cls.RESET}  {cls.PILL_CYAN} ⚡ COMMAND {cls.RESET}  {cls.BRIGHT_YELLOW}$ {str(cmd).strip()}{cls.RESET}")
            if work_dir:
                print(f"{border_color}│{cls.RESET}  {cls.GRAY}📂 Directory:{cls.RESET} {cls.DIM}{work_dir}{cls.RESET}")

            out_sample = str(output_text or "").strip()
            if out_sample:
                print(divider)
                lines = out_sample.splitlines()
                byte_count = len(out_sample.encode("utf-8"))
                size_str = f"{byte_count} B" if byte_count < 1024 else f"{byte_count/1024:.1f} KB"
                print(f"{border_color}│{cls.RESET}  {cls.PILL_DARK} 📋 TERMINAL OUTPUT ({len(lines)} lines, {size_str}) {cls.RESET}")
                preview_lines = lines[:6]
                for p_idx, pl in enumerate(preview_lines):
                    pl_clean = pl[:75]
                    print(f"{border_color}│{cls.RESET}    {cls.DIM}{p_idx+1:02d} │{cls.RESET} {cls.WHITE}{pl_clean}{cls.RESET}")
                if len(lines) > 6:
                    print(f"{border_color}│{cls.RESET}    {cls.DIM}   └── ... ({len(lines) - 6} more lines captured){cls.RESET}")

            print(f"{border_color}└───◄ {end_badge} {cls.BOLD}{cls.BRIGHT_WHITE}EXECUTION FINISHED{cls.RESET}  {time_badge} {exit_badge} {border_color}{bot_bar}{cls.RESET}")
            print()

    @classmethod
    def log_multistep(cls, res: dict[str, Any]):
        with cls._lock:
            w = 80
            ts = cls.timestamp()
            success = bool(res.get("success", False))
            start_badge = f"{cls.BG_GREEN} ▶ START {cls.RESET}" if success else f"{cls.BG_RED} ▶ START {cls.RESET}"
            status_badge = f"{cls.PILL_GREEN} ✓ COMPLETED {cls.RESET}" if success else f"{cls.BG_RED} ✕ FAILED {cls.RESET}"
            end_badge = f"{cls.BG_GREEN} ◀ END {cls.RESET}" if success else f"{cls.BG_RED} ◀ END {cls.RESET}"
            border_color = cls.BRIGHT_GREEN if success else cls.BRIGHT_RED

            step_list = res.get("step_results") or res.get("steps") or []
            total_steps = res.get("total_steps") or len(step_list)
            completed_steps = sum(1 for s in step_list if s.get("success"))

            dur = res.get("duration_ms", 0)
            dur_seconds = dur / 1000.0 if dur else 0.0
            time_badge = f"{cls.PILL_CYAN} ⏱️  {dur}ms ({dur_seconds:.2f}s) {cls.RESET}" if dur else ""

            divider = f"{border_color}│{cls.RESET}  {cls.DIM}{'─' * (w - 6)}{cls.RESET}"
            top_bar = "─" * max(2, w - 48)
            bot_bar = "─" * max(2, w - 50)

            print()
            print(f"{border_color}┌───► {start_badge} {cls.BOLD}{cls.BRIGHT_WHITE}MULTI-STEP WORKFLOW{cls.RESET}  {status_badge} {border_color}{top_bar}{cls.RESET}")
            print(f"{border_color}│{cls.RESET}  {cls.BOLD}Time:{cls.RESET} {cls.WHITE}{ts}{cls.RESET}  {cls.GRAY}│{cls.RESET}  {cls.PILL_DARK} Steps: {total_steps} {cls.RESET}  {cls.GRAY}│{cls.RESET}  {cls.PILL_GREEN if completed_steps == total_steps else cls.PILL_YELLOW} Completed: {completed_steps}/{total_steps} {cls.RESET}  {time_badge}")

            prompt = res.get("prompt") or res.get("natural_language_prompt") or res.get("original_prompt")
            if prompt:
                print(divider)
                print(f"{border_color}│{cls.RESET}  {cls.PILL_PURPLE} 💬 USER PROMPT {cls.RESET}  {cls.BOLD}{cls.BRIGHT_WHITE}\"{str(prompt).strip()}\"{cls.RESET}")

            print(divider)
            print(f"{border_color}│{cls.RESET}  {cls.PILL_CYAN} 📋 STEP-BY-STEP EXECUTION {cls.RESET}")
            for idx, st in enumerate(step_list):
                s_ok = st.get("success", False)
                s_badge = f"{cls.PILL_GREEN} ✓ DONE {cls.RESET}" if s_ok else f"{cls.PILL_RED} ✕ FAILED {cls.RESET}"
                s_desc = st.get("name") or st.get("description") or f"Step {idx + 1}"
                s_cmd = (st.get("command") or st.get("script") or "")
                s_exit = st.get("exit_code")
                exit_str = f" {cls.PILL_DARK} Exit: {s_exit} {cls.RESET}" if s_exit is not None else ""
                print(f"{border_color}│{cls.RESET}    {s_badge} {cls.BOLD}Step {idx + 1}:{cls.RESET} {cls.WHITE}{s_desc}{cls.RESET}{exit_str}")
                if s_cmd:
                    print(f"{border_color}│{cls.RESET}       {cls.DIM}${cls.RESET} {cls.BRIGHT_YELLOW}{s_cmd}{cls.RESET}")

            print(f"{border_color}└───◄ {end_badge} {cls.BOLD}{cls.BRIGHT_WHITE}WORKFLOW FINISHED{cls.RESET}  {time_badge} {border_color}{bot_bar}{cls.RESET}")
            print()

    @classmethod
    def log_conditional(cls, res: dict[str, Any]):
        with cls._lock:
            w = 80
            ts = cls.timestamp()
            success = res.get("success", False)
            start_badge = f"{cls.BG_GREEN} ▶ START {cls.RESET}" if success else f"{cls.BG_RED} ▶ START {cls.RESET}"
            status_badge = f"{cls.PILL_GREEN} ✓ COMPLETED {cls.RESET}" if success else f"{cls.BG_RED} ✕ FAILED {cls.RESET}"
            end_badge = f"{cls.BG_GREEN} ◀ END {cls.RESET}" if success else f"{cls.BG_RED} ◀ END {cls.RESET}"
            border_color = cls.BRIGHT_GREEN if success else cls.BRIGHT_RED

            divider = f"{border_color}│{cls.RESET}  {cls.DIM}{'─' * (w - 6)}{cls.RESET}"
            top_bar = "─" * max(2, w - 50)
            bot_bar = "─" * max(2, w - 52)

            print()
            print(f"{border_color}┌───► {start_badge} {cls.BOLD}{cls.BRIGHT_WHITE}CONDITIONAL WORKFLOW{cls.RESET}  {status_badge} {border_color}{top_bar}{cls.RESET}")
            branch = str(res.get('branch_taken', 'unknown')).upper()
            branch_pill = f"{cls.PILL_CYAN} Branch: {branch} {cls.RESET}"
            cond_exit = res.get('condition_exit_code')
            print(f"{border_color}│{cls.RESET}  {cls.BOLD}Time:{cls.RESET} {cls.WHITE}{ts}{cls.RESET}  {cls.GRAY}│{cls.RESET}  {branch_pill}  {cls.GRAY}│{cls.RESET}  {cls.PILL_DARK} Cond Exit: {cond_exit} {cls.RESET}")

            prompt = res.get("prompt") or res.get("natural_language_prompt") or res.get("original_prompt")
            if prompt:
                print(divider)
                print(f"{border_color}│{cls.RESET}  {cls.PILL_PURPLE} 💬 USER PROMPT {cls.RESET}  {cls.BOLD}{cls.BRIGHT_WHITE}\"{str(prompt).strip()}\"{cls.RESET}")

            print(divider)
            cond_res = res.get("condition_result", {})
            cond_cmd = str(cond_res.get("command") or "")
            if cond_cmd:
                print(f"{border_color}│{cls.RESET}  {cls.PILL_YELLOW} 🔍 CONDITION {cls.RESET}  {cls.YELLOW}$ {cond_cmd}{cls.RESET}")

            branch_res = res.get("branch_result", {})
            branch_cmd = str(branch_res.get("command") or "")
            if branch_cmd:
                print(f"{border_color}│{cls.RESET}  {cls.PILL_CYAN} ⚡ ACTION {cls.RESET}  {cls.BRIGHT_WHITE}$ {branch_cmd}{cls.RESET}")

            print(f"{border_color}└───◄ {end_badge} {cls.BOLD}{cls.BRIGHT_WHITE}CONDITIONAL FINISHED{cls.RESET}  {border_color}{bot_bar}{cls.RESET}")
            print()

    @classmethod
    def log_approval_prompt(cls, task_id: int, prompt: str, result: dict[str, Any]):
        with cls._lock:
            w = 80
            ts = cls.timestamp()
            border_color = cls.BRIGHT_YELLOW
            start_badge = f"{cls.BG_YELLOW} ▶ START {cls.RESET}"
            end_badge = f"{cls.BG_YELLOW} ◀ END {cls.RESET}"
            divider = f"{border_color}│{cls.RESET}  {cls.DIM}{'─' * (w - 6)}{cls.RESET}"
            top_bar = "─" * max(2, w - 54)
            bot_bar = "─" * max(2, w - 50)

            print()
            print(f"{border_color}┌───► {start_badge} {cls.BOLD}{cls.BRIGHT_WHITE}HUMAN APPROVAL REQUIRED{cls.RESET}  {cls.BG_YELLOW} ACTION REQ {cls.RESET} {border_color}{top_bar}{cls.RESET}")
            print(f"{border_color}│{cls.RESET}  {cls.BOLD}Time:{cls.RESET} {cls.WHITE}{ts}{cls.RESET}  {cls.GRAY}│{cls.RESET}  {cls.PILL_PURPLE} Task ID: #{task_id} {cls.RESET}")
            print(divider)
            print(f"{border_color}│{cls.RESET}  {cls.PILL_PURPLE} 💬 REQUEST PROMPT {cls.RESET}  \"{cls.BOLD}{cls.BRIGHT_WHITE}{prompt}{cls.RESET}\"")
            print(divider)

            browser_name = result.get("browser", "default-browser")
            method = result.get("method", "native-new-window")
            url = result.get("url", "")
            print(f"{border_color}│{cls.RESET}  {cls.BOLD}Browser Launched:{cls.RESET} {cls.PILL_GREEN} {browser_name} ({method}) {cls.RESET}")
            if url:
                print(f"{border_color}│{cls.RESET}  {cls.BOLD}Approval URL:{cls.RESET} {cls.UNDERLINE}{cls.BRIGHT_CYAN}{url}{cls.RESET}")
            print(f"{border_color}│{cls.RESET}  {cls.DIM}⏳ Waiting for human confirmation in browser...{cls.RESET}")
            print(f"{border_color}└───◄ {end_badge} {cls.BOLD}{cls.BRIGHT_WHITE}WAITING APPROVAL{cls.RESET} {border_color}{bot_bar}{cls.RESET}")
            print()

    @classmethod
    def log_scheduled_run(cls, task_id: int, is_recurring: bool, rule: str, command: str, result: dict[str, Any]):
        with cls._lock:
            w = 80
            ts = cls.timestamp()
            success = result.get("success", False)
            start_badge = f"{cls.BG_GREEN} ▶ START {cls.RESET}" if success else f"{cls.BG_RED} ▶ START {cls.RESET}"
            status_badge = f"{cls.PILL_GREEN} ✓ SUCCESS {cls.RESET}" if success else f"{cls.PILL_RED} ✕ FAILED {cls.RESET}"
            end_badge = f"{cls.BG_GREEN} ◀ END {cls.RESET}" if success else f"{cls.BG_RED} ◀ END {cls.RESET}"
            border_color = cls.BRIGHT_MAGENTA if is_recurring else cls.BRIGHT_BLUE
            title = "RECURRING WORKFLOW" if is_recurring else "SCHEDULED TASK"

            exit_code = result.get("exit_code")
            dur = result.get("duration_ms", 0)
            dur_seconds = dur / 1000.0 if dur else 0.0
            time_badge = f"{cls.PILL_CYAN} ⏱️  {dur}ms ({dur_seconds:.2f}s) {cls.RESET}" if dur else ""
            exit_badge = f"{cls.PILL_GREEN} Exit: 0 {cls.RESET}" if exit_code == 0 else f"{cls.PILL_RED} Exit: {exit_code} {cls.RESET}"

            divider = f"{border_color}│{cls.RESET}  {cls.DIM}{'─' * (w - 6)}{cls.RESET}"
            top_bar = "─" * max(2, w - 50)
            bot_bar = "─" * max(2, w - 52)

            print()
            print(f"{border_color}┌───► {start_badge} {cls.BOLD}{cls.BRIGHT_WHITE}{title}{cls.RESET}  {status_badge} {border_color}{top_bar}{cls.RESET}")
            print(f"{border_color}│{cls.RESET}  {cls.BOLD}Time:{cls.RESET} {cls.WHITE}{ts}{cls.RESET}  {cls.GRAY}│{cls.RESET}  {cls.PILL_PURPLE} Task ID: #{task_id} {cls.RESET}  {cls.GRAY}│{cls.RESET}  {cls.PILL_YELLOW} Rule: {rule or 'one-time'} {cls.RESET}  {cls.GRAY}│{cls.RESET}  {time_badge}  {cls.GRAY}│{cls.RESET}  {exit_badge}")
            print(divider)
            print(f"{border_color}│{cls.RESET}  {cls.PILL_CYAN} ⚡ ACTION {cls.RESET}  {cls.BRIGHT_WHITE}$ {command}{cls.RESET}")
            if result.get("browser_launch"):
                bl = result["browser_launch"]
                print(f"{border_color}│{cls.RESET}  {cls.GRAY}🌐 Browser Target:{cls.RESET} {cls.CYAN}{bl.get('url')}{cls.RESET} ({bl.get('browser')})")
            print(f"{border_color}└───◄ {end_badge} {cls.BOLD}{cls.BRIGHT_WHITE}ITERATION COMPLETE{cls.RESET}  {time_badge} {border_color}{bot_bar}{cls.RESET}")
            print()

    @classmethod
    def log_notification(cls, title: str, msg: str):
        with cls._lock:
            ts = cls.timestamp()
            print(f"{cls.GRAY}[{ts}]{cls.RESET} 🔔 {cls.BG_MAGENTA} DESKTOP NOTIFICATION {cls.RESET} → {cls.BOLD}{cls.WHITE}{title}{cls.RESET}: {cls.DIM}{msg}{cls.RESET}")

    @classmethod
    def log_info(cls, msg: str):
        with cls._lock:
            ts = cls.timestamp()
            print(f"{cls.GRAY}[{ts}]{cls.RESET} ℹ️  {cls.PILL_CYAN} INFO {cls.RESET} {cls.CYAN}{msg}{cls.RESET}")

    @classmethod
    def log_warn(cls, msg: str):
        with cls._lock:
            ts = cls.timestamp()
            print(f"{cls.GRAY}[{ts}]{cls.RESET} ⚠️  {cls.PILL_YELLOW} WARN {cls.RESET} {cls.BRIGHT_YELLOW}{msg}{cls.RESET}")

    @classmethod
    def log_error(cls, msg: str):
        with cls._lock:
            ts = cls.timestamp()
            print(f"{cls.GRAY}[{ts}]{cls.RESET} ❌ {cls.PILL_RED} ERROR {cls.RESET} {cls.BRIGHT_RED}{msg}{cls.RESET}")


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
    prompt: Optional[str] = None


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
        "cpu_percent": 0.0,
        "memory": {
            "total_mb": 0.0,
            "available_mb": 0.0,
            "used_mb": 0.0,
            "percent": 0.0,
        },
        "disk": {
            "total_gb": 0.0,
            "used_gb": 0.0,
            "free_gb": 0.0,
            "percent": 0.0,
        },
        "boot_time": time.time(),
        "uptime_seconds": 0,
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
        # Native Linux fallback if /proc is available
        if platform.system() == "Linux" and os.path.exists("/proc/meminfo"):
            try:
                mem_data = {}
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            k = parts[0].strip()
                            v = parts[1].strip().split()[0]
                            if v.isdigit():
                                mem_data[k] = int(v)
                total_kb = mem_data.get("MemTotal", 0)
                avail_kb = mem_data.get("MemAvailable", mem_data.get("MemFree", 0))
                used_kb = max(0, total_kb - avail_kb)
                pct = round((used_kb / total_kb * 100.0), 1) if total_kb > 0 else 0.0
                metrics["memory"] = {
                    "total_mb": round(total_kb / 1024.0, 1),
                    "available_mb": round(avail_kb / 1024.0, 1),
                    "used_mb": round(used_kb / 1024.0, 1),
                    "percent": pct,
                }
            except Exception:
                pass

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
    prompt: Optional[str] = None,
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
                verification_passed=False, safety_decision="cancelled", prompt=prompt,
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
            prompt=prompt,
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
                last.output = fallback.output
                last.stdout = fallback.stdout
                last.stderr = fallback.stderr
                last.exit_code = fallback.exit_code
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
    prompt: Optional[str] = None,
) -> dict:
    """Execute a validated sequence with explicit step success semantics."""
    if not isinstance(steps, list) or not steps:
        return {"success": False, "status": "invalid_plan", "steps_executed": 0, "total_steps": 0,
                "step_results": [], "output": "Multi-step plan is empty or invalid.", "prompt": prompt}

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
                cancel_event=cancel_event, prompt=prompt,
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
                rollback = completed.get("rollback_command") or completed.get("compensation_command") or completed.get("rollback")
                if not rollback: continue
                try:
                    rb = execute_command(rollback, working_directory=working_directory, approved=approved, prompt=prompt)
                    rollback_results.append({"step_id": completed.get("step_id", completed.get("step")), "result": asdict(rb)})
                except Exception as exc:
                    rollback_results.append({"step_id": completed.get("step_id", completed.get("step")), "error": str(exc)})
        if rollback_results:
            combined_output.append("--- [Rollback] ---\n" + json.dumps(rollback_results, default=str))
            res_dict["rollback_results"] = rollback_results
        if not continue_on_error: break

    # A skipped/invalid step can never make the whole pipeline successful.
    success = bool(steps) and total_success and len(step_results) == len(steps) and all(r.get("success") is True for r in step_results)
    failed_step_id = None
    if not success and step_results:
        for r in step_results:
            if not r.get("success"):
                failed_step_id = r.get("step_id")
                break
    return {
        "success": success,
        "status": "completed" if success else "failed",
        "failed_step": failed_step_id,
        "steps_executed": len(step_results), "total_steps": len(steps),
        "step_results": step_results, "output": "\n\n".join(combined_output),
        "failure_policy": {"max_attempts": max_attempts, "continue_on_error": continue_on_error, "rollback_enabled": True},
        "prompt": prompt,
    }


def execute_conditional_workflow(
    condition_script: str,
    on_success: Optional[str],
    on_failure: Optional[str] = None,
    working_directory: Optional[str] = None,
    approved: bool = False,
    condition_retries: int = 1,
    cancel_event: Optional[threading.Event] = None,
    prompt: Optional[str] = None,
) -> dict:
    """Evaluate a strict predicate and execute at most one branch.

    Exit code 0 = true, 1 = false. Any other non-zero code means the predicate
    itself failed and no branch is executed. This prevents an evaluator error
    from being silently interpreted as a normal false condition.
    """
    if not condition_script or not condition_script.strip():
        return {"success": False, "status": "invalid_condition", "condition_met": False,
                "branch_executed": "none", "condition_output": "Condition script is empty.", "prompt": prompt}

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
                prompt=prompt,
            )
        except Exception as exc:
            return {"success": False, "status": "condition_exception", "condition_met": False,
                    "branch_executed": "none", "condition_output": str(exc), "prompt": prompt}
        if cond_result.exit_code in (0, 1) or cond_result.status in {"syntax_error", "policy_blocked", "approval_required", "cancelled", "timeout"}:
            break

    if cond_result is None:
        return {"success": False, "status": "condition_no_result", "condition_met": False, "branch_executed": "none", "prompt": prompt}

    if cond_result.status in {"syntax_error", "policy_blocked", "approval_required", "cancelled", "timeout"}:
        return {"success": False, "status": "condition_evaluation_failed", "condition_met": False,
                "branch_executed": "none", "condition_output": cond_result.output,
                "condition_result": asdict(cond_result), "prompt": prompt}

    if cond_result.exit_code not in (0, 1):
        return {"success": False, "status": "condition_evaluation_failed", "condition_met": False,
                "branch_executed": "none", "condition_output": cond_result.output,
                "condition_result": asdict(cond_result),
                "error": f"Condition exited with unsupported code {cond_result.exit_code}; expected 0 or 1.", "prompt": prompt}

    condition_met = cond_result.exit_code == 0
    branch_script = on_success if condition_met else on_failure
    if not branch_script:
        return {"success": True, "status": "condition_true_no_branch" if condition_met else "condition_false_no_branch",
                "condition_met": condition_met, "branch_executed": "none",
                "condition_output": cond_result.output, "condition_result": asdict(cond_result), "output": cond_result.output, "prompt": prompt}

    try:
        branch_result = execute_with_recovery(branch_script, working_directory=working_directory, approved=approved, max_attempts=2, cancel_event=cancel_event, prompt=prompt)
    except Exception as exc:
        return {"success": False, "status": "branch_exception", "condition_met": condition_met,
                "branch_executed": "on_success" if condition_met else "on_failure",
                "condition_output": cond_result.output, "condition_result": asdict(cond_result), "error": str(exc), "prompt": prompt}
    return {
        "success": branch_result.success,
        "status": "completed" if branch_result.success else "failed",
        "condition_met": condition_met,
        "branch_executed": "on_success" if condition_met else "on_failure",
        "condition_output": cond_result.output,
        "condition_result": asdict(cond_result),
        "branch_result": asdict(branch_result),
        "output": f"Condition ({'PASS' if condition_met else 'FALSE'}):\n{cond_result.output}\n\nBranch Output:\n{branch_result.output}",
        "prompt": prompt,
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
    prompt: Optional[str] = None,
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
    is_strict_daemon = False

    TRANSIENT_CLI_COMMANDS = {
        "top", "free", "df", "ps", "uname", "uptime", "ls", "grep", "awk", "sed", "cat", 
        "echo", "head", "tail", "wc", "find", "curl", "wget", "bash", "sh", "zsh", "python", 
        "python3", "node", "git", "rustc", "cargo", "vmstat", "vm_stat", "ifconfig", "ip", 
        "ss", "netstat", "touch", "rm", "mkdir", "cp", "mv", "chmod", "chown", "tar", "zip", 
        "unzip", "which", "where", "where.exe", "whoami", "hostname", "date", "ping", "traceroute",
        "docker", "kubectl", "systemctl", "journalctl", "dmesg", "lsof", "env", "printenv"
    }

    if expected_process:
        proc_clean = expected_process.strip().lower()
        if " " not in proc_clean and proc_clean not in TRANSIENT_CLI_COMMANDS:
            is_strict_daemon = True

        detected = False
        for _ in range(10):
            if verify_process(expected_process):
                detected = True
                break
            time.sleep(0.15)
        verification["process_detected"] = detected
        verification["process_verification"] = "observed" if detected else ("not_observed" if is_strict_daemon else "transient_cli_or_description")

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
    if expected_process and is_strict_daemon and not verification.get("process_detected", False):
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
        prompt=prompt,
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
        ConsoleLogger.log_request("OPTIONS", self.path, 200, "CORS Preflight")
        self._json_response(
            {
                "status": "ok"
            }
        )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    def do_GET(self):
        start_t = time.monotonic()
        path = urllib.parse.urlparse(self.path).path
        try:
            if path in {
                "/",
                "/health",
            }:
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("GET", self.path, 200, "Health Check", dur)
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

            if path == "/scheduler/status":
                state=_scheduler_state_snapshot()
                state.update({
                    "enabled": SCHEDULER_ENABLED,
                    "interval_seconds": SCHEDULER_INTERVAL,
                    "backend_url": BACKEND_URL,
                    "approval_ui_base": APPROVAL_UI_BASE,
                    "approval_backend_base": APPROVAL_BACKEND_BASE,
                    "gui_available": _gui_available(),
                })
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("GET", self.path, 200, "Scheduler Status", dur)
                self._json_response(state)
                return

            if path == "/system":
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("GET", self.path, 200, "System Info", dur)
                self._json_response(get_system_info())
                return

            if path == "/system/metrics":
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("GET", self.path, 200, "System Metrics", dur)
                self._json_response(get_realtime_metrics())
                return

            if path == "/capabilities":
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("GET", self.path, 200, "Capabilities (19 Supported)", dur)
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

            if path == "/browsers":
                browsers = get_installed_browsers()
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("GET", self.path, 200, f"Installed Browsers ({len(browsers)} found)", dur)
                self._json_response({"browsers": browsers})
                return

            if path == "/processes":
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("GET", self.path, 200, "Process List", dur)
                self._json_response({"processes": list_processes()})
                return

            if path == "/executions":
                history = [asdict(result) for result in REGISTRY.all_history()]
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("GET", self.path, 200, f"History ({len(history)} executions)", dur)
                self._json_response({"executions": history})
                return

            if path.startswith("/executions/"):
                execution_id = path.split("/executions/", 1)[1].split("/", 1)[0]
                task = REGISTRY.get(execution_id)
                dur = int((time.monotonic() - start_t) * 1000)
                if not task:
                    ConsoleLogger.log_request("GET", self.path, 404, f"Execution {execution_id[:8]} Not Found", dur)
                    self._json_response({"error": "Execution not found."}, 404)
                    return
                ConsoleLogger.log_request("GET", self.path, 200, f"Execution {execution_id[:8]}", dur)
                self._json_response({
                    "execution_id": execution_id,
                    "finished": task.finished,
                    "cancelled": task.cancelled,
                    "result": asdict(task.result) if task.result else None,
                    "output_lines": task.output_lines[-500:],
                })
                return

            ConsoleLogger.log_request("GET", self.path, 404, "Not Found")
            self._json_response({"error": "Not found."}, 404)

        except Exception as exc:
            ConsoleLogger.log_error(f"GET {self.path} Exception: {exc}")
            self._json_response({"error": str(exc)}, 500)

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    def do_POST(self):
        start_t = time.monotonic()
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/execute":
                data = self._read_json()
                command = data.get("script") or data.get("command")
                if not command:
                    ConsoleLogger.log_request("POST", "/execute", 400, "Missing script/command")
                    self._json_response({"status": "error", "error": "Missing script/command."}, 400)
                    return

                risk = classify_command(command)
                async_mode = bool(data.get("async", False))
                if async_mode:
                    execution_id = start_async_execution(data)
                    dur = int((time.monotonic() - start_t) * 1000)
                    ConsoleLogger.log_request("POST", "/execute", 202, f"Async execution accepted ({execution_id[:8]})", dur)
                    self._json_response({"status": "accepted", "execution_id": execution_id, "risk": risk}, 202)
                    return

                cached = _idempotency_get(data.get("idempotency_key"))
                if cached:
                    response = asdict(cached)
                    response["deduplicated"] = True
                    dur = int((time.monotonic() - start_t) * 1000)
                    ConsoleLogger.log_request("POST", "/execute", 200, "Deduplicated cached execution", dur)
                    ConsoleLogger.log_execution(cached)
                    self._json_response(response, 200)
                    return

                prompt = data.get("prompt") or data.get("natural_language_prompt") or data.get("request_prompt")
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
                    prompt=prompt,
                )
                response = asdict(result)
                response["validated"] = result.success
                response["status"] = result.status
                ConsoleLogger.log_execution(result)
                self._json_response(response, 200)
                return

            if path == "/execute/multi-step":
                data = self._read_json()
                steps = data.get("steps") or []
                if not isinstance(steps, list) or not steps:
                    ConsoleLogger.log_request("POST", "/execute/multi-step", 400, "Steps list required")
                    self._json_response({"status": "error", "error": "steps list required."}, 400)
                    return
                prompt = data.get("prompt") or data.get("natural_language_prompt") or data.get("request_prompt")
                res = execute_multi_step_workflow(
                    steps=steps,
                    working_directory=data.get("working_directory"),
                    continue_on_error=bool(data.get("continue_on_error", False)),
                    approved=bool(data.get("approved", False)),
                    prompt=prompt,
                )
                ConsoleLogger.log_multistep(res)
                self._json_response(res, 200)
                return

            if path == "/execute/conditional":
                data = self._read_json()
                cond_script = data.get("condition_script")
                on_succ = data.get("on_success")
                on_fail = data.get("on_failure")
                if not cond_script or not on_succ:
                    ConsoleLogger.log_request("POST", "/execute/conditional", 400, "Missing condition/on_success")
                    self._json_response({"status": "error", "error": "condition_script and on_success are required."}, 400)
                    return
                prompt = data.get("prompt") or data.get("natural_language_prompt") or data.get("request_prompt")
                res = execute_conditional_workflow(
                    condition_script=cond_script,
                    on_success=on_succ,
                    on_failure=on_fail,
                    working_directory=data.get("working_directory"),
                    approved=bool(data.get("approved", False)),
                    prompt=prompt,
                )
                ConsoleLogger.log_conditional(res)
                self._json_response(res, 200)
                return

            if path == "/notify":
                data = self._read_json()
                title = str(data.get("title") or "OmniShell Notification")
                msg = str(data.get("message") or "")
                sent = send_desktop_notification(title, msg)
                ConsoleLogger.log_notification(title, msg)
                self._json_response({"status": "sent" if sent else "unsupported", "title": title, "message": msg}, 200)
                return

            if path == "/cancel":
                data = self._read_json()
                execution_id = data.get("execution_id")
                if not execution_id:
                    ConsoleLogger.log_request("POST", "/cancel", 400, "Missing execution_id")
                    self._json_response({"error": "execution_id is required."}, 400)
                    return
                cancelled = REGISTRY.cancel(execution_id)
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("POST", "/cancel", 200, f"Cancelled ID: {execution_id[:12]} (status: {cancelled})", dur)
                self._json_response({"execution_id": execution_id, "cancelled": cancelled})
                return

            if path == "/classify":
                data = self._read_json()
                command = data.get("script") or data.get("command")
                if not command:
                    self._json_response({"error": "Missing script/command."}, 400)
                    return
                risk_info = classify_command(command)
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("POST", "/classify", 200, f"Risk: {risk_info.get('level', 'safe').upper()}", dur)
                self._json_response(risk_info)
                return

            if path == "/dry-run":
                data = self._read_json()
                command = data.get("script") or data.get("command")
                if not command:
                    self._json_response({"error": "Missing script/command."}, 400)
                    return
                risk_info = classify_command(command)
                dur = int((time.monotonic() - start_t) * 1000)
                ConsoleLogger.log_request("POST", "/dry-run", 200, f"Dry-run simulation", dur)
                self._json_response({
                    "command": command,
                    "risk": risk_info,
                    "working_directory": normalize_working_directory(data.get("working_directory")),
                    "will_execute": False,
                })
                return

            ConsoleLogger.log_request("POST", self.path, 404, "Not Found")
            self._json_response(
                {
                    "error": "Not found."
                },
                404,
            )

        except json.JSONDecodeError as exc:
            ConsoleLogger.log_error(f"POST {self.path} JSON error: {exc}")
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
            ConsoleLogger.log_error(f"POST {self.path} Value error: {exc}")
            self._json_response(
                {
                    "status": "error",
                    "error": str(exc),
                },
                400,
            )

        except Exception as exc:
            ConsoleLogger.log_error(f"POST {self.path} Internal exception: {exc}")
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
        # Suppress raw Apache-style HTTP logs in favor of structured ConsoleLogger
        pass


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
            ConsoleLogger.log_scheduled_run(task_id, bool(task.get("is_recurring")), task.get("recurrence_rule") or "", f"Open Browser: {target_url}", result)
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
                    ConsoleLogger.log_scheduled_run(task_id, bool(task.get("is_recurring")), task.get("recurrence_rule") or "", f"Multi-Step Workflow ({len(exec_steps)} steps)", res)
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
                ConsoleLogger.log_scheduled_run(task_id, bool(task.get("is_recurring")), task.get("recurrence_rule") or "", f"Conditional: {str(cond_logic.get('condition_script'))[:30]}", res)
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
        ConsoleLogger.log_scheduled_run(task_id, bool(task.get("is_recurring")), task.get("recurrence_rule") or "", command, payload)
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
        ConsoleLogger.log_error(f"Scheduled task #{task_id} execution failed: {exc}")
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
                ConsoleLogger.log_warn(f"Task #{task_id} entered approval state without a token (backend will expire)")
                return
            prompt_preview = str(task.get("original_prompt") or "Action authorization required")[:120]
            try:
                send_desktop_notification("OmniShell Scheduled Approval", f"Task #{task_id}: {prompt_preview}")
            except Exception as exc:
                ConsoleLogger.log_warn(f"Approval desktop notification failed for #{task_id}: {exc}")
            try:
                approval_result = open_approval_document(task_id, token)
                _scheduler_state_update(last_approval_at=time.time(), last_approval_result=approval_result, last_task_id=task_id, last_task_status="awaiting_approval")
                ConsoleLogger.log_approval_prompt(task_id, prompt_preview, approval_result)
            except Exception as exc:
                _scheduler_state_update(last_approval_at=time.time(), last_approval_result={"opened":False,"error":str(exc)}, last_task_id=task_id, last_task_status="awaiting_approval", last_error=str(exc))
                ConsoleLogger.log_error(f"Approval document launch failed for task #{task_id}: {exc}")
                try:
                    manual_url = _approval_urls(task_id, token)[-1]
                    ConsoleLogger.log_warn(f"Manual approval URL: {manual_url}")
                except Exception:
                    pass
            return

        if status == "approved":
            try:
                execute_scheduled_workflow(task)
            except Exception as exc:
                ConsoleLogger.log_error(f"Approved scheduled execution failed for task #{task_id}: {exc}")
            return

        ConsoleLogger.log_warn(f"Ignoring unexpected claimed task #{task_id} state: {status!r}")
    finally:
        with _scheduler_active_lock:
            _scheduler_active_ids.discard(task_id)


def _task_worker(task):
    try: handle_claimed_task(task)
    finally: _scheduler_workers.release()


def scheduler_loop():
    ConsoleLogger.log_info(f"Scheduler worker thread active (interval={SCHEDULER_INTERVAL}s, pool={SCHEDULER_MAX_WORKERS}, backend={BACKEND_URL})")
    consecutive_errors = 0
    while not _scheduler_stop.is_set():
        try:
            poll_at = time.time()
            status, data = _http_json("GET", f"{BACKEND_URL}/api/scheduled-tasks/internal/poll")
            _scheduler_state_update(last_poll_at=poll_at, last_poll_status=status, poll_count=_scheduler_state_snapshot()["poll_count"] + 1, last_error=None)
            if status == 200:
                consecutive_errors = 0
                task = data.get("task")
                if task:
                    _scheduler_state_update(last_task_id=task.get("id"), last_task_status=task.get("status"))
                if task and _scheduler_workers.acquire(blocking=False):
                    threading.Thread(target=_task_worker, args=(task,), daemon=True, name=f"scheduled-task-{task.get('id')}").start()
            else:
                consecutive_errors += 1
        except Exception as exc:
            consecutive_errors += 1
            _scheduler_state_update(last_error=str(exc))
            if consecutive_errors in {1, 5, 20} or consecutive_errors % 50 == 0:
                ConsoleLogger.log_warn(f"Backend offline / unreachable (attempt {consecutive_errors}): {exc}")
        _scheduler_stop.wait(min(max(SCHEDULER_INTERVAL, 1) * (2 if consecutive_errors >= 5 else 1), 15))


def stop_scheduler():
    _scheduler_stop.set()


def main():
    shell_name, shell_path = detect_shell()
    info = {
        "os": platform.system(),
        "arch": platform.machine(),
        "shell": shell_name,
        "shell_path": shell_path,
        "host": HOST,
        "port": PORT,
        "backend": BACKEND_URL,
        "terminal": find_terminal() if platform.system().lower() != "windows" else "native-cmd",
    }
    ConsoleLogger.banner(info)

    if SCHEDULER_ENABLED:
        threading.Thread(target=scheduler_loop, daemon=True, name="omnishell-scheduler").start()
    server = ThreadedHTTPServer((HOST, PORT), ExecutionHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        ConsoleLogger.log_warn("Shutdown requested by operator (SIGINT / KeyboardInterrupt).")
    finally:
        stop_scheduler()
        for task in REGISTRY.active():
            if task.process:
                try: terminate_process_tree(task.process, force=True)
                except Exception: pass
        server.server_close()
        ConsoleLogger.log_info("Host Execution Agent server stopped cleanly.")


if __name__ == "__main__":
    main()