# 💻 Tech Stack

OmniShell is built using a modern, scalable, and highly decoupled architecture.

## 🎨 Frontend (The Checkpoint)
*   **Framework:** [NestJS](https://nestjs.com/)
*   **Templating:** [Handlebars (HBS)](https://handlebarsjs.com/)
*   **Styling:** [Tailwind CSS](https://tailwindcss.com/) & Custom CSS
*   **Interactivity:** [SweetAlert2](https://sweetalert2.github.io/) (For strict Human-in-the-Loop execution popups)
*   **Visualizations:** [Mermaid.js](https://mermaid.js.org/) (For dynamic Agent flowcharts)

## 🧠 Backend API (The Brain)
*   **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python)
*   **AI Orchestration:** [LiteLLM](https://litellm.ai/) (Provides standard interface for 100+ LLMs)
*   **Data Validation:** Pydantic (Enforces strict JSON schema generation from the LLMs)
*   **Tracing:** TraceNest (Logs internal agent thought processes)

## 🗄️ Infrastructure & State
*   **Containerization:** [Docker & Docker Compose](https://www.docker.com/)
*   **Database:** [PostgreSQL](https://www.postgresql.org/) (Stores execution history and prompts)
*   **Caching & Rate Limiting:** [Redis](https://redis.io/)

## ⚙️ Execution Layer (The Muscle)
*   **Language:** Python 3 (Native Host)
*   **System APIs:** `subprocess.Popen` (Advanced process piping and tree management in V2)
*   **Process Validation:** `psutil` (Validates cross-platform process spawning and cleanup)
*   **HTTP Bridge:** Custom ThreadedHTTPServer on port 8003 for secure UI-to-Host communication
