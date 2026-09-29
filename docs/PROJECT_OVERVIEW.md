# 🐚 OmniShell - Universal Autonomous Multi-Agent OS & Knowledge Syndicate

## 🌟 Executive Summary

**OmniShell** is an enterprise-grade, multi-agent autonomous operating system copilot and knowledge syndicate designed to bridge the gap between Large Language Model (LLM) cognitive reasoning and physical host execution (Linux, macOS, Windows). 

Conventional AI chatbots (e.g., ChatGPT, Claude) are constrained to isolated conversational web boxes—they can describe *how* to execute a workflow, but they cannot perform it on your machine. Conversely, naive autonomous agent implementations often execute commands blindly without human verification, risking data corruption, system disruption, or unauthorized actions.

**OmniShell solves this by combining a decentralized 8-Agent Swarm Syndicate, a strict Request Control Plane (`Intent → Policy → Plan → Execute → Verify`), multi-layer Human-in-the-Loop (HITL) gates, and an isolated local host executor daemon.**

```mermaid
graph TD
    User(["👤 User Prompt"]):::userClass --> UI["🖥️ Frontend Control Center (NestJS + Handlebars)"]:::uiClass
    UI --> Backend["⚡ Agentic Backend Engine (FastAPI)"]:::backendClass
    
    subgraph Syndicate ["🤖 8-Agent Swarm Syndicate"]
        Backend --> A1["1. Intent & Planning Agent"]:::agentClass
        A1 --> A2["2. System Reconnaissance Agent"]:::agentClass
        A2 --> A3["3. Content & Knowledge Synthesizer"]:::agentClass
        A3 --> A4["4. Security Guard"]:::agentClass
        A4 --> A5["5. Safety & Policy Supervisor"]:::agentClass
        A5 --> A6["6. Command Research Agent"]:::agentClass
        A6 --> A7["7. Command Validator Agent"]:::agentClass
        A7 --> A8["8. Execution Planner"]:::agentClass
        A5 -.->|"Ambiguity Detected"| Clarify["❓ Clarification Agent"]:::clarifyClass
    end

    Backend -.-> DB[("🐘 PostgreSQL\n(Scheduled Tasks & Execution History)")]:::dbClass
    Backend -.-> Redis[("🔴 Redis Cache\n(Learned Commands & Fast Path)")]:::cacheClass

    Syndicate --> ModeDecision{"Capability Routing (19 Modes)"}:::decisionClass
    ModeDecision -->|"Knowledge (Q&A/Info/Plan)"| DirectMarkdown["💡 Markdown Answer Card\n(Zero Shell Execution)"]:::infoClass
    ModeDecision -->|"Host Execution"| HITLCheck{"Safety Gate & HITL"}:::decisionClass
    ModeDecision -->|"Scheduled / Recurring"| PostgresQueue["📅 Scheduled Task Queue"]:::schedClass

    HITLCheck -->|"Authorized"| HostDaemon["💻 Local Host Executor (local_executor.py:8003)"]:::hostClass
    PostgresQueue -->|"Token Verified"| PopoutWindow["📄 Pop-out Approval Window Document"]:::windowClass
    PopoutWindow -->|"User Approved"| HostDaemon

    HostDaemon --> NativeOS["⚡ Native Host OS (Bash / Zsh / PowerShell)"]:::execClass
    NativeOS --> ProcessVerify["✅ Process & Exit Code Verification (psutil)"]:::verifyClass
    ProcessVerify --> UI

    classDef userClass fill:#3b82f6,stroke:#1d4ed8,color:#ffffff,stroke-width:2px;
    classDef uiClass fill:#1e1b4b,stroke:#6366f1,color:#ffffff,stroke-width:2px;
    classDef backendClass fill:#064e3b,stroke:#10b981,color:#ffffff,stroke-width:2px;
    classDef agentClass fill:#1e1b4b,stroke:#818cf8,color:#e0e7ff,stroke-width:1.5px;
    classDef clarifyClass fill:#451a03,stroke:#f59e0b,color:#fde68a,stroke-width:2px;
    classDef dbClass fill:#1e293b,stroke:#0284c7,color:#38bdf8,stroke-width:2px;
    classDef cacheClass fill:#1e293b,stroke:#ef4444,color:#f87171,stroke-width:2px;
    classDef decisionClass fill:#312e81,stroke:#a855f7,color:#ffffff,stroke-width:2px;
    classDef infoClass fill:#064e3b,stroke:#34d399,color:#ecfdf5,stroke-width:2px;
    classDef schedClass fill:#3b0764,stroke:#c084fc,color:#fae8ff,stroke-width:2px;
    classDef windowClass fill:#1e1b4b,stroke:#a855f7,color:#f3e8ff,stroke-width:2px;
    classDef hostClass fill:#111827,stroke:#10b981,color:#6ee7b7,stroke-width:2px;
    classDef execClass fill:#022c22,stroke:#059669,color:#a7f3d0,stroke-width:2px;
    classDef verifyClass fill:#064e3b,stroke:#10b981,color:#ecfdf5,stroke-width:2px;
```

