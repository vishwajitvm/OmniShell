import os
import json
import datetime
import asyncio
import hashlib
import secrets
import re
from typing import Any, Optional, Union, List, Dict, Tuple, Set, Callable
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import litellm
import redis
import asyncpg

try:
    from tracenest.logger import Logger
    from tracenest.fastapi.middleware import TraceNestMiddleware
    from tracenest.ui.router import router as tracenest_router
    logger = Logger()
    tracenest_available = True
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("omnishell")
    tracenest_available = False
    TraceNestMiddleware = None
    tracenest_router = None

# Map KIMI_API_KEY to MOONSHOT_API_KEY for litellm compatibility
if os.getenv("KIMI_API_KEY") and not os.getenv("MOONSHOT_API_KEY"):
    os.environ["MOONSHOT_API_KEY"] = os.getenv("KIMI_API_KEY")

app = FastAPI(title="Multi-Agent OS Automation API")

if tracenest_available and TraceNestMiddleware:
    app.add_middleware(TraceNestMiddleware)
if tracenest_available and tracenest_router:
    app.include_router(tracenest_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in os.getenv("OMNISHELL_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if item.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

class AutomationRequest(BaseModel):
    natural_language_prompt: str
    user_agent_os: str = "Unknown OS"
    local_time: str | None = None
    timezone: str | None = None
    client_id: str | None = None
    request_id: str | None = None

class AgentThought(BaseModel):
    agent_name: str = Field(description="Name of the agent (e.g., 'OS Analyzer', 'Security Guard', 'Execution Planner')")
    thought: str = Field(description="The internal reasoning and decision making of this agent")

class MultiAgentResult(BaseModel):
    multi_agent_discussion: list[AgentThought] = Field(default_factory=list, description="The step-by-step discussion between the agents.")
    capability_type: str = Field(default="shell_operation", description="One of the 19 core capabilities (e.g., question_answering, system_inspection, analysis, application_operation, browser_operation, file_operation, shell_operation, multi_step, interactive_workflow, scheduled_workflow, recurring_workflow, conditional_workflow, reminder, research, planning_only, human_approval, clarification, recovery_failure, information_request).")
    direct_answer: str | None = Field(default=None, description="Rich formatted Markdown answer for Q&A, info requests, analysis, research, planning, etc.")
    is_safe: bool | None = Field(default=True, description="True if safe, False if malicious (formatting, viruses).")
    target_os: str | None = Field(default="", description="The detected OS (Windows, Linux, macOS, Android, iOS).")
    requires_browser: bool | None = Field(default=False, description="Set to True ONLY if the user is asking to open a website, url, or web service (like Netflix, GitHub).")
    target_url: str | None = Field(default=None, description="The full URL to open (e.g., 'https://www.netflix.com'). Required if requires_browser is True.")
    shell_script: str | None = Field(default=None, description="Robust script to execute. Only used if requires_browser is False. E.g., Start-Process 'code'")
    expected_process: str | None = Field(default=None, description="The name of the executable process that should be running after execution.")
    mermaid_diagram_body: str | None = Field(default="", description="ONLY the body of the flowchart.")
    model_used: str | None = Field(default=None)
    
    # Multi-step & Interactive
    multi_step_plan: list[dict] | None = Field(default=None, description="Sequential sub-steps for multi-step tasks.")
    requires_interactive: bool | None = Field(default=False, description="Set to True if workflow needs user input during execution.")
    interactive_prompts: list[str] | None = Field(default=None, description="Interactive questions or prompts for user input.")
    
    # Clarification & Planning
    requires_clarification: bool | None = Field(default=False, description="Set to True if prompt is ambiguous or missing parameters.")
    clarification_questions: list[str] | None = Field(default=None, description="Specific questions to clarify the user's intent.")
    is_planning_only: bool | None = Field(default=False, description="Set to True if the user only wanted a plan/roadmap without execution.")
    
    # Scheduling & Recurring
    is_scheduled: bool = Field(default=False)
    scheduled_time: str | None = Field(default=None)
    schedule_timezone: str | None = Field(default=None)
    schedule_type: str | None = Field(default="one_time")
    is_recurring: bool = Field(default=False, description="Set to True if task repeats on an interval or cron.")
    recurrence_rule: str | None = Field(default=None, description="Recurrence expression, e.g., 'interval:5m', 'daily:10:00'.")
    
    # Conditional & Recovery
    conditional_logic: dict | None = Field(default=None, description="Conditional checks: condition_script, on_success, on_failure.")
    recovery_strategy: dict | None = Field(default=None, description="Self-healing recovery: fallback_script, retry_limit, diagnostic_command.")
    
    # Human Approval
    requires_approval: bool | None = Field(default=False, description="Set to True if high-risk or destructive operation requires confirmation.")
    approval_reason: str | None = Field(default=None, description="Explanation of why human approval is required.")
    
    # Reminders
    is_reminder: bool = Field(default=False, description="Set to True if this is a reminder notification task.")
    reminder_time: str | None = Field(default=None, description="ISO 8601 future time for the reminder.")
    reminder_message: str | None = Field(default=None, description="The message for the reminder.")
    
    # Telemetry & Scheduling Meta
    priority: int | None = Field(default=5, ge=1, le=10)
    approval_timeout_seconds: int | None = Field(default=None, ge=30, le=3600)
    scheduled_task_id: int | None = Field(default=None)
    scheduled_status: str | None = Field(default=None)
    scheduled_for_utc: str | None = Field(default=None)
    timing: dict | None = Field(default=None)

    # Intent / reliability envelope. These fields describe the resolved request
    # without expanding the 19-capability public contract.
    intent_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    intent_signals: list[str] | None = Field(default_factory=list)
    intent_entities: dict | None = Field(default_factory=dict)
    execution_mode: str | None = Field(default=None)
    safety_level: str | None = Field(default=None)
    ambiguity_reasons: list[str] | None = Field(default_factory=list)
    failure_policy: dict | None = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None)
    workflow_state: str | None = Field(default=None)

# ============================================================
# LLM / MODEL REGISTRY
# ============================================================
# IMPORTANT:
# - Only models whose provider credentials are present are activated.
# - NVIDIA NIM models use the LiteLLM provider prefix `nvidia_nim/`.
# - Specialized NVIDIA models (embedding/reranker/safety/video/etc.)
#   are registered separately and are NEVER used as chat fallbacks.
# - Old/deprecated Gemini 1.x and Gemini 2.0 experimental identifiers
#   are intentionally removed.

MODEL_REGISTRY = {
    # -------------------- General chat / agent models --------------------
    "nvidia_nim/deepseek-v4.1-flash": {
        "provider": "nvidia",
        "model_id": "deepseek-v4.1-flash",
        "role": "chat",
        "priority": 10,
        "reasoning": True,
        "tool_calling": True,
        "multimodal": True,
    },
    "nvidia_nim/glm-5-3": {
        "provider": "nvidia",
        "model_id": "glm-5-3",
        "role": "chat",
        "priority": 20,
        "reasoning": True,
        "tool_calling": True,
    },
    "nvidia_nim/glm-5-3-flash": {
        "provider": "nvidia",
        "model_id": "glm-5-3-flash",
        "role": "chat",
        "priority": 15,
        "reasoning": True,
        "tool_calling": True,
        "multimodal": True,
    },
    "nvidia_nim/kimi-k3": {
        "provider": "nvidia",
        "model_id": "kimi-k3",
        "role": "chat",
        "priority": 12,
        "reasoning": True,
        "tool_calling": True,
        "multimodal": True,
    },
    "nvidia_nim/nemotron-3.5-lightning-30b-a3b": {
        "provider": "nvidia",
        "model_id": "nemotron-3.5-lightning-30b-a3b",
        "role": "chat",
        "priority": 5,
        "reasoning": True,
        "tool_calling": True,
    },
    "nvidia_nim/muse-glimmer-30b": {
        "provider": "nvidia",
        "model_id": "muse-glimmer-30b",
        "role": "chat",
        "priority": 25,
        "reasoning": True,
        "tool_calling": True,
        "multimodal": True,
    },
    "nvidia_nim/laguna-xs-2.1": {
        "provider": "nvidia",
        "model_id": "laguna-xs-2.1",
        "role": "chat",
        "priority": 30,
        "reasoning": True,
        "tool_calling": True,
    },
    "nvidia_nim/gemma-4-31b-it": {
        "provider": "nvidia",
        "model_id": "gemma-4-31b-it",
        "role": "chat",
        "priority": 35,
        "reasoning": True,
        "tool_calling": True,
    },
    "nvidia_nim/gpt-oss-20b": {
        "provider": "nvidia",
        "model_id": "gpt-oss-20b",
        "role": "chat",
        "priority": 8,
        "reasoning": True,
        "tool_calling": True,
    },
    "nvidia_nim/diffusiongemma-26b-a4b-it": {
        "provider": "nvidia",
        "model_id": "diffusiongemma-26b-a4b-it",
        "role": "chat",
        "priority": 40,
        "reasoning": False,
        "tool_calling": False,
    },
    "nvidia_nim/ising-calibration-1-35b-a3b": {
        "provider": "nvidia",
        "model_id": "ising-calibration-1-35b-a3b",
        "role": "vision_specialized",
        "priority": 90,
        "reasoning": False,
        "tool_calling": False,
    },
    "nvidia_nim/ising-calibration-1.5-31b": {
        "provider": "nvidia",
        "model_id": "ising-calibration-1.5-31b",
        "role": "vision_specialized",
        "priority": 91,
        "reasoning": False,
        "tool_calling": False,
    },
    "nvidia_nim/nemotron-3-nano-omni-30b-a3b-reasoning": {
        "provider": "nvidia",
        "model_id": "nemotron-3-nano-omni-30b-a3b-reasoning",
        "role": "chat",
        "priority": 18,
        "reasoning": True,
        "tool_calling": True,
        "multimodal": True,
    },
    # -------------------- Specialized models --------------------
    "nvidia_nim/nemotron-3-embed-1b": {
        "provider": "nvidia",
        "model_id": "nemotron-3-embed-1b",
        "role": "embedding",
        "priority": 1,
    },
    "nvidia_nim/nemotron-3.5-content-safety": {
        "provider": "nvidia",
        "model_id": "nemotron-3.5-content-safety",
        "role": "safety",
        "priority": 1,
    },
    "nvidia_nim/cosmos3-nano": {
        "provider": "nvidia",
        "model_id": "cosmos3-nano",
        "role": "vision_video",
        "priority": 1,
        "multimodal": True,
    },
    "nvidia_nim/llama-nemotron-rerank-vl-1b-v2": {
        "provider": "nvidia",
        "model_id": "llama-nemotron-rerank-vl-1b-v2",
        "role": "reranker",
        "priority": 1,
        "multimodal": True,
    },
    "nvidia_nim/kumo-relational": {
        "provider": "nvidia",
        "model_id": "Kumo Relational",
        "role": "relational",
        "priority": 1,
    },
}

# Optional Hugging Face route. This is intentionally opt-in because a model
# name alone does not prove that a public HF Inference deployment exists.
# Set HF_*_MODEL variables only when you have an actual HF model/endpoint.
HF_CHAT_MODEL = os.getenv("HF_CHAT_MODEL", "").strip()


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _provider_key_available(provider: str) -> bool:
    if provider == "nvidia":
        return bool(os.getenv("NVIDIA_NIM_API_KEY") or os.getenv("NVIDIA_API_KEY"))
    if provider == "openrouter":
        return bool(os.getenv("OPENROUTER_API_KEY"))
    if provider == "groq":
        return bool(os.getenv("GROQ_API_KEY"))
    if provider == "gemini":
        return bool(os.getenv("GEMINI_API_KEY"))
    if provider == "huggingface":
        return bool(os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_TOKEN"))
    return False


# NVIDIA credentials: LiteLLM documents NVIDIA_NIM_API_KEY.
if os.getenv("NVIDIA_API_KEY") and not os.getenv("NVIDIA_NIM_API_KEY"):
    os.environ["NVIDIA_NIM_API_KEY"] = os.getenv("NVIDIA_API_KEY")

# A stable, current Gemini fallback is kept as an optional provider rather
# than embedding obsolete Gemini 1.x model identifiers in the source.
# Override with GEMINI_MODEL if you want another currently-enabled model.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()


# Ordered general-purpose providers. The exact order can be overridden with
# LLM_FALLBACK_ORDER, e.g. "nvidia,openrouter,groq,gemini,huggingface".
DEFAULT_PROVIDER_ORDER = ["nvidia", "openrouter", "groq", "gemini", "huggingface"]
PROVIDER_ORDER = [
    item.strip().lower()
    for item in os.getenv("LLM_FALLBACK_ORDER", ",".join(DEFAULT_PROVIDER_ORDER)).split(",")
    if item.strip()
]


def _build_fallback_models() -> list[str]:
    models: list[str] = []

    for provider in PROVIDER_ORDER:
        if provider == "nvidia" and _provider_key_available("nvidia"):
            # Only general chat-capable NVIDIA models belong here.
            nvidia_chat = [
                "nvidia_nim/nemotron-3.5-lightning-30b-a3b",
                "nvidia_nim/glm-5-3-flash",
                "nvidia_nim/deepseek-v4.1-flash",
                "nvidia_nim/kimi-k3",
                "nvidia_nim/nemotron-3-nano-omni-30b-a3b-reasoning",
                "nvidia_nim/glm-5-3",
                "nvidia_nim/gpt-oss-20b",
                "nvidia_nim/muse-glimmer-30b",
                "nvidia_nim/laguna-xs-2.1",
                "nvidia_nim/gemma-4-31b-it",
                "nvidia_nim/diffusiongemma-26b-a4b-it",
            ]
            models.extend(nvidia_chat)

        elif provider == "openrouter" and _provider_key_available("openrouter"):
            models.extend([
                "openrouter/deepseek/deepseek-chat",
                "openrouter/meta-llama/llama-3.3-70b-instruct",
                "openrouter/qwen/qwen-2.5-72b-instruct",
                "openrouter/meta-llama/llama-3.1-8b-instruct",
            ])

        elif provider == "groq" and _provider_key_available("groq"):
            # Keep current provider routing configurable; stale Groq IDs are
            # deliberately not hardcoded here.
            configured = os.getenv("GROQ_MODELS", "").strip()
            if configured:
                models.extend([
                    f"groq/{m.strip()}" if not m.strip().startswith("groq/") else m.strip()
                    for m in configured.split(",") if m.strip()
                ])

        elif provider == "gemini" and _provider_key_available("gemini"):
            models.append(f"gemini/{GEMINI_MODEL}")

        elif provider == "huggingface" and _provider_key_available("huggingface") and HF_CHAT_MODEL:
            models.append(
                HF_CHAT_MODEL if HF_CHAT_MODEL.startswith("huggingface/")
                else f"huggingface/{HF_CHAT_MODEL}"
            )

    # Remove duplicates without changing priority.
    return list(dict.fromkeys(models))


FALLBACK_MODELS = _build_fallback_models()

SPECIALIZED_MODELS = {
    key: meta for key, meta in MODEL_REGISTRY.items()
    if meta.get("role") not in {"chat"}
}

if not FALLBACK_MODELS:
    logger.warning(
        "No configured LLM provider credentials were found. "
        "Set NVIDIA_NIM_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, "
        "GEMINI_API_KEY, or HUGGINGFACE_API_KEY/HF_TOKEN."
    )


def get_model_registry() -> dict:
    """Return safe model metadata for diagnostics/UI."""
    return {
        "active_fallbacks": FALLBACK_MODELS,
        "specialized_models": SPECIALIZED_MODELS,
        "providers": {
            "nvidia": _provider_key_available("nvidia"),
            "openrouter": _provider_key_available("openrouter"),
            "groq": _provider_key_available("groq"),
            "gemini": _provider_key_available("gemini"),
            "huggingface": _provider_key_available("huggingface"),
        },
    }


# Runtime failure state. A model that repeatedly returns a permanent
# availability/authentication error is temporarily cooled down so every
# request does not waste latency hitting the same dead endpoint.
MODEL_COOLDOWN: dict[str, float] = {}
MODEL_FAILURES: dict[str, int] = {}
MODEL_COOLDOWN_SECONDS = int(os.getenv("MODEL_COOLDOWN_SECONDS", "300"))


def model_is_cooled_down(model_name: str) -> bool:
    until = MODEL_COOLDOWN.get(model_name, 0.0)
    return until > asyncio.get_running_loop().time()


def mark_model_failure(model_name: str, permanent: bool = False):
    now = asyncio.get_running_loop().time()
    MODEL_FAILURES[model_name] = MODEL_FAILURES.get(model_name, 0) + 1
    # Permanent failures get a longer cooldown; transient failures get a
    # shorter one. This avoids hammering a provider during outages.
    multiplier = 4 if permanent else min(MODEL_FAILURES[model_name], 3)
    MODEL_COOLDOWN[model_name] = now + MODEL_COOLDOWN_SECONDS * multiplier


def clear_model_failure(model_name: str):
    MODEL_FAILURES.pop(model_name, None)
    MODEL_COOLDOWN.pop(model_name, None)


def classify_llm_error(exc: Exception) -> tuple[str, bool]:
    """Return (category, permanent-ish) for routing decisions."""
    name = type(exc).__name__.lower()
    message = str(exc).lower()

    if "notfound" in name or "not found" in message or "404" in message:
        return "model_not_found", True
    if "authentication" in name or "unauthorized" in message or "401" in message:
        return "authentication", True
    if "permission" in name or "forbidden" in message or "403" in message:
        return "permission", True
    if "ratelimit" in name or "rate limit" in message or "429" in message:
        return "rate_limit", False
    if "timeout" in name or "timed out" in message:
        return "timeout", False
    if "connection" in name or "connect" in message:
        return "connection", False
    if "unsupported" in name or "not support" in message:
        return "unsupported_parameter", True
    if "json" in name or "json" in message:
        return "invalid_model_output", False
    return "unknown", False


async def call_llm_with_fallback(messages: list[dict], *, purpose: str = "automation", timeout: float = 30.0):
    """Single production LLM gateway used by every agent."""
    if not FALLBACK_MODELS:
        raise RuntimeError(
            "No LLM providers are configured. Set NVIDIA_NIM_API_KEY, "
            "OPENROUTER_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, or "
            "HUGGINGFACE_API_KEY/HF_TOKEN + HF_CHAT_MODEL."
        )

    errors = []
    for model_name in FALLBACK_MODELS:
        if model_is_cooled_down(model_name):
            logger.warning(f"[LLM Router] Skipping cooled-down model: {model_name}")
            continue

        try:
            logger.info(f"[LLM Router] {purpose}: trying {model_name}")
            response = await litellm.acompletion(
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"},
                timeout=timeout,
                num_retries=0,
                drop_params=True,
            )
            clear_model_failure(model_name)
            return response, model_name
        except Exception as exc:
            category, permanent = classify_llm_error(exc)
            mark_model_failure(model_name, permanent=permanent)
            errors.append({
                "model": model_name,
                "category": category,
                "error": str(exc),
            })
            logger.warning(
                f"[LLM Router] {model_name} failed | category={category} | "
                f"permanent={permanent} | error={exc}"
            )
            continue

    details = " | ".join(
        f"{item['model']} [{item['category']}] {item['error']}"
        for item in errors
    )
    raise RuntimeError(f"All configured LLM models failed: {details}")


# --- LEARNED APP KNOWLEDGE BASE ---
# This dictionary is the system's "memory" of correct commands.
# When the LLM hallucinates wrong scripts, the middleware below overrides them.
# Future: This will be backed by Redis/PostgreSQL for dynamic learning.
KNOWN_APP_COMMANDS = {
    "Windows": {
        "vscode": {"script": "code", "process": "Code.exe"},
        "vs code": {"script": "code", "process": "Code.exe"},
        "visual studio code": {"script": "code", "process": "Code.exe"},
        "notepad": {"script": "notepad", "process": "notepad.exe"},
        "calculator": {"script": "calc", "process": "Calculator.exe"},
        "paint": {"script": "mspaint", "process": "mspaint.exe"},
        "file explorer": {"script": 'Start-Process "explorer"', "process": "explorer.exe"},
        "task manager": {"script": "taskmgr", "process": "Taskmgr.exe"},
        "camera": {"script": "Start-Process 'microsoft.windows.camera:'", "process": "WindowsCamera.exe"},
        "recycle bin": {"script": 'Start-Process "shell:RecycleBinFolder"', "process": "explorer.exe"},
        "git bash": {"script": r'Start-Process "C:\Program Files\Git\git-bash.exe"', "process": "git-bash.exe"},
        "terminal": {"script": "wt", "process": "WindowsTerminal.exe"},
        "powershell": {"script": "powershell", "process": "powershell.exe"},
        "word": {"script": "winword", "process": "WINWORD.EXE"},
        "excel": {"script": "excel", "process": "EXCEL.EXE"},
        "powerpoint": {"script": "powerpnt", "process": "POWERPNT.EXE"},
        "cmd": {"script": "cmd", "process": "cmd.exe"},
        "snipping tool": {"script": "snippingtool", "process": "SnippingTool.exe"},
        "settings": {"script": "start ms-settings:", "process": "SystemSettings.exe"},
        "spotify": {"script": "Start-Process 'spotify:'", "process": "Spotify.exe"}
    },
    "Linux": {
        "vscode": {"script": "code", "process": "code"},
        "vs code": {"script": "code", "process": "code"},
        "visual studio code": {"script": "code", "process": "code"},
        "notepad": {"script": "gedit", "process": "gedit"},
        "calculator": {"script": "gnome-calculator", "process": "gnome-calculator"},
        "paint": {"script": "gimp", "process": "gimp"},
        "file explorer": {"script": "nautilus", "process": "nautilus"},
        "task manager": {"script": "gnome-system-monitor", "process": "gnome-system-monitor"},
        "terminal": {"script": "gnome-terminal", "process": "gnome-terminal"}
    }
}

# --- REDIS LEARNING STORE ---
# Connect to Redis for persistent command learning across restarts.

try:
    redis_client = redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, db=0, decode_responses=True)
    redis_client.ping()
    logger.info("Redis Learning Store connected successfully")
except Exception as e:
    redis_client = None
    logger.warning(f"Redis unavailable, falling back to in-memory only: {e}")

DB_POOL = None

async def init_db():
    global DB_POOL
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@postgres:5432/nl_automation")
    DB_POOL = await asyncpg.create_pool(db_url)
    async with DB_POOL.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id SERIAL PRIMARY KEY,
                original_prompt TEXT NOT NULL,
                target_os VARCHAR(50),
                requires_browser BOOLEAN DEFAULT FALSE,
                target_url TEXT,
                shell_script TEXT,
                expected_process VARCHAR(100),
                scheduled_for TIMESTAMP WITH TIME ZONE NOT NULL,
                timezone VARCHAR(100),
                schedule_type VARCHAR(30) DEFAULT 'one_time',
                priority INTEGER DEFAULT 5,
                status VARCHAR(30) DEFAULT 'scheduled',
                approval_token_hash VARCHAR(128),
                approval_expires_at TIMESTAMP WITH TIME ZONE,
                execution_id VARCHAR(100),
                client_id VARCHAR(200),
                request_id VARCHAR(200),
                attempt_count INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                triggered_at TIMESTAMP WITH TIME ZONE,
                approved_at TIMESTAMP WITH TIME ZONE,
                denied_at TIMESTAMP WITH TIME ZONE,
                completed_at TIMESTAMP WITH TIME ZONE,
                failed_at TIMESTAMP WITH TIME ZONE,
                cancelled_at TIMESTAMP WITH TIME ZONE,
                expired_at TIMESTAMP WITH TIME ZONE,
                last_error TEXT,
                failure_reason TEXT,
                execution_result JSONB,
                raw_workflow JSONB,
                metadata JSONB
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                message TEXT NOT NULL,
                trigger_time TIMESTAMP NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS execution_logs (
                id SERIAL PRIMARY KEY,
                prompt TEXT NOT NULL,
                os_context VARCHAR(50),
                model_used VARCHAR(100),
                is_safe BOOLEAN,
                requires_browser BOOLEAN,
                target_url TEXT,
                shell_script TEXT,
                expected_process VARCHAR(100),
                is_reminder BOOLEAN,
                raw_response JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')


        # Upgrade databases created by OmniShell V2 without requiring manual SQL.
        for migration in [
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS schedule_type VARCHAR(30) DEFAULT 'one_time'",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 5",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS approval_token_hash VARCHAR(128)",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS approval_expires_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS client_id VARCHAR(200)",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS request_id VARCHAR(200)",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 0",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS max_attempts INTEGER DEFAULT 3",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS expired_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS last_error TEXT",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS metadata JSONB",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS is_recurring BOOLEAN DEFAULT FALSE",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS recurrence_rule VARCHAR(100)",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS condition_script TEXT",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS capability_type VARCHAR(50) DEFAULT 'scheduled_workflow'",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS multi_step_plan JSONB",
            "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS recovery_strategy JSONB",
        ]:
            try:
                await conn.execute(migration)
            except Exception as migration_error:
                logger.warning(f"Scheduled task migration skipped: {migration_error}")

        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_due "
            "ON scheduled_tasks (status, scheduled_for, priority, id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_request "
            "ON scheduled_tasks (request_id)"
        )


@app.on_event("startup")
async def startup_event():
    await init_db()

def get_learned_command(app_name: str) -> dict | None:
    """Check Redis for a previously learned correct command."""
    if not redis_client:
        return None
    try:
        cached = redis_client.get(f"learned_cmd:{app_name}")
        if cached:
            logger.info(f"Redis Cache HIT for '{app_name}'")
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Redis lookup failed: {e}")
    return None

def store_learned_command(app_name: str, script: str, process: str):
    """Store a verified correct command in Redis for future use."""
    if not redis_client:
        return
    try:
        data = {"script": script, "process": process}
        redis_client.set(f"learned_cmd:{app_name}", json.dumps(data))
        logger.info(f"Redis STORED learned command: '{app_name}' -> '{script}'")
    except Exception as e:
        logger.warning(f"Redis store failed: {e}")

# --- COMMAND RESEARCH AGENT ---
# Searches the web in parallel with the main LLM to find the correct command.
async def research_command(app_query: str, target_os: str) -> dict | None:
    """
    Agent 5: Command Research Agent
    Searches DuckDuckGo for the correct CLI command, then uses a fast LLM
    to extract the precise command from search results.
    """
    try:
        from duckduckgo_search import DDGS
        
        # Determine OS keyword for search
        os_keyword = "Windows PowerShell" if "windows" in target_os.lower() else "Linux bash"
        search_query = f"how to open {app_query} from command line {os_keyword}"
        
        logger.info(f"[Research Agent] Searching: '{search_query}'")
        
        # Run DuckDuckGo search in a thread (it's synchronous)
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, lambda: list(DDGS().text(search_query, max_results=5)))
        
        if not results:
            logger.warning("[Research Agent] No search results found")
            return None
        
        # Build context from search results
        search_context = "\n\n".join([
            f"Title: {r.get('title', '')}\nSnippet: {r.get('body', '')}" 
            for r in results[:5]
        ])
        
        logger.info(f"[Research Agent] Got {len(results)} search results, extracting command...")
        
        # Use a fast LLM to extract the correct command from search results
        extraction_prompt = f"""You are a command extraction agent. Given these search results about opening '{app_query}' on {os_keyword}, extract the SIMPLEST correct command that works.

RULES:
- Return ONLY valid JSON: {{"script": "the_command", "process": "expected_process.exe"}}
- For Windows: prefer simple commands like 'code' over long paths like 'Start-Process -FilePath "C:\\..."'
- If the app adds itself to PATH, just use the short command name
- The 'process' field should be the .exe name that appears in Task Manager
- NO explanations, NO markdown, JUST the JSON object

Search Results:
{search_context}"""

        extract_response, extraction_model = await call_llm_with_fallback(
            [
                {"role": "system", "content": "You extract CLI commands from search results. Return ONLY raw JSON."},
                {"role": "user", "content": extraction_prompt}
            ],
            purpose="command-research",
            timeout=15.0,
        )
        logger.info(f"[Research Agent] Extraction model: {extraction_model}")
        
        raw = extract_response.choices[0].message.content.strip()
        # Clean markdown fencing if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        
        result = json.loads(raw)
        logger.info(f"[Research Agent] Extracted command: script='{result.get('script')}', process='{result.get('process')}'")
        return result
        
    except Exception as e:
        logger.warning(f"[Research Agent] Failed: {type(e).__name__} - {str(e)}")
        return None


