import os
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import litellm
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
    user_agent_os: str = "Unknown OS"

class AgentThought(BaseModel):
    agent_name: str = Field(description="Name of the agent (e.g., 'OS Analyzer', 'Security Guard', 'Execution Planner')")
    thought: str = Field(description="The internal reasoning and decision making of this agent")

class MultiAgentResult(BaseModel):
    multi_agent_discussion: list[AgentThought] = Field(description="The step-by-step discussion between the agents.")
    is_safe: bool = Field(description="True if safe, False if malicious (formatting, viruses).")
    target_os: str = Field(description="The detected OS (Windows, Linux, macOS, Android, iOS).")
    requires_browser: bool = Field(description="Set to True ONLY if the user is asking to open a website, url, or web service (like Netflix, GitHub).")
    target_url: str | None = Field(description="The full URL to open (e.g., 'https://www.netflix.com'). Required if requires_browser is True.")
    shell_script: str = Field(description="Robust script to execute. Only used if requires_browser is False. E.g., Start-Process 'code'")
    expected_process: str | None = Field(default=None, description="The name of the executable process that should be running after execution (e.g. 'excel', 'code', 'spotify', 'explorer'). Used to validate 100% completion.")
    mermaid_diagram_body: str = Field(description="ONLY the body of the flowchart. DO NOT include 'graph TD;'. You MUST map out a highly detailed, branching diagram showing parallel agent work and decision trees. Example: P[Prompt] --> OS[OS Analyzer]; P --> SG[Security Guard]; OS -.-> EP[Execution Planner]; SG -.-> EP; EP -->|Web| W[URL]; EP -->|Local| S[Script]; W --> H[Host]; S --> H; H --> UI[UI];")
    model_used: str | None = Field(default=None)
    model_used: str | None = Field(default=None)

# Fallback Models (Smartest 70B+ models first to ensure strict prompt adherence)
FALLBACK_MODELS = [
    "openrouter/google/gemini-2.0-flash-exp:free",
    "openrouter/meta-llama/llama-3.3-70b-instruct:free",
    "openrouter/nvidia/llama-3.1-nemotron-70b-instruct:free",
    "groq/llama-3.3-70b-versatile",
    "openrouter/meta-llama/llama-3.1-8b-instruct",
    "gemini/gemini-1.5-flash"
]

@app.post("/api/generate-workflow", response_model=MultiAgentResult)
async def generate_workflow(request: AutomationRequest):
    system_prompt = f"""
    You are a Multi-Agent OS Automation Syndicate. 
    You are receiving a request from a user on the following OS environment: '{request.user_agent_os}'.
    
    You must simulate a highly advanced discussion between FOUR distinct agents:
    1. Intent & Planning Agent: Breaks down the plain English prompt into logical, multi-step execution sequences.
    2. Content Generation Agent: If the user provides rough instructions for an email, message, or search, this agent expands it into a fully professional, context-aware text body, and URL-encodes it so it can be passed into deep links.
    3. Security Guard: Strictly checks for malicious intent (formatting disks, viruses) AND enforces operational constraints (e.g., if the user asks to SEND an email, the Guard MUST downgrade it to DRAFT ONLY. Sending without manual review is illegal). 
    4. Execution Planner: Takes the finalized plan and content, then decides if it requires a URL/Deep Link OR a local Desktop App script.
       CRITICAL RULES FOR JSON OUTPUT:
       - If the user asks to open ANY website or web app, YOU MUST SET requires_browser=true and target_url="https://...". DO NOT write a shell script for this.
       - DEEP LINKING: For multi-step web actions (e.g., "open gmail... draft email... say X"), construct the exact deep link! Example: target_url="https://mail.google.com/mail/?view=cm&fs=1&to=person@email.com&su=Subject&body=URL_ENCODED_PROFESSIONAL_BODY". DO NOT write a local PowerShell SMTP script.
       - Even if the user explicitly says "open brave browser", just set requires_browser=true and target_url="https://...". The external UI Agent will handle selecting the Brave browser.
       - If the user asks to open the RECYCLE BIN: Look at target_os! If Windows, shell_script='Start-Process "shell:RecycleBinFolder"'. If Linux/Ubuntu, shell_script='xdg-open trash://' or 'nautilus trash://'. DO NOT use explorer.exe.
       - If they want a LOCAL app: Look at target_os! If Windows, write a robust PowerShell script that actually searches for the application executable (e.g. checking $env:LOCALAPPDATA, $env:APPDATA, $env:ProgramFiles) before calling Start-Process.
       - NEVER use placeholder text like "[username]". ALWAYS use standard environment variables like $env:USERNAME.
       - You MUST populate the `expected_process` field with the executable name (e.g., "excel", "spotify") whenever you are launching an app, so the system can verify it actually opened.
       - If the user asks a QUESTION about the system: Look at target_os! Write a clean PowerShell (Windows) or Bash (Linux) script.
       
       ZERO HALLUCINATION POLICY:
       Your ONLY job is to output the final script/URL. You CANNOT EXECUTE SCRIPTS. The user's machine will execute it.

    CRITICAL MERMAID RULES:
    Generate a HIGHLY DETAILED, NON-LINEAR flowchart mapping the exact agent architecture. 
    DO NOT just make a single straight line! Show parallel processes, decision trees, and data flows.
    DO NOT include 'graph TD;' at the start (the frontend will prepend it).
    Example of a safe detailed graph using ONLY brackets for shapes:
    Prompt[User Prompt] --> IntentPlan[Intent & Planning Agent]
    IntentPlan --> ContentGen[Content Generation Agent]
    IntentPlan --> SecGuard[Security Guard]
    ContentGen -.->|Drafts Body| ExecPlanner[Execution Planner]
    SecGuard -.->|Blocks Send| ExecPlanner
    ExecPlanner --> WebNode[Deep Link URL]
    ExecPlanner --> ShellNode[Shell Script]
    WebNode --> HostEngine[Host Execution]
    ShellNode --> HostEngine
    HostEngine --> Validator[Process Validation]
    Validator --> UI[Frontend UI]
    
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
                response_format=MultiAgentResult,
                timeout=20.0 
            )
            
            logger.log("TRACE", "Received raw LLM response", raw_content=response.choices[0].message.content)
            
            structured_data = json.loads(response.choices[0].message.content)
            logger.debug("Extracted JSON data from model response")
            
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
                    "youtube": "https://www.youtube.com"
                }
                
                forced_url = None
                for kw, url in web_keywords.items():
                    if kw in prompt_lower:
                        forced_url = url
                        break
                        
                if forced_url or "browser" in prompt_lower or "http" in prompt_lower or "website" in prompt_lower:
                    structured_data["requires_browser"] = True
                    if not structured_data.get("target_url") or "google.com" in structured_data.get("target_url", ""):
                        structured_data["target_url"] = forced_url if forced_url else "https://www.google.com"
            # --------------------------------------
            
            structured_data['model_used'] = model_name
            
            # Log agent decisions
            for agent in structured_data.get('multi_agent_discussion', []):
                logger.log("TRACE", f"Agent Action: {agent.get('agent_name')}", thought=agent.get('thought'))
            
            logger.info("Successfully architected workflow", model=model_name)
            return MultiAgentResult(**structured_data)
            
        except Exception as e:
            logger.warning(f"Model {model_name} failed: {type(e).__name__} - {str(e)}")
            last_error = e
            continue 

    logger.critical("All fallback models failed", error=str(last_error))
    raise HTTPException(status_code=500, detail=f"All fallback models failed. Last error: {str(last_error)}")
