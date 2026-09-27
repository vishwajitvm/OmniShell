# 🏗️ Architecture Deep Dive

OmniShell relies on a strict separation of concerns to maintain security while executing AI-generated commands.

## The 7-Agent Syndicate
Within the FastAPI backend, requests are processed by a multi-agent system before any code is generated:
1. **Intent & Planning:** Parses natural language into a logical sequence of actions.
2. **System Reconnaissance:** 🆕 Dynamically writes scripts to discover available applications locally (e.g. searching for text editors) to prevent hallucinating hardcoded paths on different OS builds.
3. **Content Generation Agent:** Expands rough instructions for emails/messages into fully professional text.
4. **Security Guard:** A rigid rule-engine that strips out destructive commands and forces compliance.
5. **Command Research Agent:** Searches the web in real-time (via DuckDuckGo) to find the correct CLI command for the specific target OS.
6. **Command Validator Agent (CRITIC):** 🆕 A ruthless reviewer that scrutinizes the Command Research Agent's output. Enforces strict case-sensitivity for Linux, checks for robust fallbacks (e.g., using `find`), and forces a complete rewrite if the initial draft is flawed.
7. **Execution Planner:** Maps the finalized, validated intent to either a `requires_browser=True` Deep Link URL, or a robust, fault-tolerant `shell_script` for local OS execution.

## 3-Tier Command Resolution

Before executing any command, OmniShell runs a **3-tier resolution pipeline** to ensure the correct command is used:

```mermaid
graph LR;
    Prompt["User Prompt"] --> T1{"Tier 1: Redis Cache"};
    T1 -->|"HIT"| Exec["Execute Correct Command"];
    T1 -->|"MISS"| T2{"Tier 2: Knowledge Base"};
    T2 -->|"MATCH"| Exec;
    T2 -->|"MISS"| T3["Tier 3: Research Agent"];
    T3 -->|"Web Search + LLM"| Exec;
    T3 -->|"Learn"| Redis[("Redis")];
```

| Tier | Source | Speed | Description |
|------|--------|-------|-------------|
| **1** | Redis Cache | ⚡ < 1ms | Previously learned commands. Checked first for instant lookups. |
| **2** | `KNOWN_APP_COMMANDS` | ⚡ < 1ms | Hardcoded knowledge base of 20+ common apps and their correct commands. |
| **3** | Research Agent | 🔍 3-10s | DuckDuckGo web search → LLM extraction → stores result in Redis for future. |

## Docker-to-Host Bridging
Because the FastAPI backend lives inside an isolated Docker network, it cannot natively launch applications on the host Windows/Linux machine. 

To solve this, OmniShell uses an asynchronous bridge:
1. The AI generates the script/URL.
2. The UI intercepts it and triggers a **SweetAlert2** popup for human approval.
3. Upon approval, the UI sends an HTTP POST request to http://localhost:8003.
4. `local_executor.py` intercepts this on the host machine.
5. On Windows, it uses `creationflags=0x00000010` (`CREATE_NEW_CONSOLE`) to physically pop open a highly visible terminal to execute the command.

## 🧠 Self-Learning Pipeline

OmniShell includes a self-correcting learning system that ensures the AI gets smarter with every interaction. Instead of blindly trusting LLM-generated commands, the system validates outputs and learns from mistakes.

### How It Works

```mermaid
graph TD;
    A((User)) -->|"open vs code"| B["LLM Agent Pipeline"];
    B -->|"Generates WRONG command"| C{"3-Tier Resolution"};
    C -->|"Tier 1: Redis MISS"| D{"Tier 2: Knowledge Base"};
    D -->|"FOUND: vs code = code"| E["Override LLM with correct command"];
    D -->|"NOT FOUND"| F["Tier 3: Research Agent searches web"];
    F -->|"DuckDuckGo + LLM extract"| G["Found correct command"];
    G -->|"Store in Redis"| H[("Redis Cache")];
    E --> I["Host Execution"];
    G --> I;
    I --> J{"psutil Validator"};
    J -->|"SUCCESS"| K["Return to User"];
    J -->|"FAILURE"| L["Log and Learn"];
    L --> H;
```

### The Three Execution Paths

| Path | Trigger | Behavior |
|------|---------|----------|
| **Known App (Cached)** | App exists in Redis or `KNOWN_APP_COMMANDS` | LLM output is **overridden** with the known-correct command. Near-instant response. |
| **Unknown App (Research)** | App is NOT in knowledge base or cache | **Research Agent** searches the web, extracts the correct command, stores it in Redis, and executes. Next time it's instant. |
| **Failed Execution** | psutil validation fails | The failure is logged with full context (command, expected process, error output, timestamp). Flagged for manual review. |

### Knowledge Base: `KNOWN_APP_COMMANDS`

A curated dictionary of common application mappings that acts as a **middleware override layer** between the LLM and execution:

```python
KNOWN_APP_COMMANDS = {
    "Windows": {
        "vs code":   {"script": "code",     "process": "Code.exe"},
        "calculator": {"script": "calc",    "process": "Calculator.exe"},
        # ...
    },
    "Linux": {
        "vs code":   {"script": "code",     "process": "code"},
        "calculator": {"script": "gnome-calculator", "process": "gnome-calculator"},
        # ...
    }
}
```

### Dual-Store Caching Strategy

- **Redis** — Fast in-memory cache for corrected command mappings. Enables sub-millisecond lookups for repeat requests, allowing the system to bypass the LLM entirely for known apps.
- **PostgreSQL** — Persistent store for the complete correction history including timestamps, original LLM output, corrected command, validation results, and error logs. Used for analytics, debugging, and model fine-tuning.

> See the full diagrams at:
> - [`architecture.mmd`](./diagrams/architecture.mmd) — 5-Agent architecture with 3-Tier resolution
> - [`self_learning_pipeline.mmd`](./diagrams/self_learning_pipeline.mmd) — Detailed pipeline with known/unknown/cached paths
> - [`learning_fix_flow.mmd`](./diagrams/learning_fix_flow.mmd) — Complete learning & self-correction flow