---

## 🏛️ System Topology & Decoupled Layers

OmniShell is architected with three cleanly decoupled operational layers:

### 1. The Presentation & Control Plane (NestJS + Handlebars + Tailwind CSS)
- **Real-time Lifecycle State Machine**: Displays the 5-stage lifecycle badges (`Intent → Policy → Plan → Execute → Verify`) with live color transitions (`COMPLETED`, `ACTIVE`, `PENDING`, `APPROVAL REQ`, `CLARIFICATION`).
- **Interactive Swarm Telemetry**: Live metric meters tracking LLM reasoning time, web research latency, security validation timing, and native execution duration.
- **Interactive Multi-Agent Syndicate Discussion**: Expandable transcript detailing the deliberation, AST checks, and execution planning of all 8 agents.
- **Dynamic Mermaid Flowchart Viewer**: Renders interactive Mermaid workflow diagrams with pan and `- Zoom`, `Reset`, `+ Zoom` canvas controls.
- **Dual Human-in-the-Loop Dialogues**:
  - *In-UI SweetAlert2 Modals*: For immediate elevated host operations with syntax-highlighted command previews.
  - *Pop-out Approval Window Documents (`/scheduled-approval/:token`)*: Standalone dedicated pages with SHA-256 token validation and 300-second countdown timers for background scheduled jobs.

### 2. The Cognitive Engine & Swarm Syndicate (FastAPI + LiteLLM + Redis + PostgreSQL)
- **8-Agent Swarm Collaboration**: Specialized agents decompose, screen, research, validate, and plan incoming prompts.
- **Clarification & Intent Disambiguation Engine**: Synthesizes structured, actionable choice options when prompts are ambiguous or missing parameters.
- **Knowledge Base & 3-Tier Command Caching**: Redis-backed fast-path for sub-millisecond execution of recognized operations without LLM overhead.
- **PostgreSQL Task & Execution Registry**: Persistent storage for background scheduled tasks, recurrence rules, approval tokens, and comprehensive execution logs.

### 3. The Native Host Execution Daemon (`local_executor.py` on Port 8003)
- **Isolated Host Bridge**: Runs natively in user-space on Windows, Linux, or macOS.
- **Safe Subprocess Pipeline**: Executes commands via `/bin/bash` or `powershell.exe` with real-time stdout/stderr capture, process group isolation, and timeout guards.
- **Process Verification**: Integrates `psutil` to inspect process trees, PID creation, and exit codes.
- **Cross-Platform Browser Launcher**: Detects installed browsers (Chrome, Brave, Firefox, Edge, Safari) and handles deep-link dispatches.
- **Background Scheduler Poller**: Periodically checks the backend queue, triggers pop-out approval documents when tasks mature, and executes approved jobs.

---

## 🎯 Primary Use Cases & Capabilities Summary

| Interaction Category | Description | Primary Execution Mechanism |
|---|---|---|
| **Direct Knowledge & Q&A** | Answers conceptual, factual, and technical queries | Rich Markdown Card (Zero Host Shell Invocation) |
| **System Diagnostics** | Inspects CPU, RAM, disk, network, and active processes | Native `psutil` & diagnostic terminal scripts |
| **Application & Browser Operations** | Launches applications and deep-links browser workflows | Native process dispatch & URL deep-linking |
| **Multi-Step Workflows** | Decomposes goals into sequential executable steps | Structured step tracker with progress states |
| **Scheduled & Recurring Tasks** | Runs tasks at future timestamps or recurring intervals | PostgreSQL scheduler queue + Pop-out Approval Window |
| **Self-Healing Recovery** | Recovers from command failures with retry heuristics | Automatic diagnostic analysis and fallback commands |

---

## 🔒 Enterprise Security & Guardrails

1. **Pre-LLM Regex Red-Line Interceptor**: Hardcoded deterministic filter blocking dangerous shell primitives (`rm -rf /`, `mkfs`, `dd if=/dev/zero`, password theft, credential dumping).
2. **AI Security Guard Agent**: Contextual AST analysis checking for privilege escalation, network exfiltration, or destructive file modifications.
3. **Double-Confirmation Human-in-the-Loop**: Destructive host operations require explicit confirmation before execution.
4. **Cryptographic Token Verification**: Scheduled tasks require single-use, URL-safe SHA-256 tokens to prevent replay or unauthorized execution.
