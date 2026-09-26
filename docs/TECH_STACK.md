# 💻 Tech Stack

OmniShell is built using a modern, scalable, and highly decoupled architecture.

## 🎨 Frontend (The Checkpoint)
*   **Framework:** [NestJS](https://nestjs.com/)
*   **Templating:** [Handlebars (HBS)](https://handlebarsjs.com/)
*   **Styling:** Bootstrap & Custom CSS
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
*   **Language:** Python 3
*   **System APIs:** subprocess.Popen (Windows CREATE_NEW_CONSOLE integration)
*   **Process Validation:** psutil (Validates cross-platform process spawning)
