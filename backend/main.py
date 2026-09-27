import os
import json
import datetime
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import litellm
import redis
import asyncpg

from tracenest.logger import Logger
from tracenest.fastapi.middleware import TraceNestMiddleware
from tracenest.ui.router import router as tracenest_router

logger = Logger()

# Map KIMI_API_KEY to MOONSHOT_API_KEY for litellm compatibility
if os.getenv("KIMI_API_KEY") and not os.getenv("MOONSHOT_API_KEY"):
    os.environ["MOONSHOT_API_KEY"] = os.getenv("KIMI_API_KEY")

app = FastAPI(title="Multi-Agent OS Automation API")

app.add_middleware(TraceNestMiddleware)
app.include_router(tracenest_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AutomationRequest(BaseModel):
    natural_language_prompt: str
    user_agent_os: str
    user_agent_os: str = "Unknown OS"
    local_time: str | None = None

class AgentThought(BaseModel):
    agent_name: str = Field(description="Name of the agent (e.g., 'OS Analyzer', 'Security Guard', 'Execution Planner')")
    thought: str = Field(description="The internal reasoning and decision making of this agent")

class MultiAgentResult(BaseModel):
    multi_agent_discussion: list[AgentThought] = Field(default_factory=list, description="The step-by-step discussion between the agents.")
    is_safe: bool = Field(default=True, description="True if safe, False if malicious (formatting, viruses).")
    target_os: str = Field(default="", description="The detected OS (Windows, Linux, macOS, Android, iOS).")
    requires_browser: bool = Field(default=False, description="Set to True ONLY if the user is asking to open a website, url, or web service (like Netflix, GitHub).")
    target_url: str | None = Field(default=None, description="The full URL to open (e.g., 'https://www.netflix.com'). Required if requires_browser is True.")
    shell_script: str | None = Field(default=None, description="Robust script to execute. Only used if requires_browser is False. E.g., Start-Process 'code'")
    expected_process: str | None = Field(default=None, description="The name of the executable process that should be running after execution.")
    mermaid_diagram_body: str = Field(default="", description="ONLY the body of the flowchart.")
    model_used: str | None = Field(default=None)
    is_reminder: bool = Field(default=False, description="Set to True if this is a scheduling or reminder task.")
    reminder_time: str | None = Field(default=None, description="ISO 8601 future time for the reminder.")
    reminder_message: str | None = Field(default=None, description="The message for the reminder.")

# Fallback Models (Smartest 70B+ models first to ensure strict prompt adherence)
FALLBACK_MODELS = []
if os.getenv("OPENROUTER_API_KEY"):
    FALLBACK_MODELS.extend([
        "openrouter/meta-llama/llama-3.3-70b-instruct",
        "openrouter/qwen/qwen-2.5-72b-instruct",
        "openrouter/meta-llama/llama-3.1-8b-instruct",
        "openrouter/mistralai/mistral-nemo",
        "openrouter/deepseek/deepseek-chat"
    ])
if os.getenv("GROQ_API_KEY"):
    FALLBACK_MODELS.extend([
        "groq/llama3-8b-8192",
        "groq/llama3-70b-8192",
        "groq/mixtral-8x7b-32768"
    ])
if os.getenv("GEMINI_API_KEY"):
    FALLBACK_MODELS.extend([
        "gemini/gemini-1.5-flash",
        "gemini/gemini-1.5-pro",
        "gemini/gemini-pro",
        "gemini/gemini-1.0-pro"
    ])

if not FALLBACK_MODELS:
    # If no keys are found, inject a massive array of 16+ free models in hopes one is cached or allowed
    FALLBACK_MODELS = [
        "openrouter/google/gemini-2.0-flash-exp:free",
        "openrouter/google/gemini-2.0-flash-thinking-exp:free",
        "openrouter/meta-llama/llama-3.3-70b-instruct:free",
        "openrouter/nvidia/llama-3.1-nemotron-70b-instruct:free",
        "openrouter/qwen/qwen-2.5-72b-instruct:free",
        "openrouter/google/gemma-2-27b-it:free",
        "openrouter/google/gemma-2-9b-it:free",
        "openrouter/meta-llama/llama-3.1-8b-instruct:free",
        "openrouter/meta-llama/llama-3.2-3b-instruct:free",
        "openrouter/meta-llama/llama-3.2-1b-instruct:free",
        "openrouter/mistralai/mistral-nemo:free",
        "openrouter/mistralai/mistral-7b-instruct:free",
        "openrouter/microsoft/phi-3-medium-128k-instruct:free",
        "openrouter/microsoft/phi-3-mini-128k-instruct:free",
        "openrouter/deepseek/deepseek-chat:free",
        "openrouter/cognitivecomputations/dolphin-3.0-r1-mistral-24b:free"
    ]

# --- LEARNED APP KNOWLEDGE BASE ---
# This dictionary is the system's "memory" of correct commands.
# When the LLM hallucinates wrong scripts, the middleware below overrides them.
# Future: This will be backed by Redis/PostgreSQL for dynamic learning.
KNOWN_APP_COMMANDS = {
    # App aliases -> { "script": correct command, "process": expected process name }
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
    "git bash": {"script": 'Start-Process "C:\\Program Files\\Git\\git-bash.exe"', "process": "git-bash.exe"},
    "terminal": {"script": "wt", "process": "WindowsTerminal.exe"},
    "powershell": {"script": "powershell", "process": "powershell.exe"},
    "word": {"script": "winword", "process": "WINWORD.EXE"},
    "excel": {"script": "excel", "process": "EXCEL.EXE"},
    "powerpoint": {"script": "powerpnt", "process": "POWERPNT.EXE"},
    "cmd": {"script": "cmd", "process": "cmd.exe"},
    "snipping tool": {"script": "snippingtool", "process": "SnippingTool.exe"},
    "settings": {"script": "start ms-settings:", "process": "SystemSettings.exe"},
    "spotify": {"script": "Start-Process 'spotify:'", "process": "Spotify.exe"},
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
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                message TEXT NOT NULL,
                trigger_time TIMESTAMP NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

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

        extract_response = await litellm.acompletion(
            model="openrouter/google/gemini-2.0-flash-exp:free",
            messages=[
                {"role": "system", "content": "You extract CLI commands from search results. Return ONLY raw JSON."},
                {"role": "user", "content": extraction_prompt}
            ],
            timeout=10.0
        )
        
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
def get_analytics():
    if not redis_client:
        return {"data": [], "fallback_flow": FALLBACK_MODELS}
    records = redis_client.lrange("llm_analytics", 0, -1)
    data = []
    for r in records:
        try:
            data.append(json.loads(r))
        except:
            pass
    return {"data": data, "fallback_flow": FALLBACK_MODELS}

@app.post("/api/generate-workflow"
, response_model=MultiAgentResult)
async def generate_workflow(request: AutomationRequest):
    system_prompt = f"""
    You are a Multi-Agent OS Automation Syndicate. 
    You are receiving a request from a user on the following OS environment: '{request.user_agent_os}'.
    
    CURRENT SYSTEM TIME: {request.local_time or datetime.datetime.now().isoformat()}
    
    You must simulate a highly advanced discussion between SIX distinct agents:
    1. Intent & Planning Agent: Breaks down the plain English prompt into logical, multi-step execution sequences.
    2. System Reconnaissance Agent: Thinks about how to dynamically discover the correct application or path on the user's specific OS to prevent hallucinating hardcoded paths.
    3. Content Generation Agent: If the user provides rough instructions for an email, message, or search, this agent expands it into a fully professional, context-aware text body, and URL-encodes it so it can be passed into deep links.
    4. Security Guard: Strictly checks for malicious intent (formatting disks, viruses) AND enforces operational constraints (e.g., if the user asks to SEND an email, the Guard MUST downgrade it to DRAFT ONLY).
    5. Command Research Agent: Verifies the exact, flawless CLI command for the target OS (e.g. knowing that Ubuntu uses gnome-text-editor now instead of gedit, and that emptying trash on Linux is `rm -rf ~/.local/share/Trash/*`).
    6. Execution Planner: Takes the finalized plan and explicitly decides the execution mode: Immediate URL/Deep Link, Immediate Local Script, OR Scheduled/Delayed Reminder (if the user implies a future time).
       CRITICAL RULES FOR JSON OUTPUT:
       - If the user asks to open ANY website or web app, YOU MUST SET requires_browser=true and target_url="https://...".
       - DEEP LINKING: For multi-step web actions (e.g., "open gmail... draft email..."), construct the exact deep link!
       - REMINDERS & SCHEDULING: If the user asks to "remind me to...", "schedule", or do something at a specific future time:
         * DO NOT write a bash script. DO NOT open Google Calendar. DO NOT use pyautogui.
         * INSTEAD, set `is_reminder=true`.
         * Set `reminder_message` to the task (e.g. "Call manager").
         * Set `reminder_time` to the EXACT future time in ISO 8601 format, STRICTLY CONVERTED TO UTC (e.g., "2026-10-01T10:30:00Z"). CALCULATE this based on the CURRENT SYSTEM TIME provided above.
         * Set `shell_script` to a simple comment: "# Reminder scheduled in database".
       - If the user asks to EMPTY/CLEAR the RECYCLE BIN: Look at target_os! If Windows, use `Clear-RecycleBin -Force`. If Linux, use `rm -rf ~/.local/share/Trash/*`. DO NOT hallucinate Windows commands on Linux.
       - If the user asks to OPEN an app (e.g. "text editor"): DO NOT HARDCODE PATHS. 
         * On Linux, write a Bash script that loops through an array of possibilities (e.g., `for app in gnome-text-editor gedit kwrite mousepad nano; do if command -v $app >/dev/null; then $app & exit 0; fi; done`).
         * On Windows, write a PowerShell script that loops through standard directories or uses `Get-Command`.
       - NEVER use placeholder text like "[username]". ALWAYS use standard environment variables.
       - You MUST populate the `expected_process` field with the executable name (e.g., "gnome-text-editor", "spotify") whenever you are launching an app.
       - Your scripts MUST be resilient, smart, and dynamic.
       
       ZERO HALLUCINATION POLICY:
       Your ONLY job is to output the final script/URL. You CANNOT EXECUTE SCRIPTS directly. The user's machine will execute the script you generate.

    YOU MUST OUTPUT STRICTLY A JSON OBJECT MATCHING THIS EXACT SCHEMA (do not omit ANY fields):
    {{
      "multi_agent_discussion": [{{"agent_name": "str", "thought": "str"}}],
      "is_safe": true,
      "target_os": "str",
      "requires_browser": true,
      "target_url": "str or null",
      "shell_script": "str",
      "expected_process": "str or null",
      "mermaid_diagram_body": "str"
    }}

    CRITICAL MERMAID RULES:
    You MUST generate a HIGHLY DETAILED, NON-LINEAR flowchart mapping the EXACT architecture and decision process for THIS specific task.
    DO NOT just make a single straight line! 
    - Show conditional decision trees (using diamond shapes {{}} for decisions).
    - Show parallel processing where multiple agents work at once.
    - Specifically label edges with WHAT the agent did or concluded (e.g., -->|Generated Draft Text|).
    DO NOT include 'graph TD;' at the start (the frontend will prepend it).
    Use safe Mermaid syntax: ALWAYS quote labels if they have spaces or special characters (e.g., NodeID["Text goes here"]).
    
    Example of an advanced graph:
    User["User Prompt"] --> Swarm["Agent Swarm Spawned"]
    Swarm -->|Step 1| IntentPlan["Intent Agent: Broke into multiple steps"]
    Swarm -->|Step 2| SysRecon["Recon Agent: Identified Linux text editors"]
    Swarm -->|Step 3| ContentGen["Content Agent: Wrote 5 lines about friend"]
    IntentPlan --> SecGuard{{"Security Guard: Is it malicious?"}}
    SysRecon --> CommandRes["Command Research: Found Bash Loop syntax"]
    ContentGen --> CommandRes
    SecGuard -->|No, Safe| ExecPlanner["Execution Planner: Assembled final script"]
    SecGuard -->|Yes, Block| Abort["Abort Operation"]
    CommandRes --> ExecPlanner
    ExecPlanner --> ShellNode["Bash Script Output"]
    ShellNode --> HostEngine["Host Execution"]
    
    Ensure your output matches the requested JSON schema exactly.
    """
    
    last_error = None
    
    logger.info("Incoming automation request received", prompt=request.natural_language_prompt, user_agent=request.user_agent_os)
    logger.debug("System prompt built successfully", length=len(system_prompt))
    
    for model_name in FALLBACK_MODELS:
        try:
            logger.info(f"Attempting multi-agent generation with model: {model_name}")
            logger.log("TRACE", "Sending request to litellm", model=model_name, timeout=20.0)
            
            response = await litellm.acompletion(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Task: {request.natural_language_prompt}"}
                ],
                response_format={"type": "json_object"},
                timeout=20.0 
            )
            
            logger.log("TRACE", "Received raw LLM response", raw_content=response.choices[0].message.content)
            
            raw_content = response.choices[0].message.content.strip()
            if raw_content.startswith("```"):
                raw_content = raw_content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            structured_data = json.loads(raw_content)
            logger.info(f'PARSED DATA: {structured_data}')
            
            if structured_data.get("is_reminder") and structured_data.get("reminder_time"):
                try:
                    # Handle Z and ISO formats
                    time_str = structured_data["reminder_time"].replace("Z", "+00:00")
                    dt_obj = datetime.datetime.fromisoformat(time_str)
                    # convert to naive UTC for asyncpg timestamp
                    if dt_obj.tzinfo:
                        dt_obj = dt_obj.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                    
                    async with DB_POOL.acquire() as conn:
                        await conn.execute(
                            "INSERT INTO reminders (message, trigger_time) VALUES ($1, $2)",
                            structured_data["reminder_message"],
                            dt_obj
                        )
                    logger.info(f"Scheduled reminder saved to DB: {structured_data['reminder_message']} at {structured_data['reminder_time']}")
                except Exception as e:
                    logger.error(f"Failed to insert reminder into DB: {e}")
                    raise e

            
            logger.debug("Extracted JSON data from model response")
            
            # --- Analytics Recording ---
            usage = getattr(response, "usage", {})
            if isinstance(usage, dict):
                t = {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0)
                }
            else:
                t = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0)
                }
            record_llm_usage(model_name, True, t)

            
            # --- AGENTIC MIDDLEWARE INTERCEPTOR ---
            prompt_lower = request.natural_language_prompt.lower()
            
            
            # Explicit Deep Link Interceptor for weak models (like Llama 8B)
            if "gmail" in prompt_lower and ("draft" in prompt_lower or "email" in prompt_lower):
                import urllib.parse
                
                # Extract basic info heuristically
                to_email = ""
                emails = [word for word in prompt_lower.split() if "@" in word]
                if emails:
                    to_email = emails[0].strip("',.")
                
                # Hard fallback URL construction
                base_url = "https://mail.google.com/mail/?view=cm&fs=1"
                if to_email:
                    base_url += f"&to={to_email}"
                
                # Add a generic professional body
                body_text = "Hello,\n\nI will not be able to join the meeting today.\n\nBest regards."
                if "cannot" in prompt_lower and "meeting" in prompt_lower:
                    base_url += f"&su=Meeting&body={urllib.parse.quote(body_text)}"
                
                logger.info("Middleware hijacked Gmail intent to enforce Deep Linking.")
                structured_data["requires_browser"] = True
                structured_data["target_url"] = base_url
                structured_data["shell_script"] = ""
            else:
                web_keywords = {
                    "spotify": "https://open.spotify.com",
                    "netflix": "https://www.netflix.com",
                    "github": "https://github.com",
                    "youtube": "https://www.youtube.com",
                    "camera": "microsoft.windows.camera:"
                }
                
                forced_url = None
                for kw, url in web_keywords.items():
                    if kw in prompt_lower:
                        forced_url = url
                        break
                        
                if forced_url or "browser" in prompt_lower or "http" in prompt_lower or "website" in prompt_lower:
                    if forced_url == "microsoft.windows.camera:":
                        # Launch camera via protocol without browser
                        structured_data["requires_browser"] = False
                        structured_data["shell_script"] = f"Start-Process '{forced_url}'"
                    else:
                        structured_data["requires_browser"] = True
                        if not structured_data.get("target_url") or "google.com" in structured_data.get("target_url", ""):
                            structured_data["target_url"] = forced_url if forced_url else "https://www.google.com"

                # --- INTELLIGENT COMMAND RESOLUTION (3-tier) ---
                # Tier 1: Redis Cache (instant, previously learned)
                # Tier 2: KNOWN_APP_COMMANDS (hardcoded knowledge base)
                # Tier 3: Research Agent (web search + LLM extraction)
                
                if not structured_data.get("requires_browser"):
                    resolved_command = None
                    resolution_source = None
                    
                    # Extract the app name from the prompt for lookups
                    app_keywords = prompt_lower.replace("open ", "").replace("launch ", "").replace("start ", "").strip()
                    
                    # --- TIER 1: Redis Cache ---
                    redis_result = get_learned_command(app_keywords)
                    if redis_result:
                        resolved_command = redis_result
                        resolution_source = "Redis Cache (previously learned)"
                    
                    # --- TIER 2: KNOWN_APP_COMMANDS ---
                    if not resolved_command:
                        for app_alias, app_data in KNOWN_APP_COMMANDS.items():
                            if app_alias in prompt_lower:
                                resolved_command = app_data
                                resolution_source = f"Knowledge Base (matched '{app_alias}')"
                                # Also cache in Redis for faster future lookups
                                store_learned_command(app_alias, app_data["script"], app_data["process"])
                                break
                    
                    # --- TIER 3: Research Agent (web search) ---
                    if not resolved_command and not structured_data.get("requires_browser"):
                        logger.info(f"[Tier 3] No cached/known command. Deploying Research Agent for: '{app_keywords}'")
                        research_result = await research_command(app_keywords, request.user_agent_os)
                        if research_result and research_result.get("script"):
                            resolved_command = research_result
                            resolution_source = "Research Agent (web search + LLM extraction)"
                            # Learn it for next time!
                            store_learned_command(app_keywords, research_result["script"], research_result.get("process", ""))
                            # Add the Research Agent to the discussion log
                            structured_data.setdefault("multi_agent_discussion", []).append({
                                "agent_name": "Command Research Agent",
                                "thought": f"Searched the web for the correct command to '{app_keywords}'. Found: '{research_result['script']}'. Stored in Redis for instant future lookups."
                            })
                    
                    # Apply the resolved command (from any tier)
                    if resolved_command:
                        structured_data["requires_browser"] = False
                        structured_data["shell_script"] = resolved_command["script"]
                        structured_data["expected_process"] = resolved_command.get("process", "")
                        structured_data["target_url"] = ""
                        logger.info(f"Command resolved via {resolution_source}: script='{resolved_command['script']}'")
            # --------------------------------------
            
            structured_data['model_used'] = model_name
            
            # Log agent decisions
            for agent in structured_data.get('multi_agent_discussion', []):
                logger.log("TRACE", f"Agent Action: {agent.get('agent_name')}", thought=agent.get('thought'))
            
            logger.info("Successfully architected workflow", model=model_name)
            return MultiAgentResult(**structured_data)
            
        except Exception as e:
            print(f"MODEL_FAILURE_DEBUG: Model {model_name} failed: {type(e).__name__} - {str(e)}", flush=True)
            logger.warning(f"Model {model_name} failed: {type(e).__name__} - {str(e)}")
            last_error = e
            continue 

    logger.critical("All fallback models failed", error=str(last_error))
    raise HTTPException(status_code=500, detail=f"All fallback models failed. Last error: {str(last_error)}")

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
