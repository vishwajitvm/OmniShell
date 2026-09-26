import os

# 1. LOCAL_SETUP.md
local_setup = """# 🛠️ Local Setup Guide

This guide will walk you through setting up OmniShell on your local machine.

## 📋 Prerequisites
Before you begin, ensure you have the following installed on your machine:
- [Docker Desktop](https://www.docker.com/products/docker-desktop) (For the AI Backend & UI)
- [Python 3.10+](https://www.python.org/downloads/) (For the Host Executor)
- [Git](https://git-scm.com/)

---

## 🚀 Step 1: Clone the Repository
Open your terminal and clone the repository:

`ash
git clone https://github.com/vishwajitvm/OmniShell.git
cd OmniShell
`

## ⚙️ Step 2: Configure Environment Variables
You need to provide your LLM API keys so the Agent Swarm can function.

1. Copy the template file to create your .env file:
`ash
cp .env.template .env
`
*(On Windows Command Prompt, use copy .env.template .env)*

2. Open the .env file in your favorite text editor and add your API keys (e.g., Groq, OpenAI, or OpenRouter).

## 🐳 Step 3: Spin Up the AI Brain (Docker)
Start the PostgreSQL database, Redis cache, FastAPI backend, and NestJS frontend.

`ash
docker-compose up --build -d
`
> **Note:** The -d flag runs it in the background. To see the logs, you can run docker-compose logs -f.

## 💻 Step 4: Start the Host Executor (Native OS)
The AI Brain is safely isolated in Docker. To allow it to execute approved commands on your actual Windows/Linux desktop, you must run the Host Executor natively.

Open a **new terminal window** on your physical machine and run:

`ash
pip install psutil
python local_executor.py
`
*(Leave this terminal window open! It listens on Port 8003 for approved commands).*

## 🌐 Step 5: Open the UI
Everything is now running! Open your browser and navigate to:

`	ext
http://localhost:3000
`

Try typing: Open Gmail and draft an email to hello@example.com saying I will be late.
"""

# 2. TECH_STACK.md
tech_stack = """# 💻 Tech Stack

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
"""

# 3. DEPLOYMENT.md
deployment = """# 🚀 Deployment Guide

OmniShell's decoupled architecture means you can deploy the **Brain** (Docker) in the cloud, while keeping the **Muscle** (Host Executor) running securely on your local machine.

## ☁️ Cloud Deployment (The Brain & UI)
You can host the Dockerized stack on any VPS (AWS EC2, DigitalOcean, Linode).

1. SSH into your VPS.
2. Clone the repository:
`ash
git clone https://github.com/vishwajitvm/OmniShell.git
cd OmniShell
`
3. Set up your .env file with production API keys.
4. Run Docker Compose:
`ash
docker-compose up --build -d
`
5. Ensure Port 3000 (Frontend) is exposed to the web, or place it behind a reverse proxy like Nginx or Traefik.

## 🔌 Connecting Your Local Machine
If the Brain is in the cloud, how does it control your laptop?

1. You must update the Frontend UI to send execution commands to your localhost:8003, or use a secure tunnel (like **Ngrok** or **Cloudflare Tunnels**) to expose your local executor to your cloud instance.
2. Run the executor natively on your machine:
`ash
python local_executor.py
`

> **⚠️ SECURITY WARNING:** Never expose port 8003 to the public internet without strict authentication. The local_executor.py script has full execution privileges on your host machine.
"""

# 4. ARCHITECTURE.md
architecture = """# 🏗️ Architecture Deep Dive

OmniShell relies on a strict separation of concerns to maintain security while executing AI-generated commands.

## The 4-Agent Syndicate
Within the FastAPI backend, requests are processed by a multi-agent system before any code is generated:
1. **Intent & Planning:** Parses natural language.
2. **Content Generation:** Translates rough notes into URL-encoded, professional text payloads.
3. **Security Guard:** A rigid rule-engine that strips out destructive commands and forces compliance (e.g., downgrading a "send" command to a "draft" command).
4. **Execution Planner:** Maps the finalized intent to either a equires_browser=True Deep Link URL, or a shell_script for local OS execution.

## Docker-to-Host Bridging
Because the FastAPI backend lives inside an isolated Docker network, it cannot natively launch applications on the host Windows/Linux machine. 

To solve this, OmniShell uses an asynchronous bridge:
1. The AI generates the script/URL.
2. The UI intercepts it and triggers a **SweetAlert2** popup for human approval.
3. Upon approval, the UI sends an HTTP POST request to http://localhost:8003.
4. local_executor.py intercepts this on the host machine.
5. On Windows, it uses creationflags=0x00000010 (CREATE_NEW_CONSOLE) to physically pop open a highly visible terminal to execute the command, avoiding Session 0 isolation issues.
"""

# Write files
os.makedirs("docs", exist_ok=True)
with open("docs/LOCAL_SETUP.md", "w", encoding="utf-8") as f: f.write(local_setup)
with open("docs/TECH_STACK.md", "w", encoding="utf-8") as f: f.write(tech_stack)
with open("docs/DEPLOYMENT.md", "w", encoding="utf-8") as f: f.write(deployment)
with open("docs/ARCHITECTURE.md", "w", encoding="utf-8") as f: f.write(architecture)

print("Created all documentation files.")