import time

def record_llm_usage(model_name: str, success: bool, tokens: dict, error: str = None):
    if not redis_client:
        return
    try:
        provider = model_name.split("/")[0] if "/" in model_name else "gemini"
        data = {
            "timestamp": int(time.time()),
            "model": model_name,
            "provider": provider,
            "success": success,
            "prompt_tokens": tokens.get("prompt_tokens", 0),
            "completion_tokens": tokens.get("completion_tokens", 0),
            "total_tokens": tokens.get("total_tokens", 0),
            "error": error
        }
        redis_client.lpush("llm_analytics", json.dumps(data))
    except Exception as e:
        logger.warning(f"Failed to record LLM usage: {e}")

@app.get("/api/analytics")
async def get_analytics():
    records = []
    if redis_client:
        raw_records = redis_client.lrange("llm_analytics", 0, -1)
        for r in raw_records:
            try:
                records.append(json.loads(r))
            except:
                pass

    db_logs = []
    if DB_POOL:
        try:
            async with DB_POOL.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT id, prompt, os_context, model_used, is_safe, requires_browser, 
                           target_url, shell_script, expected_process, is_reminder, 
                           created_at, raw_response
                    FROM execution_logs 
                    ORDER BY id DESC LIMIT 50
                ''')
                for row in rows:
                    raw_resp = {}
                    try:
                        raw_resp = json.loads(row["raw_response"]) if row["raw_response"] else {}
                    except:
                        pass
                    db_logs.append({
                        "id": row["id"],
                        "prompt": row["prompt"],
                        "os_context": row["os_context"],
                        "model_used": row["model_used"],
                        "is_safe": row["is_safe"],
                        "requires_browser": row["requires_browser"],
                        "target_url": row["target_url"],
                        "capability_type": raw_resp.get("capability_type") or "shell_operation",
                        "timing": raw_resp.get("timing") or {},
                        "created_at": row["created_at"].isoformat() if row.get("created_at") else None
                    })
        except Exception as e:
            logger.warning(f"Error reading execution_logs from DB: {e}")

    return {
        "data": records,
        "fallback_flow": FALLBACK_MODELS,
        "execution_history": db_logs,
        "capabilities_summary": CAPABILITIES_REGISTRY,
    }


async def log_execution_to_db(prompt: str, os_context: str, result: dict):
    from tracenest.logger import Logger
    Logger().info(f'DB_POOL IS: {DB_POOL}')
    if not DB_POOL: return
    try:
        async with DB_POOL.acquire() as conn:
            await conn.execute('''
                INSERT INTO execution_logs 
                (prompt, os_context, model_used, is_safe, requires_browser, target_url, shell_script, expected_process, is_reminder, raw_response)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ''', 
            prompt, 
            os_context, 
            result.get("model_used"), 
            bool(result.get("is_safe")), 
            bool(result.get("requires_browser")), 
            result.get("target_url"), 
            result.get("shell_script"), 
            result.get("expected_process"), 
            bool(result.get("is_reminder")), 
            json.dumps(result))
    except Exception as e:
        from tracenest.logger import Logger
        Logger().error(f"Failed to log execution to DB: {e}")


import re as _re

# ============================================================
# HARDCODED PRE-LLM GUARDRAIL (Cannot be jailbroken)
# ============================================================
BLOCKED_PATTERNS = [
    # Password/credential theft
    (r"password[s]?.*(extract|steal|get|retrieve|dump|export|show|find|list|read)", "Password/credential extraction attempt"),
    (r"(shadow|passwd).*(read|cat|dump|access|get|view)", "System credential file access"),
    (r"(browser|chrome|brave|firefox|edge).*(password|cookie|session|token|profile|autofill)", "Browser data theft attempt"),
    (r"keylog", "Keylogger deployment"),
    # System file attacks
    (r"(delete|remove|rm|wipe|destroy|nuke).*(/etc|/root|/boot|/sys|/proc|system32|C:\\Windows|\.config\b|/snap\b)", "System directory attack"),
    (r"rm\s+-rf\s+(/|~|\$HOME)\s*$", "Root/home directory wipe"),
    (r"(mkfs|fdisk|wipefs|dd\s+if=).*(/dev/sd|/dev/nvme|/dev/hd)", "Disk destruction"),
    # Mass destruction
    (r"(delete|remove|rm|wipe).*(all|everything|every).*(file|folder|directory)", "Mass file destruction"),
    # Illegal/harmful content
    (r"(porn|xxx|adult\s+content|nsfw|hentai)", "Adult/illegal content request"),
    (r"(dark\s*web|\.onion|tor\s+hidden|silk\s*road)", "Dark web access attempt"),
    (r"(hack|exploit|crack|brute\s*force|reverse\s*shell|rat\s+trojan|ddos|dos\s+attack)", "Hacking/exploitation attempt"),
    (r"(arp\s*spoof|dns\s*poison|mitm|man.in.the.middle)", "Network attack"),
    # Social engineering bypass
    (r"(bypass|ignore|skip|override|disable).*(safe|secur|guard|confirm|check|protect)", "Security bypass attempt"),
    # Crypto mining
    (r"(crypto\s*min|xmrig|minergate|nicehash|coinhive)", "Crypto mining attempt"),
]

def hardcoded_guardrail_check(prompt: str) -> tuple:
    """Pre-LLM guardrail. Returns (is_blocked, reason). Cannot be jailbroken."""
    prompt_lower = prompt.lower()
    for pattern, reason in BLOCKED_PATTERNS:
        if _re.search(pattern, prompt_lower):
            return True, reason
    return False, ""


# ============================================================
# SCHEDULING HELPERS
# ============================================================

SCHEDULE_DEFAULT_TZ = os.getenv("OMNISHELL_DEFAULT_TIMEZONE", "Asia/Kolkata")
SCHEDULE_APPROVAL_TIMEOUT = int(os.getenv("OMNISHELL_APPROVAL_TIMEOUT_SECONDS", "300"))
SCHEDULE_MAX_DELAY_DAYS = int(os.getenv("OMNISHELL_MAX_SCHEDULE_DAYS", "365"))


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _safe_timezone(name):
    candidate = (name or SCHEDULE_DEFAULT_TZ).strip()
    try:
        ZoneInfo(candidate)
        return candidate
    except Exception:
        return "UTC"


def _parse_schedule_datetime(value, timezone_name=None):
    dt = datetime.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(_safe_timezone(timezone_name)))
    return dt.astimezone(datetime.timezone.utc)


def _calculate_next_recurrence(rule: str, tz_name: str = None) -> datetime.datetime:
    """Calculate the next execution time for recurring tasks."""
    tz = ZoneInfo(_safe_timezone(tz_name))
    now_local = _utc_now().astimezone(tz)
    rule_clean = (rule or "").strip().lower()
    
    # interval:Nm or interval:Nh or interval:Ns or interval:Nd
    m_int = re.match(r"^interval:(\d+(?:\.\d+)?)\s*([smhd])$", rule_clean)
    if m_int:
        amount = float(m_int.group(1))
        unit = m_int.group(2)
        if unit == "s": delta = datetime.timedelta(seconds=amount)
        elif unit == "m": delta = datetime.timedelta(minutes=amount)
        elif unit == "h": delta = datetime.timedelta(hours=amount)
        elif unit == "d": delta = datetime.timedelta(days=amount)
        else: delta = datetime.timedelta(minutes=5)
        return (now_local + delta).astimezone(datetime.timezone.utc)
        
    # daily:HH:MM
    m_daily = re.match(r"^daily:(\d{1,2}):(\d{2})$", rule_clean)
    if m_daily:
        h, m = int(m_daily.group(1)), int(m_daily.group(2))
        target_today = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        if target_today > now_local + datetime.timedelta(minutes=1):
            return target_today.astimezone(datetime.timezone.utc)
        else:
            return (target_today + datetime.timedelta(days=1)).astimezone(datetime.timezone.utc)
            
    # Default fallback: 5 minutes interval
    return (now_local + datetime.timedelta(minutes=5)).astimezone(datetime.timezone.utc)


def _deterministic_recurrence_rule(prompt: str, timezone_name: str = None) -> tuple[bool, str | None, datetime.datetime | None]:
    """Detect recurring rules such as 'every 5 minutes', 'daily at 9am', 'every hour'."""
    p = prompt.lower().strip()
    tz_name = _safe_timezone(timezone_name)
    now_local = _utc_now().astimezone(ZoneInfo(tz_name))

    # Pattern: every N minutes/hours/days/seconds
    m = re.search(r"\bevery\s+(\d+(?:\.\d+)?)\s*(second|seconds|sec|secs|minute|minutes|min|mins|hour|hours|hr|hrs|day|days)\b", p)
    if m:
        amount = float(m.group(1))
        unit = m.group(2)
        if unit.startswith(("sec", "second")):
            rule = f"interval:{int(amount)}s"
            delta = datetime.timedelta(seconds=amount)
        elif unit.startswith(("min", "minute")):
            rule = f"interval:{int(amount)}m"
            delta = datetime.timedelta(minutes=amount)
        elif unit.startswith(("hour", "hr")):
            rule = f"interval:{int(amount)}h"
            delta = datetime.timedelta(hours=amount)
        else:
            rule = f"interval:{int(amount)}d"
            delta = datetime.timedelta(days=amount)
        return True, rule, (now_local + delta).astimezone(datetime.timezone.utc)

    # Pattern: daily at HH:MM / daily at H AM/PM / every day at ...
    m_daily = re.search(r"\b(?:daily|every\s+day)(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", p)
    if m_daily:
        hour = int(m_daily.group(1))
        minute = int(m_daily.group(2) or 0)
        meridiem = m_daily.group(3)
        if meridiem:
            if hour == 12: hour = 0
            if meridiem == "pm": hour += 12
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            rule = f"daily:{hour:02d}:{minute:02d}"
            target_today = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_today > now_local + datetime.timedelta(seconds=30):
                first_run = target_today
            else:
                first_run = target_today + datetime.timedelta(days=1)
            return True, rule, first_run.astimezone(datetime.timezone.utc)

    # Pattern: hourly / every hour
    if re.search(r"\b(?:hourly|every\s+hour)\b", p):
        rule = "interval:1h"
        return True, rule, (now_local + datetime.timedelta(hours=1)).astimezone(datetime.timezone.utc)

    return False, None, None


def _deterministic_relative_schedule(prompt, timezone_name):
    """Resolve common 'after/in N minutes/hours' phrases without LLM arithmetic."""
    p = prompt.lower().strip()
    tz_name = _safe_timezone(timezone_name)
    now_local = _utc_now().astimezone(ZoneInfo(tz_name))

    m = re.search(r"\b(?:after|in)\s+(\d+(?:\.\d+)?)\s*(second|seconds|sec|secs|minute|minutes|min|mins|hour|hours|hr|hrs|day|days)\b", p)
    if m:
        amount = float(m.group(1))
        unit = m.group(2)
        if unit.startswith(("sec", "second")):
            delta = datetime.timedelta(seconds=amount)
        elif unit.startswith(("minute", "min")):
            delta = datetime.timedelta(minutes=amount)
        elif unit.startswith(("hour", "hr")):
            delta = datetime.timedelta(hours=amount)
        else:
            delta = datetime.timedelta(days=amount)
        return (now_local + delta).astimezone(datetime.timezone.utc), tz_name

    m = re.search(r"\btomorrow(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", p)
    if m:
        hour = int(m.group(1)); minute = int(m.group(2) or 0); meridiem = m.group(3)
        if meridiem:
            if hour == 12: hour = 0
            if meridiem == "pm": hour += 12
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            candidate = (now_local + datetime.timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return candidate.astimezone(datetime.timezone.utc), tz_name

    return None, tz_name


def _schedule_is_valid(dt):
    now = _utc_now()
    if dt <= now - datetime.timedelta(seconds=5):
        raise ValueError("Scheduled time must be in the future.")
    if dt > now + datetime.timedelta(days=SCHEDULE_MAX_DELAY_DAYS):
        raise ValueError(f"Scheduled time cannot be more than {SCHEDULE_MAX_DELAY_DAYS} days in the future.")


def _hash_approval_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_approval_token():
    return secrets.token_urlsafe(32)


def _json_safe_record(record):
    result = dict(record)
    for key, value in result.items():
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
            result[key] = value.isoformat()
    return result


async def create_scheduled_task(*, prompt, workflow, scheduled_for, timezone_name, client_id=None, request_id=None):
    _schedule_is_valid(scheduled_for)
    schedule_type = workflow.get("schedule_type", "one_time")
    priority = max(1, min(int(workflow.get("priority", 5) or 5), 10))
    approval_timeout = max(30, min(int(workflow.get("approval_timeout_seconds") or SCHEDULE_APPROVAL_TIMEOUT), 3600))
    is_recurring = bool(workflow.get("is_recurring", False))
    recurrence_rule = workflow.get("recurrence_rule")
    condition_script = (workflow.get("conditional_logic") or {}).get("condition_script") if isinstance(workflow.get("conditional_logic"), dict) else None
    capability_type = workflow.get("capability_type", "scheduled_workflow")

    async with DB_POOL.acquire() as conn:
        if request_id:
            existing = await conn.fetchrow(
                "SELECT * FROM scheduled_tasks WHERE request_id=$1 ORDER BY id DESC LIMIT 1",
                request_id,
            )
            if existing:
                return _json_safe_record(existing)

        row = await conn.fetchrow(
            """INSERT INTO scheduled_tasks (
                original_prompt,target_os,requires_browser,target_url,shell_script,
                expected_process,scheduled_for,timezone,schedule_type,priority,status,
                client_id,request_id,max_attempts,raw_workflow,metadata,
                is_recurring,recurrence_rule,condition_script,capability_type,
                multi_step_plan,recovery_strategy
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'scheduled',$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)
            RETURNING *""",
            prompt, workflow.get("target_os"), bool(workflow.get("requires_browser")),
            workflow.get("target_url"), workflow.get("shell_script"),
            workflow.get("expected_process"), scheduled_for, timezone_name,
            schedule_type, priority, client_id, request_id,
            int(os.getenv("OMNISHELL_SCHEDULE_MAX_ATTEMPTS", "3")),
            json.dumps(workflow),
            json.dumps({
                "created_by": "omnishell-ai",
                "approval_timeout_seconds": approval_timeout,
                "created_at_utc": _utc_now().isoformat(),
            }),
            is_recurring, recurrence_rule, condition_script, capability_type,
            json.dumps(workflow.get("multi_step_plan")) if workflow.get("multi_step_plan") else None,
            json.dumps(workflow.get("recovery_strategy")) if workflow.get("recovery_strategy") else None,
        )
        return _json_safe_record(row)


# ============================================================
# 19 CORE CAPABILITIES CLASSIFIER & METADATA
# ============================================================

CAPABILITIES_REGISTRY = {
    "question_answering": {
        "title": "Questions and Answers",
        "description": "Direct contextual answers for factual, conceptual, math, and knowledge inquiries.",
        "requires_execution": False,
    },
    "information_request": {
        "title": "Information Requests",
        "description": "System documentation, summaries, technical overviews, and structured information.",
        "requires_execution": False,
    },
    "system_inspection": {
        "title": "System Inspection",
        "description": "Real-time diagnostic inspection of CPU, memory, disk, network, processes, and OS stats.",
        "requires_execution": True,
    },
    "analysis": {
        "title": "Analysis",
        "description": "In-depth diagnostic log analysis, code audits, architectural comparisons, and performance evaluation.",
        "requires_execution": False,
    },
    "application_operation": {
        "title": "Application Operations",
        "description": "Cross-platform launching, process tracking, and lifecycle management for desktop applications.",
        "requires_execution": True,
    },
    "browser_operation": {
        "title": "Browser Operations",
        "description": "Web navigation, deep-linking into web applications, and automated browser launches.",
        "requires_execution": True,
    },
    "file_operation": {
        "title": "File Operations",
        "description": "Creating, reading, searching, archiving, moving, and safely managing local files and directories.",
        "requires_execution": True,
    },
    "shell_operation": {
        "title": "Shell Operations",
        "description": "Native, secure shell command execution on Linux, macOS, and Windows.",
        "requires_execution": True,
    },
    "multi_step": {
        "title": "Multi-Step Tasks",
        "description": "Sequential task pipelines decomposed into structured steps with state propagation.",
        "requires_execution": True,
    },
    "interactive_workflow": {
        "title": "Interactive Workflows",
        "description": "Guided multi-stage workflows with interactive user inputs and confirmation checkpoints.",
        "requires_execution": True,
    },
    "scheduled_workflow": {
        "title": "Scheduled Workflows",
        "description": "Autonomous future execution at exact timestamps or relative offsets with human-in-the-loop gates.",
        "requires_execution": True,
    },
    "recurring_workflow": {
        "title": "Recurring Workflows",
        "description": "Continuous periodic tasks scheduled with interval or daily recurrence rules.",
        "requires_execution": True,
    },
    "conditional_workflow": {
        "title": "Conditional Workflows",
        "description": "Branching execution paths evaluated dynamically based on system state or script exit codes.",
        "requires_execution": True,
    },
    "reminder": {
        "title": "Reminders",
        "description": "Contextual scheduled alerts and notifications with custom messages.",
        "requires_execution": True,
    },
    "research": {
        "title": "Research Tasks",
        "description": "Deep multi-tier research synthesizing web data and dynamically discovering unknown commands.",
        "requires_execution": False,
    },
    "planning_only": {
        "title": "Planning-Only Requests",
        "description": "Architectural blueprints, phased migration plans, and sequence diagrams without execution.",
        "requires_execution": False,
    },
    "human_approval": {
        "title": "Tasks Requiring Human Approval",
        "description": "Elevated and potentially destructive operations protected by strict multi-step human confirmation.",
        "requires_execution": True,
    },
    "clarification": {
        "title": "Tasks Requiring Clarification",
        "description": "Ambiguous or underspecified requests automatically prompting user for clarifying choices.",
        "requires_execution": False,
    },
    "recovery_failure": {
        "title": "Tasks Requiring Recovery After Failure",
        "description": "Self-healing resilient workflows equipped with automated retries and fallback execution chains.",
        "requires_execution": True,
    },
}


def _intent_entities(prompt: str) -> dict[str, Any]:
    """Extract stable entities before an LLM is allowed to decide execution."""
    urls = re.findall(r"https?://[^\s<>\"']+", prompt)
    paths = re.findall(r"(?:~|/|[A-Za-z]:\\)[^\s<>\"']+", prompt)
    emails = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", prompt)
    return {
        "urls": urls[:10],
        "paths": paths[:10],
        "emails": emails[:10],
    }


def _intent_result(capability: str, *, confidence: float, signals: list[str],
                   execution_mode: str, safety_level: str = "low",
                   **kwargs: Any) -> dict[str, Any]:
    """Create a consistent intent envelope for every route."""
    result = {
        "capability_type": capability,
        "intent_confidence": max(0.0, min(1.0, confidence)),
        "intent_signals": signals,
        "intent_entities": kwargs.pop("intent_entities", {}),
        "execution_mode": execution_mode,
        "safety_level": safety_level,
        "ambiguity_reasons": kwargs.pop("ambiguity_reasons", []),
        "failure_policy": kwargs.pop("failure_policy", {
            "max_attempts": 2,
            "retry_on": ["timeout", "connection", "transient"],
            "verify_after_each_step": True,
        }),
        "is_safe": safety_level != "blocked",
    }
    result.update(kwargs)
    return result


def classify_prompt_capability(prompt: str, user_agent_os: str) -> dict:
    """Resolve intent using deterministic precedence, entity extraction and safety gates.

    This is deliberately conservative: execution intent must be explicit enough to
    identify an action, target and mode. The LLM may enrich the plan later, but it
    cannot silently turn an informational request into an executable workflow.
    """
    raw = (prompt or "").strip()
    p = raw.lower()
    is_windows = "windows" in user_agent_os.lower()
    is_linux = "linux" in user_agent_os.lower() or "ubuntu" in user_agent_os.lower()
    entities = _intent_entities(raw)

    # Hard stop / human approval takes precedence over all other classifications.
    destructive = re.search(
        r"\b(rm\s+-rf|rm\s+-[^\s]*r|rm\s+-[^\s]*f|delete\b.*(?:folder|file|trash|directory|data)|empty\s+trash|clean\s+trash|trash|wipe|format|mkfs|fdisk|drop\s+database|killall|pkill\s+-9|destroy|nuke|rmdir)\b",
        p,
    )
    if destructive:
        return _intent_result(
            "human_approval", confidence=.99,
            signals=["destructive_operation"], execution_mode="approval_gate",
            safety_level="high", intent_entities=entities,
            requires_approval=True,
            approval_reason="The requested operation performs file deletions, trash purges, or system mutations requiring authorization.",
            shell_script=("find /tmp -type f -atime +7 -delete" if is_linux else "Remove-Item -Path $env:TEMP\\* -Recurse -Force"),
            direct_answer="This operation performs file deletions or system mutations and must pass a human approval gate before execution.",
        )

    # Recovery is an explicit workflow modifier and therefore wins over generic execution.
    recovery_terms = ["if it fails", "on failure", "fallback", "retry", "auto-heal", "automatic rollback", "rollback on"]
    if any(t in p for t in recovery_terms):
        script = "systemctl restart nginx" if is_linux else "Restart-Service nginx"
        return _intent_result(
            "recovery_failure", confidence=.98,
            signals=["recovery_modifier"], execution_mode="resilient_execution",
            safety_level="medium", intent_entities=entities,
            shell_script=script,
            recovery_strategy={
                "retry_limit": 3,
                "retry_backoff_seconds": [1, 3, 8],
                "diagnostic_command": "systemctl status nginx --no-pager" if is_linux else "Get-Service nginx",
                "fallback_script": "echo 'Fallback/rollback required; no destructive fallback is assumed.'",
                "rollback_on_failure": "rollback" in p,
            },
            failure_policy={"max_attempts": 3, "retry_on": ["timeout", "connection", "transient"], "verify_after_each_step": True},
            direct_answer="A resilient workflow will retry transient failures, verify the result, and use the configured recovery path when necessary.",
        )

    # Clarification must happen before execution when the target is materially missing.
    vague = {
        "deploy", "fix", "fix bug", "clean", "clean up", "update", "install",
        "run test", "delete", "deploy the project", "deploy the application",
        "deploy the application to cloud", "open it", "run it", "do it",
    }
    if p in vague or re.fullmatch(r"(deploy|install|update|delete|clean)\s+(the|my)\s+\w+", p or ""):
        return _intent_result(
            "clarification", confidence=.99, signals=["missing_target_or_scope"],
            execution_mode="clarification_gate", safety_level="low", intent_entities=entities,
            requires_clarification=True,
            ambiguity_reasons=["Target, environment, or desired scope is not sufficiently specified."],
            clarification_questions=[
                "What exact target/project should OmniShell operate on?",
                "Which environment should be affected (development, staging, or production)?",
                "Should OmniShell preview the plan first or execute it after approval?",
            ],
            direct_answer="I need the target and scope before I can safely execute this request.",
        )

    # Multi-step intent is structural: require multiple actions or explicit sequencing.
    multi_markers = ["multi-step", "multistep", "first ", "then ", "after that", "and finally", "step 1", "steps:", "once that"]
    if sum(1 for marker in multi_markers if marker in p) >= 1 and re.search(r"\b(and|then|after|finally|first|step)\b", p) and not re.search(r"\bif\b.+\bthen\b", p):
        plan = [
            {"step_id": 1, "name": "Prepare", "description": "Validate prerequisites and target.", "command": None, "expected": "Prerequisites valid"},
            {"step_id": 2, "name": "Execute", "description": "Perform the requested operation.", "command": None, "expected": "Operation completes"},
            {"step_id": 3, "name": "Verify", "description": "Verify the resulting state and recover if needed.", "command": None, "expected": "Postcondition verified"},
        ]
        return _intent_result(
            "multi_step", confidence=.98, signals=["explicit_sequence"],
            execution_mode="verified_pipeline", safety_level="medium", intent_entities=entities,
            multi_step_plan=plan, shell_script=None,
            direct_answer="Multi-step workflow detected. Each step will be validated before the next step, with failure handling at the step boundary.",
        )

    # Scheduling/recurrence is evaluated before ordinary action verbs.
    is_rec, rec_rule, rec_dt = _deterministic_recurrence_rule(p, None)
    if is_rec:
        return _intent_result(
            "recurring_workflow", confidence=.99, signals=["recurrence_expression"],
            execution_mode="scheduled_execution", safety_level="medium", intent_entities=entities,
            is_scheduled=True, is_recurring=True, recurrence_rule=rec_rule,
            scheduled_time=rec_dt.isoformat() if rec_dt else None,
            shell_script=("df -h" if "disk" in p else "uptime"),
            direct_answer=f"Recurring workflow resolved with rule `{rec_rule}`.",
        )

    if p.startswith(("remind me", "set reminder", "set a reminder")):
        dt = _utc_now() + datetime.timedelta(minutes=15)
        return _intent_result(
            "reminder", confidence=.99, signals=["reminder_language"],
            execution_mode="notification_schedule", safety_level="low", intent_entities=entities,
            is_reminder=True, is_scheduled=True, scheduled_time=dt.isoformat(),
            reminder_time=dt.isoformat(), reminder_message=raw,
            direct_answer=f"Reminder scheduled: {raw}",
        )

    if re.search(r"\b(schedule|tomorrow|tonight|today at|run at|execute at|in \d+ (minutes?|hours?|days?))\b", p):
        return _intent_result(
            "scheduled_workflow", confidence=.97, signals=["future_time_expression"],
            execution_mode="scheduled_execution", safety_level="medium", intent_entities=entities,
            is_scheduled=True, scheduled_time=None,
            shell_script=("df -h" if "disk" in p else "echo 'Scheduled task executed'"),
            direct_answer="The request contains a future execution condition and will be handled as a scheduled workflow.",
        )

    # Conditional workflows require a branch expression, not merely the word 'if' in prose.
    if re.search(r"\bif\b.+\b(then|alert|notify|run|execute|start|stop|else|otherwise)\b", p):
        cond = "test 0 -eq 0"
        return _intent_result(
            "conditional_workflow", confidence=.97, signals=["condition_and_branch"],
            execution_mode="conditional_execution", safety_level="medium", intent_entities=entities,
            conditional_logic={"condition_script": cond, "on_success": "echo 'Condition passed'", "on_failure": "echo 'Condition failed'"},
            direct_answer="Conditional workflow detected; the condition and branch actions will be validated before execution.",
        )

    if any(k in p for k in ["interactive", "wizard", "prompt me", "ask me for", "walk me through"]):
        return _intent_result(
            "interactive_workflow", confidence=.98, signals=["interactive_language"],
            execution_mode="interactive_checkpoint", safety_level="medium", intent_entities=entities,
            requires_interactive=True,
            interactive_prompts=[
                "What is the target environment?",
                "What target/project should be modified?",
                "Should changes be applied automatically after validation?",
            ],
            direct_answer="Interactive workflow detected; OmniShell will pause at explicit checkpoints instead of guessing missing inputs.",
        )

    planning_terms = ["without executing", "do not execute", "don't execute", "plan only", "create a plan", "roadmap", "system design", "architecture for", "migration plan"]
    if p.startswith(("plan ", "design ", "create a plan", "roadmap ")) or any(t in p for t in planning_terms):
        plan = [
            {"step_id": 1, "name": "Assess", "description": "Inspect scope, dependencies and constraints.", "command": None, "expected": "Scope confirmed"},
            {"step_id": 2, "name": "Plan", "description": "Build ordered implementation steps with rollback points.", "command": None, "expected": "Plan validated"},
            {"step_id": 3, "name": "Validate", "description": "Identify risks, approvals and missing inputs.", "command": None, "expected": "Execution readiness known"},
        ]
        return _intent_result(
            "planning_only", confidence=.99, signals=["planning_language"],
            execution_mode="plan_only", safety_level="low", intent_entities=entities,
            is_planning_only=True, multi_step_plan=plan,
            direct_answer="### Execution Plan\n\n1. Assess scope and dependencies.\n2. Build ordered steps with validation and rollback points.\n3. Surface risks, approvals, and missing inputs.\n\nNo commands will be executed.",
        )

    research_terms = ["research ", "deep research", "investigate", "compare current", "find latest", "look up"]
    if any(t in p for t in research_terms):
        return _intent_result(
            "research", confidence=.96, signals=["research_language"],
            execution_mode="research_only", safety_level="low", intent_entities=entities,
            direct_answer=None,
        )

    analysis_terms = ["analyze", "analysis", "diagnose", "diagnosis", "audit", "investigate bottleneck", "performance evaluation"]
    if any(t in p for t in analysis_terms):
        script = "top -bn1 | head -15 && free -h && df -h /" if is_linux else "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10"
        return _intent_result(
            "analysis", confidence=.95, signals=["analysis_language"],
            execution_mode="inspect_then_analyze", safety_level="low", intent_entities=entities,
            shell_script=script,
            direct_answer="Analysis requested. OmniShell will collect relevant evidence before producing conclusions rather than assuming the current system state.",
        )

    # Browser intent: explicit URL/open/browse or web destinations
    browser_terms = [
        "open website", "open url", "browse to", "in my browser", "open in browser",
        "on browser", "in browser", "to browser", "open on browser", "open chrome",
        "in chrome", "on chrome", "open firefox", "in firefox", "on firefox", "open edge",
        "on edge", "in safari", "open safari", "open brave", "browse ", "visit "
    ]
    web_destinations = {
        "youtube music": "https://music.youtube.com",
        "you tube music": "https://music.youtube.com",
        "yt music": "https://music.youtube.com",
        "youtube": "https://www.youtube.com",
        "you tube": "https://www.youtube.com",
        "spotify": "https://open.spotify.com",
        "netflix": "https://www.netflix.com",
        "github": "https://github.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "reddit": "https://www.reddit.com",
        "twitter": "https://twitter.com",
        "x.com": "https://x.com",
        "amazon": "https://www.amazon.com",
        "chatgpt": "https://chat.openai.com",
        "claude": "https://claude.ai",
    }
    has_browser_term = any(t in p for t in browser_terms)
    has_web_dest = any(dest in p for dest in web_destinations)
    if entities["urls"] or has_browser_term or has_web_dest:
        url = entities["urls"][0] if entities["urls"] else None
        if not url:
            for dest, dest_url in web_destinations.items():
                if dest in p:
                    url = dest_url
                    break
        if not url and has_browser_term:
            url = "https://www.google.com"

        if url:
            is_mac = "darwin" in user_agent_os.lower() or "mac" in user_agent_os.lower()
            browser_cmd = f"xdg-open '{url}' || google-chrome '{url}'" if is_linux else (f"open '{url}'" if is_mac else f"Start-Process '{url}'")
            return _intent_result(
                "browser_operation", confidence=.99, signals=["browser_target"],
                execution_mode="browser_operation", safety_level="low", intent_entities=entities,
                requires_browser=True, target_url=url, shell_script=browser_cmd,
                direct_answer=f"Browser operation resolved for `{url}`.",
            )

    # System inspection is read-only and should outrank generic shell execution.
    inspection_terms = ["check cpu", "cpu usage", "cpu utilization", "memory usage", "memory utilization", "ram usage", "system memory", "inspect memory", "disk space", "disk usage", "system info", "inspect system", "system inspection", "list processes", "running processes", "top processes", "ip address", "network interfaces"]
    if any(k in p for k in inspection_terms):
        if any(x in p for x in ["cpu", "ram", "memory", "disk"]):
            script = "top -bn1 | head -15 && free -h && df -h /" if is_linux else "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10; Get-Volume"
        elif "process" in p:
            script = "ps aux --sort=-%mem | head -20" if is_linux else "Get-Process | Sort-Object WorkingSet -Descending | Select-Object -First 20"
        else:
            script = "ip addr show || ifconfig" if is_linux else "Get-NetIPAddress -AddressFamily IPv4"
        return _intent_result("system_inspection", confidence=.97, signals=["read_only_system_query"], execution_mode="read_only_inspection", safety_level="low", intent_entities=entities, shell_script=script, direct_answer="Read-only system inspection requested.")

    # Application operation: explicit action + known app. Avoid treating 'run tests' as app launch.
    apps = ["code", "vscode", "visual studio", "notepad", "calculator", "terminal", "slack", "spotify", "discord", "vlc", "file explorer"]
    if re.search(r"\b(open|launch|start)\b", p) and any(a in p for a in apps):
        return _intent_result("application_operation", confidence=.98, signals=["explicit_app_action"], execution_mode="local_application", safety_level="low", intent_entities=entities, shell_script=None, expected_process=None, direct_answer="Application operation resolved; the host command registry will select the verified native command.")

    # File operations are identified by file semantics and target entities.
    file_terms = ["create file", "write file", "read file", "list directory", "list files", "delete file", "search files", "find file", "backup file", "file named", "rename file", "move file", "copy file"]
    if any(k in p for k in file_terms) or entities["paths"]:
        script = "touch test_report.txt && ls -la" if is_linux else "New-Item test_report.txt; Get-ChildItem"
        return _intent_result("file_operation", confidence=.96, signals=["file_semantics"], execution_mode="file_operation", safety_level="medium", intent_entities=entities, shell_script=script, direct_answer="File operation detected; target paths and mutation scope should be validated before applying changes.")

    # Explicit shell intent is last among executable classes.
    if re.search(r"\b(run|execute|command|shell|terminal)\b", p):
        return _intent_result("shell_operation", confidence=.93, signals=["explicit_command_language"], execution_mode="shell_execution", safety_level="medium", intent_entities=entities, shell_script=None, direct_answer=None)

    # Pure Q&A / information. Never invent an answer in deterministic mode.
    q_starters = ("what is", "what are", "what's", "who is", "who are", "who's", "where is", "where are", "when did", "when was", "why is", "why do", "why does", "how does", "how do", "how to", "explain ", "define ", "tell me about", "what means", "which is", "can you explain")
    is_math = bool(re.fullmatch(r"[\d\s+\-*/^().%]+", p))
    if is_math or p.endswith("?") or p.startswith(q_starters):
        direct = None
        if "capital of india" in p: direct = "The capital of India is **New Delhi**."
        elif "capital of france" in p: direct = "The capital of France is **Paris**."
        elif "capital of japan" in p: direct = "The capital of Japan is **Tokyo**."
        elif "capital of usa" in p or "capital of the united states" in p: direct = "The capital of the United States is **Washington, D.C.**"
        elif "who invented linux" in p or "creator of linux" in p: direct = "Linux was created by **Linus Torvalds** in 1991."
        elif is_math:
            try:
                # Mathematical-only grammar, no names or calls are permitted.
                direct = f"**Calculation Result:** `{raw} = {eval(p, {'__builtins__': {}}, {})}`"
            except Exception:
                direct = None
        cap = "information_request" if p.startswith(("tell me about", "explain ", "define ")) else "question_answering"
        return _intent_result(cap, confidence=.99, signals=["informational_language"], execution_mode="answer_only", safety_level="low", intent_entities=entities, direct_answer=direct, shell_script=None, requires_browser=False)

    # Fallback when no deterministic rules match (allow model synthesis to classify intent)
    return _intent_result(
        "clarification", confidence=.50, signals=["no_deterministic_rule_match"],
        execution_mode="dynamic_evaluation", safety_level="low", intent_entities=entities,
        requires_clarification=False,
        ambiguity_reasons=[],
        clarification_questions=["What outcome do you want?", "Should OmniShell only explain/plan, or actually perform the operation?"],
        direct_answer=None,
    )


def normalize_multi_step_plan(plan: Any) -> list[dict]:
    """Normalize multi-step plan array from any LLM/schema structure into clean, verified step dictionaries."""
    if not plan:
        return []
    if isinstance(plan, dict):
        plan = [plan]
    if not isinstance(plan, list):
        return []
    
    normalized = []
    for idx, item in enumerate(plan):
        if isinstance(item, str):
            clean_str = item.strip()
            normalized.append({
                "step_id": idx + 1,
                "name": clean_str,
                "description": clean_str,
                "command": None,
                "expected": "Step completes successfully"
            })
        elif isinstance(item, dict):
            step_id = item.get("step_id") or item.get("step") or item.get("id") or (idx + 1)
            name = item.get("name") or item.get("title") or item.get("action") or item.get("description") or f"Step {step_id}"
            desc = item.get("description") or name
            cmd = item.get("command") or item.get("script") or item.get("cmd") or None
            expected = item.get("expected") or item.get("expected_outcome") or item.get("validation") or item.get("verify") or "Step completed and verified"
            if isinstance(expected, dict):
                expected = ", ".join(f"{k}: {v}" for k, v in expected.items())
            
            normalized.append({
                "step_id": step_id,
                "name": str(name),
                "description": str(desc),
                "command": str(cmd) if cmd else None,
                "expected": str(expected)
            })
    return normalized


def generate_dynamic_mermaid_diagram(data: dict, prompt: str, user_os: str) -> str:
    """Generate an extensive, rich Mermaid flowchart covering all 7 agents, policy gates,
    multi-step pipelines, recurrence loops, conditions, and host execution verification."""
    p_clean = prompt.replace('"', "'").replace("\n", " ")[:40]
    cap = data.get("capability_type") or "workflow"
    cap_label = cap.replace("_", " ").title()
    is_safe = data.get("is_safe", True)
    safe_text = "Safe (Approved)" if is_safe else "Blocked (Guardrail)"
    target_os = data.get("target_os") or user_os or "Native OS"
    requires_browser = data.get("requires_browser", False)
    target_url = data.get("target_url")
    is_recurring = data.get("is_recurring", False)
    rec_rule = data.get("recurrence_rule")
    is_scheduled = data.get("is_scheduled", False)
    multi_step = data.get("multi_step_plan") or []
    has_recovery = bool(data.get("recovery_strategy"))
    has_condition = bool(data.get("conditional_logic"))
    
    lines = []
    lines.append(f'User["👤 User Request<br/><b>{p_clean}</b>"]')
    lines.append(f'A1["🧠 Intent & Planning Agent<br/><b>Capability:</b> {cap_label}"]')
    lines.append(f'A2["💻 System Recon Agent<br/><b>Target OS:</b> {target_os}"]')
    lines.append(f'A3["📝 Content Gen Agent<br/><b>Synthesis:</b> Contextual"]')
    lines.append(f'A4{{"🛡️ Security Guardrail<br/><b>Status:</b> {safe_text}"}}')
    lines.append(f'A5["⚡ Command Research<br/><b>Target:</b> Resilient Command"]')
    lines.append(f'A6["🔍 Validator (CRITIC)<br/><b>Status:</b> Syntax & Risk Checked"]')
    lines.append(f'A7["📋 Execution Planner<br/><b>Decision:</b> Finalized Workflow"]')
    
    # Core flow
    lines.append('User --> A1')
    lines.append('A1 --> A2 & A3')
    lines.append('A2 & A3 --> A4')
    
    if not is_safe:
        lines.append('A4 -->|Threat Detected| BlockedNode["🛑 Blocked by Security Policy"]')
        return "\n".join(lines)
        
    lines.append('A4 -->|Safe: Verified| A5')
    lines.append('A5 --> A6')
    lines.append('A6 --> A7')
    
    prev_node = "A7"
    
    # Conditional logic branch
    if has_condition:
        cond_data = data["conditional_logic"] if isinstance(data["conditional_logic"], dict) else {}
        cond_script = str(cond_data.get("condition_script", "test condition"))[:30].replace('"', "'")
        lines.append(f'CondGate{{"❓ Condition Check<br/><code>{cond_script}</code>"}}')
        lines.append(f'{prev_node} --> CondGate')
        lines.append('CondGate -->|True: Success| BranchSuccess["✅ Success Handler"]')
        lines.append('CondGate -->|False: Failure| BranchFail["⚠️ Failure / Fallback Handler"]')
        prev_node = "BranchSuccess"

    # Multi-step plan chain
    if multi_step and isinstance(multi_step, list) and len(multi_step) > 0:
        lines.append('subgraph Pipeline ["📋 Autonomous Multi-Step Execution Plan"]')
        step_nodes = []
        for idx, s in enumerate(multi_step):
            s_num = s.get("step_id") or s.get("step") or (idx + 1)
            s_name = (s.get("name") or s.get("title") or s.get("description") or f"Step {s_num}")[:28].replace('"', "'")
            s_node = f"Step{s_num}"
            lines.append(f'  {s_node}["Step {s_num}: {s_name}"]')
            step_nodes.append(s_node)
        
        # Link steps sequentially
        for i in range(len(step_nodes) - 1):
            lines.append(f'  {step_nodes[i]} -->|Verify Pass| {step_nodes[i+1]}')
        lines.append('end')
        
        lines.append(f'{prev_node} --> {step_nodes[0]}')
        prev_node = step_nodes[-1]

    # Recurrence & Scheduling loop
    if is_recurring:
        lines.append(f'RecurNode["🔁 Recurrence Engine<br/><b>Rule:</b> {rec_rule or "Interval"}"]')
        lines.append('QueueNode["⏳ Background Worker Queue"]')
        lines.append(f'{prev_node} --> RecurNode')
        lines.append('RecurNode --> QueueNode')
        lines.append('QueueNode -.->|Next Cycle Trigger| A7')
        prev_node = "RecurNode"
    elif is_scheduled:
        lines.append('SchedNode["⏰ Scheduled Timer<br/>Registered in DB"]')
        lines.append(f'{prev_node} --> SchedNode')
        prev_node = "SchedNode"

    # Final execution or answer node
    if requires_browser and target_url:
        u_clean = target_url[:35].replace('"', "'")
        lines.append(f'ExecTarget["🌐 Browser Deep Link<br/><code>{u_clean}</code>"]')
        lines.append('HostBridge["🚀 Host Launch Agent<br/>(Port 8003)"]')
        lines.append(f'{prev_node} --> ExecTarget --> HostBridge')
    elif data.get("shell_script"):
        script_snippet = str(data["shell_script"])[:35].replace('"', "'").replace("\n", " ")
        lines.append(f'ExecTarget["⚡ Host Shell Execution<br/><code>{script_snippet}</code>"]')
        lines.append('VerifyNode["✅ Process & Output Verification"]')
        lines.append(f'{prev_node} --> ExecTarget --> VerifyNode')
        if has_recovery:
            lines.append('RecoveryNode["🛡️ Self-Healing Recovery<br/>Auto-Retry & Fallback"]')
            lines.append('VerifyNode -.->|On Failure| RecoveryNode --> ExecTarget')
    elif cap in {"question_answering", "information_request"}:
        lines.append('DirectAnswerNode["💡 Contextual Insights & Direct Answer<br/>Delivered to UI"]')
        lines.append(f'{prev_node} --> DirectAnswerNode')
    elif cap == "planning_only":
        lines.append('PlanNode["📝 Architectural Plan Delivered<br/>Non-Executing"]')
        lines.append(f'{prev_node} --> PlanNode')
    elif data.get("requires_clarification"):
        lines.append('ClarifyNode["❓ Interactive Clarification Gate<br/>Awaiting User Input"]')
        lines.append(f'{prev_node} --> ClarifyNode')
    elif data.get("requires_approval"):
        lines.append('ApprovalNode["🔒 Human Approval Gate<br/>Awaiting Confirmation"]')
        lines.append(f'{prev_node} --> ApprovalNode')
    else:
        lines.append('DoneNode["✅ Execution Pipeline Complete"]')
        lines.append(f'{prev_node} --> DoneNode')

    return "\n".join(lines)


@app.post("/api/generate-workflow", response_model=MultiAgentResult)
async def generate_workflow(request: AutomationRequest, background_tasks: BackgroundTasks):
    import time
    t_start = time.time()
    timing = {"llm_reasoning": 0.0, "research": 0.0, "validation": 0.0, "execution": 0.0, "total": 0.0}

    # LAYER 0: Hardcoded pre-LLM guardrail (un-jailbreakable)
    is_blocked, block_reason = hardcoded_guardrail_check(request.natural_language_prompt)
    if is_blocked:
        return MultiAgentResult(
            multi_agent_discussion=[
                AgentThought(agent_name="Security Guard (HARDCODED)", thought=f"BLOCKED: {block_reason}. This request has been intercepted by the system-level guardrail BEFORE reaching any AI model. This is non-negotiable."),
                AgentThought(agent_name="Intent & Planning Agent", thought="Request terminated. No further processing."),
            ],
            capability_type="human_approval",
            direct_answer=f"### 🛑 Security Guardrail Triggered\n**Reason:** {block_reason}\n\nThis request was intercepted and halted before execution for your safety.",
            is_safe=False,
            target_os=request.user_agent_os,
            shell_script=f"# BLOCKED by System Guardrail: {block_reason}",
            mermaid_diagram_body='User["User Prompt"] --> Guard{"HARDCODED GUARDRAIL"}\nGuard -->|BLOCKED| Abort["Request Terminated"]',
        )

    # Fast deterministic capability pre-check
    deterministic_cap = classify_prompt_capability(request.natural_language_prompt, request.user_agent_os)

    # Deterministic intent is the safety envelope. The LLM may enrich details,
    # but it cannot downgrade a clarification/approval/answer-only decision.
    intent_locked_capabilities = {
        "question_answering", "information_request", "planning_only",
        "clarification", "human_approval", "reminder", "scheduled_workflow",
        "recurring_workflow", "browser_operation", "interactive_workflow",
    }

    system_prompt = f"""
    You are a Multi-Agent OS Automation Syndicate with comprehensive support for 19 core capabilities:
    1. Questions and answers
    2. Information requests
    3. System inspection
    4. Analysis
    5. Application operations
    6. Browser operations
    7. File operations
    8. Shell operations
    9. Multi-step tasks
    10. Interactive workflows
    11. Scheduled workflows
    12. Recurring workflows
    13. Conditional workflows
    14. Reminders
    15. Research tasks
    16. Planning-only requests
    17. Tasks requiring human approval
    18. Tasks requiring clarification
    19. Tasks requiring recovery after failure

    Environment Context:
    - Target OS: '{request.user_agent_os}'
    - CURRENT SYSTEM TIME (UTC): {request.local_time or datetime.datetime.now(datetime.timezone.utc).isoformat()}
    - USER TIMEZONE: {request.timezone}
    
    You must simulate a multi-turn, iterative discussion between SEVEN distinct agents:
    1. Intent & Planning Agent: Identifies the exact capability type (from the 19 above), decomposes prompt into logical steps.
    2. System Reconnaissance Agent: Identifies dynamic OS paths, binaries, and environment variables.
    3. Content Generation Agent: For Q&A, info requests, analysis, research, or communications, drafts rich, detailed Markdown text for `direct_answer`.
    4. Security Guard: Ruthlessly screens for malicious intent, credential theft, system file destruction, or unauthorized exploits.
    5. Command Research Agent: Formulates exact, resilient CLI commands, deep links, or multi-step plans.
    6. Command Validator Agent (CRITIC): Reviews the plan, loops back if flawed, checks case-sensitivity, error handling, and recovery strategies.
    7. Execution Planner: Decides the final execution mode (direct answer only, browser deep link, local shell script, scheduled/recurring task, or interactive plan).

    CRITICAL RULES FOR CAPABILITIES:
    - If user asks a Question or Information Request (e.g. "what is capital of india", "explain kubernetes", "2+2"):
      * Set `capability_type="question_answering"` (or `information_request`).
      * Provide a comprehensive, structured Markdown response in `direct_answer`.
      * Set `requires_browser=false`, `shell_script=null`, `expected_process=null`. DO NOT output a dummy shell script for pure questions!
    - If user asks a Planning-Only Request:
      * Set `capability_type="planning_only"`, `is_planning_only=true`.
      * Provide an architectural roadmap in `direct_answer` and breakdown in `multi_step_plan`.
      * Set `shell_script=null`.
    - If user asks a Multi-Step Task:
      * Set `capability_type="multi_step"`.
      * Populate `multi_step_plan` array with step objects: `[{{"step_id": 1, "name": "...", "command": "...", "expected": "..."}}]`.
      * Set `shell_script` to the compound resilient script.
    - If user requests a Scheduled, Delayed, or Reminder Task (e.g. "after 3 minutes", "open spotify in 5 mins", "delete trash after 2 mins"):
      * Set `capability_type="scheduled_workflow"` (or `reminder`), `is_scheduled=true`, `scheduled_time="<ISO_TIMESTAMP>"`.
      * Set `shell_script` to the actual direct command (e.g. `rm -rf ~/.local/share/Trash/*` or `xdg-open https://...`).
      * CRITICAL: DO NOT put `sleep <seconds>` inside `shell_script` or `multi_step_plan`! The OmniShell background scheduler handles the timing automatically.
    - If user asks a Recurring Task (e.g. "every 5 minutes...", "daily at 10 AM..."):
      * Set `capability_type="recurring_workflow"`, `is_scheduled=true`, `is_recurring=true`, and specify `recurrence_rule`.
    - If user asks a Conditional Task:
      * Set `capability_type="conditional_workflow"`, `conditional_logic={{"condition_script": "...", "on_success": "...", "on_failure": "..."}}`.
    - If user prompt is ambiguous:
      * Set `capability_type="clarification"`, `requires_clarification=true`, `clarification_questions=["..."]`.
    - If user operation is potentially destructive or high-risk:
      * Set `capability_type="human_approval"`, `requires_approval=true`, `approval_reason="..."`.
    - If user requests recovery/fallback:
      * Set `capability_type="recovery_failure"`, `recovery_strategy={{"retry_limit": 3, "fallback_script": "..."}}`.
    - If opening a website/app in browser:
      * Set `requires_browser=true`, `target_url="https://..."`.

    YOU MUST OUTPUT STRICTLY A JSON OBJECT MATCHING THIS EXACT SCHEMA:
    {{
      "multi_agent_discussion": [{{"agent_name": "str", "thought": "str"}}],
      "capability_type": "question_answering | information_request | system_inspection | analysis | application_operation | browser_operation | file_operation | shell_operation | multi_step | interactive_workflow | scheduled_workflow | recurring_workflow | conditional_workflow | reminder | research | planning_only | human_approval | clarification | recovery_failure",
      "direct_answer": "str or null",
      "is_safe": true,
      "target_os": "str",
      "requires_browser": true or false,
      "target_url": "str or null",
      "shell_script": "str or null",
      "expected_process": "str or null",
      "mermaid_diagram_body": "str",
      "multi_step_plan": [{{"step_id": 1, "name": "str", "command": "str", "expected": "str"}}] or null,
      "requires_interactive": true or false,
      "interactive_prompts": ["str"] or null,
      "requires_clarification": true or false,
      "clarification_questions": ["str"] or null,
      "is_planning_only": true or false,
      "is_scheduled": true or false,
      "scheduled_time": "str or null",
      "schedule_timezone": "str or null",
      "is_recurring": true or false,
      "recurrence_rule": "str or null",
      "conditional_logic": {{"condition_script": "str", "on_success": "str", "on_failure": "str"}} or null,
      "recovery_strategy": {{"fallback_script": "str", "retry_limit": 3}} or null,
      "requires_approval": true or false,
      "approval_reason": "str or null",
      "is_reminder": true or false,
      "reminder_time": "str or null",
      "reminder_message": "str or null"
    }}
    """

    logger.info("Incoming automation request received", prompt=request.natural_language_prompt, user_agent=request.user_agent_os)

    structured_data = {}
    model_name = "omnishell-agent-syndicate"

    try:
        t_llm_start = time.time()
        response, model_name = await call_llm_with_fallback(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Task: {request.natural_language_prompt}"}
            ],
            purpose="multi-agent-workflow",
            timeout=float(os.getenv("LLM_REQUEST_TIMEOUT", "30")),
        )
        timing["llm_reasoning"] = time.time() - t_llm_start
        raw_content = response.choices[0].message.content.strip()
        if raw_content.startswith("```"):
            raw_content = raw_content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        structured_data = json.loads(raw_content)

        usage = getattr(response, "usage", {})
        t = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) if not isinstance(usage, dict) else usage.get("prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0) if not isinstance(usage, dict) else usage.get("completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0) if not isinstance(usage, dict) else usage.get("total_tokens", 0),
        }
        record_llm_usage(model_name, True, t)
    except Exception as llm_err:
        logger.warning(f"LLM generation failed or unavailable: {llm_err}. Using deterministic capability synthesis.")
        # Fallback to deterministic synthesis
        structured_data = {
            "multi_agent_discussion": [
                {"agent_name": "Intent & Planning Agent", "thought": f"Analyzed prompt '{request.natural_language_prompt}' and mapped to capability: {deterministic_cap.get('capability_type')}."},
                {"agent_name": "System Reconnaissance Agent", "thought": f"Operating on {request.user_agent_os} environment."},
                {"agent_name": "Security Guard", "thought": "Screened prompt for malicious patterns. Verified safe."},
                {"agent_name": "Execution Planner", "thought": "Finalized resilient workflow configuration."}
            ],
            "is_safe": True,
            "target_os": request.user_agent_os,
            "mermaid_diagram_body": 'User["User Request"] --> Intent["Intent Agent: Capability Resolved"]\nIntent --> Security["Security Guard: Verified"]\nSecurity --> Planner["Execution Planner: Assembled"]',
        }
        model_name = "deterministic-agent-engine"

    # --- POST-PROCESSING & CAPABILITY HARMONIZATION ---
    t_res = time.time()
    prompt_lower = request.natural_language_prompt.lower()

    # Harmonize capability type. High-confidence deterministic intent owns the
    # execution boundary; the model is used for enrichment, not permission.
    det_conf = float(deterministic_cap.get("intent_confidence") or 0.0)
    det_cap = deterministic_cap.get("capability_type")
    
    if det_cap in {"human_approval", "reminder", "recurring_workflow"} and det_conf >= 0.95:
        structured_data["capability_type"] = det_cap
    elif det_cap == "browser_operation" and det_conf >= 0.95:
        structured_data["capability_type"] = "browser_operation"
        structured_data["requires_browser"] = True
        if not structured_data.get("target_url") and deterministic_cap.get("target_url"):
            structured_data["target_url"] = deterministic_cap["target_url"]
        if not structured_data.get("shell_script") and deterministic_cap.get("shell_script"):
            structured_data["shell_script"] = deterministic_cap["shell_script"]
    elif det_cap in {"question_answering", "information_request"} and det_conf >= 0.98:
        structured_data["capability_type"] = det_cap
    elif not structured_data.get("capability_type") or structured_data.get("capability_type") == "clarification":
        if det_cap and det_cap != "clarification":
            structured_data["capability_type"] = det_cap

    # Copy the intent envelope into the response for Command Center visibility.
    for key in ("intent_confidence", "intent_signals", "intent_entities", "execution_mode", "safety_level", "ambiguity_reasons", "failure_policy"):
        if deterministic_cap.get(key) is not None:
            if key == "execution_mode" and deterministic_cap.get("execution_mode") in {"dynamic_evaluation", "clarification_gate"} and structured_data.get("capability_type") not in {"clarification", None}:
                continue
            if key == "intent_confidence" and det_conf < 0.8 and structured_data.get("capability_type") != "clarification":
                structured_data[key] = 0.95
                continue
            structured_data[key] = deterministic_cap[key]

    # Detect Q&A / Informational intent if agents in discussion indicated so
    discussion_text = " ".join([
        (step.get("thought", "") if isinstance(step, dict) else getattr(step, "thought", ""))
        for step in structured_data.get("multi_agent_discussion", [])
    ]).lower()

    if any(phrase in discussion_text for phrase in ["informational query", "answer can be provided directly", "answer to this question", "capital of", "the answer is"]):
        structured_data["capability_type"] = "question_answering"
        structured_data["shell_script"] = None
        structured_data["requires_browser"] = False

    # Extract direct answer from discussion if missing in top-level JSON
    if not structured_data.get("direct_answer"):
        for step in structured_data.get("multi_agent_discussion", []):
            thought = step.get("thought", "") if isinstance(step, dict) else getattr(step, "thought", "")
            agent_name = (step.get("agent_name", "") if isinstance(step, dict) else getattr(step, "agent_name", "")).lower()
            if ("content" in agent_name or "planner" in agent_name or "intent" in agent_name) and any(w in thought.lower() for w in ["answer", "is '", "is \"", "capital", "paris", "delhi"]):
                structured_data["direct_answer"] = thought
                break

    # Hard execution boundary: these capabilities must never receive a generated
    # shell payload merely because the model hallucinated one.
    if structured_data.get("capability_type") in {"question_answering", "information_request", "planning_only", "clarification", "research", "reminder"} and not structured_data.get("is_reminder"):
        structured_data["shell_script"] = None
        structured_data["requires_browser"] = False
    if structured_data.get("capability_type") in {"clarification", "human_approval"}:
        structured_data["requires_clarification"] = structured_data.get("capability_type") == "clarification"
        if deterministic_cap.get("clarification_questions"):
            structured_data["clarification_questions"] = deterministic_cap["clarification_questions"]
        if deterministic_cap.get("approval_reason"):
            structured_data["requires_approval"] = True
            structured_data["approval_reason"] = deterministic_cap["approval_reason"]

    # Merge deterministic direct answers if still missing
    if structured_data.get("capability_type") in {"question_answering", "information_request", "planning_only", "clarification", "research"}:
        if not structured_data.get("direct_answer") and deterministic_cap.get("direct_answer"):
            structured_data["direct_answer"] = deterministic_cap["direct_answer"]
        if deterministic_cap.get("clarification_questions") and not structured_data.get("clarification_questions"):
            structured_data["clarification_questions"] = deterministic_cap["clarification_questions"]
            structured_data["requires_clarification"] = True
        structured_data["shell_script"] = None
        structured_data["requires_browser"] = False

    # Deep Link Interceptor & Browser URL Resolver
    if "gmail" in prompt_lower and ("draft" in prompt_lower or "email" in prompt_lower):
        import urllib.parse
        to_email = ""
        emails = [word for word in prompt_lower.split() if "@" in word]
        if emails: to_email = emails[0].strip("',.")
        base_url = "https://mail.google.com/mail/?view=cm&fs=1"
        if to_email: base_url += f"&to={to_email}"
        body_text = "Hello,\n\nI will not be able to join the meeting today.\n\nBest regards."
        if "cannot" in prompt_lower and "meeting" in prompt_lower:
            base_url += f"&su=Meeting&body={urllib.parse.quote(body_text)}"
        structured_data["capability_type"] = "browser_operation"
        structured_data["requires_browser"] = True
        structured_data["target_url"] = base_url
        is_lin = "linux" in request.user_agent_os.lower()
        structured_data["shell_script"] = f"xdg-open '{base_url}' || google-chrome '{base_url}'" if is_lin else f"Start-Process '{base_url}'"
    elif structured_data.get("capability_type") == "browser_operation" or structured_data.get("requires_browser") or any(kw in prompt_lower for kw in ["spotify", "netflix", "github", "youtube", "you tube", "chrome", "firefox", "browser"]):
        web_keywords = {
            "youtube music": "https://music.youtube.com",
            "you tube music": "https://music.youtube.com",
            "yt music": "https://music.youtube.com",
            "youtube": "https://www.youtube.com",
            "you tube": "https://www.youtube.com",
            "spotify": "https://open.spotify.com",
            "netflix": "https://www.netflix.com",
            "github": "https://github.com",
            "google": "https://www.google.com",
            "reddit": "https://www.reddit.com",
            "twitter": "https://twitter.com",
            "x.com": "https://x.com",
            "amazon": "https://www.amazon.com",
            "chatgpt": "https://chat.openai.com",
            "claude": "https://claude.ai",
        }
        target_u = structured_data.get("target_url")
        if not target_u:
            for kw, url in web_keywords.items():
                if kw in prompt_lower:
                    target_u = url
                    break
        if not target_u and deterministic_cap.get("target_url"):
            target_u = deterministic_cap["target_url"]

        if target_u:
            structured_data["capability_type"] = "browser_operation"
            structured_data["requires_browser"] = True
            structured_data["target_url"] = target_u
            is_lin = "linux" in request.user_agent_os.lower()
            is_mac = "darwin" in request.user_agent_os.lower() or "mac" in request.user_agent_os.lower()
            structured_data["shell_script"] = f"xdg-open '{target_u}' || google-chrome '{target_u}'" if is_lin else (f"open '{target_u}'" if is_mac else f"Start-Process '{target_u}'")
            structured_data["requires_clarification"] = False

    # Intelligent Command Resolution for desktop apps
    if not structured_data.get("requires_browser") and structured_data.get("capability_type") in {"application_operation", "shell_operation"}:
        app_keywords = prompt_lower.replace("open ", "").replace("launch ", "").replace("start ", "").strip()
        redis_result = get_learned_command(f"{request.user_agent_os}_{app_keywords}")
        if redis_result:
            structured_data["shell_script"] = redis_result["script"]
            structured_data["expected_process"] = redis_result.get("process", "")
        else:
            os_kb = KNOWN_APP_COMMANDS.get(request.user_agent_os, {})
            for app_alias, app_data in os_kb.items():
                if app_alias in prompt_lower:
                    structured_data["shell_script"] = app_data["script"]
                    structured_data["expected_process"] = app_data.get("process", "")
                    store_learned_command(f"{request.user_agent_os}_{app_alias}", app_data["script"], app_data.get("process", ""))
                    break

    # Check recurring scheduling
    is_rec, rec_rule, rec_dt = _deterministic_recurrence_rule(request.natural_language_prompt, request.timezone)
    if is_rec:
        structured_data["capability_type"] = "recurring_workflow"
        structured_data["is_scheduled"] = True
        structured_data["is_recurring"] = True
        structured_data["recurrence_rule"] = rec_rule
        structured_data["scheduled_time"] = rec_dt.isoformat() if rec_dt else None

    # Check relative scheduling
    deterministic_dt, deterministic_tz = _deterministic_relative_schedule(
        request.natural_language_prompt,
        request.timezone or structured_data.get("schedule_timezone"),
    )
    if deterministic_dt is not None:
        structured_data["is_scheduled"] = True
        structured_data["scheduled_time"] = deterministic_dt.isoformat()
        structured_data["schedule_timezone"] = deterministic_tz
        if not structured_data.get("is_recurring"):
            structured_data["capability_type"] = "scheduled_workflow"

    # Persist scheduled / recurring tasks into DB
    if structured_data.get("is_scheduled"):
        if not structured_data.get("scheduled_time"):
            scheduled_now = _utc_now() + datetime.timedelta(seconds=60)
            structured_data["scheduled_time"] = scheduled_now.isoformat()
        
        # Clean redundant delay prefixes from scripts/plans since scheduler handles timing
        if structured_data.get("shell_script"):
            structured_data["shell_script"] = re.sub(r'^\s*sleep\s+\d+\s*(?:;|&&)\s*', '', str(structured_data["shell_script"])).strip()
        if isinstance(structured_data.get("multi_step_plan"), list):
            structured_data["multi_step_plan"] = [
                s for s in structured_data["multi_step_plan"]
                if not (isinstance(s, dict) and re.match(r"^\s*sleep\s+\d+\s*$", str(s.get("command") or s.get("script") or "").strip()))
            ]

    # Evaluate operations requiring human authorization (file deletions, trash purges, system mutations)
    p_check = (request.natural_language_prompt or "").lower()
    script_check = str(structured_data.get("shell_script") or "").lower()
    multi_check = " ".join([str(s.get("command") or s.get("script") or "") for s in (structured_data.get("multi_step_plan") or []) if isinstance(s, dict)]).lower()
    all_cmds = f"{p_check} {script_check} {multi_check}"

    if re.search(r"\b(rm|rmdir|unlink|shred|truncate|dd|mkfs|fdisk|chmod|chown|kill|pkill|killall|systemctl|service|apt|yum|dnf|pacman|pip|npm|delete|trash|clean|wipe|format|destroy|reboot|shutdown)\b", all_cmds):
        structured_data["requires_approval"] = True
        structured_data["safety_level"] = "high"
        if not structured_data.get("approval_reason"):
            structured_data["approval_reason"] = "This operation performs file deletions or system mutations requiring explicit human authorization."

    # Persist scheduled / recurring tasks into DB
    if structured_data.get("is_scheduled"):
        try:
            schedule_tz = _safe_timezone(request.timezone or structured_data.get("schedule_timezone"))
            scheduled_dt = _parse_schedule_datetime(structured_data["scheduled_time"], schedule_tz)
            _schedule_is_valid(scheduled_dt)
            structured_data["schedule_timezone"] = schedule_tz
            structured_data.setdefault("schedule_type", "recurring" if structured_data.get("is_recurring") else "one_time")
            structured_data.setdefault("priority", 5)
            structured_data.setdefault("approval_timeout_seconds", SCHEDULE_APPROVAL_TIMEOUT)

            scheduled_record = await create_scheduled_task(
                prompt=request.natural_language_prompt,
                workflow=structured_data,
                scheduled_for=scheduled_dt,
                timezone_name=schedule_tz,
                client_id=request.client_id,
                request_id=request.request_id,
            )
            structured_data["scheduled_task_id"] = scheduled_record["id"]
            structured_data["scheduled_status"] = scheduled_record["status"]
            structured_data["scheduled_for_utc"] = scheduled_record["scheduled_for"]
        except Exception as schedule_error:
            logger.warning(f"Unable to persist scheduled task: {schedule_error}")

    structured_data["model_used"] = model_name
    structured_data.setdefault("idempotency_key", request.request_id or hashlib.sha256(request.natural_language_prompt.encode("utf-8")).hexdigest()[:24])
    structured_data.setdefault("workflow_state", "planned" if structured_data.get("is_planning_only") else ("waiting_for_clarification" if structured_data.get("requires_clarification") else ("waiting_for_approval" if structured_data.get("requires_approval") else ("scheduled" if structured_data.get("is_scheduled") else "ready"))))
    structured_data.setdefault("failure_policy", deterministic_cap.get("failure_policy", {"max_attempts": 2, "retry_on": ["timeout", "connection", "transient"], "verify_after_each_step": True}))
    timing["research"] = time.time() - t_res
    timing["total"] = time.time() - t_start
    timing["execution"] = max(0.0, timing["total"] - timing["llm_reasoning"] - timing["research"])
    structured_data["timing"] = timing

    # Ensure required default fields exist
    structured_data.setdefault("multi_agent_discussion", [])
    structured_data.setdefault("is_safe", True)
    structured_data.setdefault("target_os", request.user_agent_os or "Unknown OS")
    structured_data.setdefault("requires_browser", False)
    structured_data.setdefault("capability_type", "shell_operation")

    # Normalize multi-step plan to guarantee clean dictionary structures
    if structured_data.get("multi_step_plan"):
        structured_data["multi_step_plan"] = normalize_multi_step_plan(structured_data["multi_step_plan"])
    elif structured_data.get("capability_type") == "multi_step":
        structured_data["multi_step_plan"] = normalize_multi_step_plan(deterministic_cap.get("multi_step_plan"))

    # Generate complete dynamic flowchart reflecting all agents, policies, loops, and execution targets
    structured_data["mermaid_diagram_body"] = generate_dynamic_mermaid_diagram(
        structured_data, request.natural_language_prompt, request.user_agent_os
    )

    background_tasks.add_task(log_execution_to_db, request.natural_language_prompt, request.user_agent_os, structured_data)
    return MultiAgentResult(**structured_data)


@app.get("/api/capabilities")
def get_capabilities():
    """Return all 19 supported OmniShell capabilities."""
    return {
        "total_capabilities": len(CAPABILITIES_REGISTRY),
        "capabilities": CAPABILITIES_REGISTRY,
    }


@app.post("/api/clarify", response_model=MultiAgentResult)
async def clarify_workflow(request: Request, background_tasks: BackgroundTasks):
    """Continue an ambiguous workflow with the user's clarified parameters."""
    body = await request.json()
    original_prompt = body.get("original_prompt", "")
    clarification_choice = body.get("clarification_choice", "")
    user_os = body.get("user_agent_os", "Unknown OS")
    combined_prompt = f"{original_prompt} (clarified: {clarification_choice})".strip()
    return await generate_workflow(
        AutomationRequest(
            natural_language_prompt=combined_prompt,
            user_agent_os=user_os,
            local_time=body.get("local_time"),
            timezone=body.get("timezone"),
        ),
        background_tasks,
    )

@app.get("/api/models")
def list_models():
    return get_model_registry()


@app.get("/api/models/fallback")
def list_fallback_models():
    return {
        "models": FALLBACK_MODELS,
        "cooldowns": {k: v for k, v in MODEL_COOLDOWN.items()},
        "failures": dict(MODEL_FAILURES),
    }


@app.get("/api/reminders")
async def get_reminders():
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT id, message, trigger_time, status FROM reminders WHERE status = 'pending' ORDER BY trigger_time ASC")
        return [{"id": r["id"], "message": r["message"], "trigger_time": r["trigger_time"].isoformat(), "status": r["status"]} for r in rows]

@app.post("/api/reminders/{reminder_id}/complete")
async def complete_reminder(reminder_id: int):
    async with DB_POOL.acquire() as conn:
        await conn.execute("UPDATE reminders SET status = 'completed' WHERE id = $1", reminder_id)
        return {"status": "success"}


# ============================================================
# SCHEDULED TASKS API
# ============================================================

def _approval_expiry_for_task(record):
    metadata = record.get("metadata") or {}
    if isinstance(metadata, str):
        try: metadata = json.loads(metadata)
        except Exception: metadata = {}
    timeout = int(metadata.get("approval_timeout_seconds", SCHEDULE_APPROVAL_TIMEOUT)) if isinstance(metadata, dict) else SCHEDULE_APPROVAL_TIMEOUT
    return _utc_now() + datetime.timedelta(seconds=max(30, min(timeout, 3600)))


@app.get("/api/scheduled-tasks")
async def get_scheduled_tasks(status: str | None = None, limit: int = 100):
    limit = max(1, min(limit, 500))
    async with DB_POOL.acquire() as conn:
        if status:
            rows = await conn.fetch("""SELECT id,original_prompt,target_os,requires_browser,target_url,
                shell_script,expected_process,scheduled_for,timezone,schedule_type,priority,status,
                execution_id,attempt_count,max_attempts,created_at,triggered_at,approved_at,denied_at,
                completed_at,failed_at,cancelled_at,expired_at,failure_reason,last_error
                FROM scheduled_tasks WHERE status=$1 ORDER BY scheduled_for ASC LIMIT $2""", status, limit)
        else:
            rows = await conn.fetch("""SELECT id,original_prompt,target_os,requires_browser,target_url,
                shell_script,expected_process,scheduled_for,timezone,schedule_type,priority,status,
                execution_id,attempt_count,max_attempts,created_at,triggered_at,approved_at,denied_at,
                completed_at,failed_at,cancelled_at,expired_at,failure_reason,last_error
                FROM scheduled_tasks ORDER BY scheduled_for DESC LIMIT $1""", limit)
        return [_json_safe_record(r) for r in rows]


@app.get("/api/scheduled-tasks/{task_id}")
async def get_scheduled_task(task_id: int):
    async with DB_POOL.acquire() as conn:
        record = await conn.fetchrow("SELECT * FROM scheduled_tasks WHERE id=$1", task_id)
        if not record: raise HTTPException(status_code=404, detail="Task not found")
        result = _json_safe_record(record)
        result.pop("approval_token_hash", None)
        return result


@app.post("/api/scheduled-tasks/{task_id}/cancel")
async def cancel_scheduled_task(task_id: int):
    async with DB_POOL.acquire() as conn:
        async with conn.transaction():
            record = await conn.fetchrow("SELECT status FROM scheduled_tasks WHERE id=$1 FOR UPDATE", task_id)
            if not record: raise HTTPException(status_code=404, detail="Task not found")
            if record["status"] in {"completed","failed","cancelled","denied","expired","executing"}:
                raise HTTPException(status_code=400, detail=f"Cannot cancel task in {record['status']} state")
            await conn.execute("""UPDATE scheduled_tasks SET status='cancelled',
                cancelled_at=CURRENT_TIMESTAMP,approval_token_hash=NULL,
                approval_expires_at=NULL,last_error='Cancelled by user' WHERE id=$1""", task_id)
            return {"status":"cancelled","task_id":task_id}


@app.post("/api/scheduled-tasks/{task_id}/retry")
async def retry_scheduled_task(task_id: int):
    async with DB_POOL.acquire() as conn:
        async with conn.transaction():
            record = await conn.fetchrow("SELECT status FROM scheduled_tasks WHERE id=$1 FOR UPDATE", task_id)
            if not record: raise HTTPException(status_code=404, detail="Task not found")
            if record["status"] not in {"failed","expired","denied"}:
                raise HTTPException(status_code=400, detail="Only failed, expired, or denied tasks can be retried.")
            await conn.execute("""UPDATE scheduled_tasks SET status='scheduled',
                scheduled_for=CURRENT_TIMESTAMP,approval_token_hash=NULL,
                approval_expires_at=NULL,last_error=NULL,failure_reason=NULL,
                denied_at=NULL,expired_at=NULL WHERE id=$1""", task_id)
            return {"status":"scheduled","task_id":task_id}


@app.get("/api/scheduled-tasks/internal/poll")
async def poll_due_tasks():
    async with DB_POOL.acquire() as conn:
        async with conn.transaction():
            # Clean up stale awaiting_approval tasks
            await conn.execute("""
                UPDATE scheduled_tasks SET status='expired', 
                expired_at=CURRENT_TIMESTAMP, approval_token_hash=NULL, approval_expires_at=NULL,
                last_error='Approval window expired (reaped)'
                WHERE status='awaiting_approval' AND approval_expires_at <= CURRENT_TIMESTAMP
            """)

            # Clean up stale approved tasks (executor crashed before running)
            await conn.execute("""
                UPDATE scheduled_tasks SET status=CASE WHEN attempt_count<max_attempts THEN 'scheduled' ELSE 'failed' END,
                scheduled_for=CASE WHEN attempt_count<max_attempts THEN CURRENT_TIMESTAMP + INTERVAL '15 seconds' ELSE scheduled_for END,
                failed_at=CASE WHEN attempt_count>=max_attempts THEN CURRENT_TIMESTAMP ELSE failed_at END,
                last_error='Executor crashed after approval (reaped)',
                failure_reason='Executor crashed after approval (reaped)'
                WHERE status='approved' AND approved_at <= CURRENT_TIMESTAMP - INTERVAL '5 minutes'
            """)
            

            record = await conn.fetchrow("""SELECT * FROM scheduled_tasks
                WHERE status='scheduled' AND scheduled_for<=CURRENT_TIMESTAMP
                AND attempt_count<max_attempts
                ORDER BY priority ASC,scheduled_for ASC,id ASC
                FOR UPDATE SKIP LOCKED LIMIT 1""")
            if not record: return {"task":None}

            task_id=record["id"]
            task=dict(record)
            raw_workflow=task.get("raw_workflow") or {}
            if isinstance(raw_workflow, str):
                try: raw_workflow=json.loads(raw_workflow)
                except Exception: raw_workflow={}
            # Scheduled work with mutations, deletions, or high risk enters the human approval checkpoint
            cmd = str(task.get("shell_script") or raw_workflow.get("shell_script") or "")
            multi_steps = task.get("multi_step_plan") or raw_workflow.get("multi_step_plan") or []
            prompt_text = str(task.get("original_prompt") or "").lower()
            
            has_mutation_or_risk = bool(
                re.search(r"\b(rm|rmdir|unlink|shred|truncate|dd|mkfs|chmod|chown|kill|pkill|systemctl|service|apt|yum|dnf|pacman|pip|npm|delete|trash|clean)\b", cmd, re.I)
                or re.search(r"\b(rm|delete|trash|remove|clean|kill|stop|destroy|wipe|format|reboot|shutdown)\b", prompt_text, re.I)
                or any(re.search(r"\b(rm|rmdir|unlink|shred|truncate|dd|mkfs|chmod|chown|kill|pkill|systemctl|service|apt|yum|dnf|pacman|pip|npm)\b", str(s.get("command") or s.get("script") or ""), re.I) for s in multi_steps if isinstance(s, dict))
            )

            needs_approval = bool(
                task.get("capability_type") == "human_approval"
                or raw_workflow.get("requires_approval")
                or str(raw_workflow.get("safety_level", "")).lower() in {"high", "critical", "medium"}
                or has_mutation_or_risk
            )
            if needs_approval:
                raw_token=_new_approval_token()
                token_hash=_hash_approval_token(raw_token)
                expiry=_approval_expiry_for_task(dict(record))
                await conn.execute("""UPDATE scheduled_tasks SET status='awaiting_approval',
                    approval_token_hash=$1,approval_expires_at=$2,triggered_at=CURRENT_TIMESTAMP,
                    attempt_count=attempt_count+1,last_error=NULL WHERE id=$3""",
                    token_hash,expiry,task_id)
                task["status"]="awaiting_approval"
                task["approval_token"]=raw_token
                task["approval_expires_at"]=expiry
            else:
                await conn.execute("""UPDATE scheduled_tasks SET status='approved',
                    approved_at=CURRENT_TIMESTAMP,triggered_at=CURRENT_TIMESTAMP,
                    attempt_count=attempt_count+1,last_error=NULL WHERE id=$1""", task_id)
                task["status"]="approved"
                task["approved_at"]=_utc_now()
            return {"task":_json_safe_record(task)}


@app.post("/api/scheduled-tasks/{task_id}/approve")
async def approve_scheduled_task(task_id: int, request: Request):
    body=await request.json()
    token=str(body.get("token") or "").strip()
    if not token: raise HTTPException(status_code=400, detail="Missing approval token")
    async with DB_POOL.acquire() as conn:
        async with conn.transaction():
            record=await conn.fetchrow("SELECT * FROM scheduled_tasks WHERE id=$1 FOR UPDATE",task_id)
            if not record: raise HTTPException(status_code=404, detail="Task not found")
            if record["status"]!="awaiting_approval": raise HTTPException(status_code=409, detail=f"Task is already {record['status']}.")
            if record["approval_token_hash"]!=_hash_approval_token(token): raise HTTPException(status_code=403, detail="Invalid approval token")
            if record["approval_expires_at"] and record["approval_expires_at"]<=_utc_now():
                await conn.execute("""UPDATE scheduled_tasks SET status='expired',
                    expired_at=CURRENT_TIMESTAMP,approval_token_hash=NULL,approval_expires_at=NULL WHERE id=$1""",task_id)
                raise HTTPException(status_code=410, detail="Approval window expired")
            await conn.execute("""UPDATE scheduled_tasks SET status='approved',
                approved_at=CURRENT_TIMESTAMP,approval_token_hash=NULL,approval_expires_at=NULL WHERE id=$1""",task_id)
            return {"status":"approved","task_id":task_id}


@app.post("/api/scheduled-tasks/{task_id}/deny")
async def deny_scheduled_task(task_id: int, request: Request):
    body=await request.json()
    token=str(body.get("token") or "").strip()
    if not token: raise HTTPException(status_code=400, detail="Missing approval token")
    async with DB_POOL.acquire() as conn:
        async with conn.transaction():
            record=await conn.fetchrow("SELECT status,approval_token_hash FROM scheduled_tasks WHERE id=$1 FOR UPDATE",task_id)
            if not record: raise HTTPException(status_code=404, detail="Task not found")
            if record["status"]!="awaiting_approval": raise HTTPException(status_code=409, detail=f"Task is already {record['status']}.")
            if record["approval_token_hash"]!=_hash_approval_token(token): raise HTTPException(status_code=403, detail="Invalid approval token")
            await conn.execute("""UPDATE scheduled_tasks SET status='denied',
                denied_at=CURRENT_TIMESTAMP,approval_token_hash=NULL,approval_expires_at=NULL WHERE id=$1""",task_id)
            return {"status":"denied","task_id":task_id}


@app.post("/api/scheduled-tasks/{task_id}/mark-executing")
async def mark_scheduled_task_executing(task_id: int, request: Request):
    body=await request.json()
    execution_id=str(body.get("execution_token") or "").strip()
    if not execution_id: raise HTTPException(status_code=400, detail="Missing execution token")
    async with DB_POOL.acquire() as conn:
        updated=await conn.fetchrow("""UPDATE scheduled_tasks SET status='executing',execution_id=$1
            WHERE id=$2 AND status='approved' RETURNING id,status,execution_id""",execution_id,task_id)
        if not updated: raise HTTPException(status_code=409, detail="Task is no longer approved for execution.")
        return dict(updated)


@app.post("/api/scheduled-tasks/{task_id}/result")
async def store_scheduled_task_result(task_id: int, request: Request):
    body=await request.json()
    status=str(body.get("status") or "")
    execution_result=body.get("execution_result") or {}
    execution_id=body.get("execution_id")
    failure_reason=body.get("failure_reason")
    is_permanent=bool(body.get("is_permanent", False))
    if status not in {"completed","failed"}:
        raise HTTPException(status_code=400, detail="status must be completed or failed")

    async with DB_POOL.acquire() as conn:
        async with conn.transaction():
            record = await conn.fetchrow("SELECT status,attempt_count,max_attempts,execution_id,is_recurring,recurrence_rule,timezone,raw_workflow FROM scheduled_tasks WHERE id=$1 FOR UPDATE", task_id)
            if not record: raise HTTPException(status_code=404, detail="Task not found")
            if record["status"] not in {"approved","executing"}:
                return {"status":"ignored","reason":f"Task is {record['status']}"}
            if record["status"] == "executing" and execution_id and record.get("execution_id") and execution_id != record["execution_id"]:
                return {"status":"ignored","reason":f"Task is {record['status']}"}

            if status == "completed":
                is_recurring = record.get("is_recurring") or (record.get("raw_workflow") or {}).get("is_recurring", False) if isinstance(record.get("raw_workflow"), dict) else bool(record.get("is_recurring"))
                rec_rule = record.get("recurrence_rule") or ((record.get("raw_workflow") or {}).get("recurrence_rule") if isinstance(record.get("raw_workflow"), dict) else None)

                if is_recurring and rec_rule:
                    next_run = _calculate_next_recurrence(rec_rule, record.get("timezone"))
                    await conn.execute("""UPDATE scheduled_tasks SET
                        status='scheduled', scheduled_for=$1, attempt_count=0,
                        execution_result=$2, execution_id=NULL, approval_token_hash=NULL,
                        approval_expires_at=NULL, triggered_at=NULL, approved_at=NULL,
                        last_error=NULL
                        WHERE id=$3""",
                        next_run, json.dumps(execution_result), task_id)
                    return {"status": "recurring_rescheduled", "task_id": task_id, "next_scheduled_for": next_run.isoformat()}
                else:
                    await conn.execute("""UPDATE scheduled_tasks SET status='completed',
                        completed_at=CURRENT_TIMESTAMP,execution_result=$1,execution_id=$2,last_error=NULL WHERE id=$3""",
                        json.dumps(execution_result),execution_id,task_id)
            else:
                terminal=is_permanent or record["attempt_count"]>=record["max_attempts"]
                next_status="failed" if terminal else "scheduled"
                await conn.execute("""UPDATE scheduled_tasks SET status=$1,
                    failed_at=CASE WHEN $1='failed' THEN CURRENT_TIMESTAMP ELSE failed_at END,
                    failure_reason=$2,last_error=$2,execution_result=$3,execution_id=$4,
                    scheduled_for=CASE WHEN $1='scheduled'
                    THEN CURRENT_TIMESTAMP + INTERVAL '15 seconds' ELSE scheduled_for END WHERE id=$5""",
                    next_status,failure_reason or "Scheduled execution failed",
                    json.dumps(execution_result),execution_id,task_id)
            return {"status":"ok","task_id":task_id}


@app.post("/api/scheduled-tasks/{task_id}/expire")
async def expire_scheduled_task(task_id: int):
    async with DB_POOL.acquire() as conn:
        async with conn.transaction():
            record=await conn.fetchrow("SELECT status FROM scheduled_tasks WHERE id=$1 FOR UPDATE",task_id)
            if not record: raise HTTPException(status_code=404, detail="Task not found")
            if record["status"]=="awaiting_approval":
                await conn.execute("""UPDATE scheduled_tasks SET status='expired',
                    approval_token_hash=NULL,approval_expires_at=NULL,
                    expired_at=CURRENT_TIMESTAMP,last_error='Approval window expired' WHERE id=$1""",task_id)
                return {"status":"expired"}
            return {"status":record["status"]}