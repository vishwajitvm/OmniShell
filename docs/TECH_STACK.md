# 💻 OmniShell Tech Stack & Architecture Components

OmniShell is built using a modern, decoupled architecture separating cognitive planning, web presentation, state persistence, and native OS execution.

---

## 🎨 1. Frontend & Presentation Layer

- **Framework**: [NestJS](https://nestjs.com/) (Node.js framework with TypeScript)
- **Templating**: [Handlebars (HBS)](https://handlebarsjs.com/) for server-side rendering
- **Styling**: [Tailwind CSS](https://tailwindcss.com/) & Modern Dark Glassmorphism Design
- **Interactive Modals**: [SweetAlert2](https://sweetalert2.github.io/) for Human-in-the-Loop authorization
- **Flowchart Rendering**: [Mermaid.js](https://mermaid.js.org/) for dynamic multi-agent pipeline visualization with `- Zoom`, `Reset`, `+ Zoom` canvas controls
- **Markdown & Code Rendering**: [marked.js](https://marked.js.org/) & [highlight.js](https://highlightjs.org/)

---

## 🧠 2. Agentic Backend & Cognitive Engine

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (High-performance Python async web framework)
- **AI / LLM Orchestration**: [LiteLLM](https://litellm.ai/) & Multi-Provider Model Routing (NVIDIA NIM, DeepSeek-R1, OpenAI, Anthropic, Ollama)
- **Data Validation & Schemas**: [Pydantic v2](https://docs.pydantic.dev/) (Enforces strict schema typing and structured output validation)
- **Web Research API**: Autonomous DuckDuckGo Search Integration for unknown command resolution
- **Tracing & Telemetry**: Native TraceNest Execution Logger & Microsecond-precision telemetry timers

---

## 🗄️ 3. Persistence, Caching & Infrastructure

- **Containerization**: [Docker & Docker Compose](https://www.docker.com/) for complete stack isolation
- **Database**: [PostgreSQL 16](https://www.postgresql.org/) (Stores scheduled tasks, execution logs, and audit trails)
- **In-Memory Cache & Fast Path**: [Redis 7](https://redis.io/) (Caches learned commands, session states, and rate limits)
- **ORM / Query Layer**: [SQLAlchemy](https://www.sqlalchemy.org/) & [asyncpg](https://github.com/MagicStack/asyncpg) / [psycopg2](https://www.psycopg.org/)

---

## ⚙️ 4. Native Host Execution Daemon (`local_executor.py`)

- **Runtime**: Python 3.10+ running natively in host user space on Port 8003
- **Process Management**: `subprocess.Popen` with process group isolation and stdin/stdout/stderr piping
- **System Monitoring**: `psutil` (Validates process hierarchy, PID creation, memory, and CPU metrics)
- **Cross-Platform Shells**: Linux (`/bin/bash`), macOS (`/bin/zsh`), Windows (`powershell.exe`)
- **Browser Automation**: Multi-browser detection and deep-link protocol dispatches
- **Autonomous Poller**: Background daemon thread polling for scheduled task maturity every 2 seconds
