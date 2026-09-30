# 🛠️ OmniShell Local Setup & Installation Guide

This guide provides instructions to install, configure, and run OmniShell on your local machine (Linux, macOS, or Windows).

---

## 📋 Prerequisites

Before starting, ensure you have the following installed:
- **[Docker & Docker Compose](https://www.docker.com/)**: For the backend, database, cache, and frontend containers.
- **[Python 3.10+](https://www.python.org/downloads/)**: For running the Native Host Executor Daemon (`local_executor.py`).
- **[Git](https://git-scm.com/)**: For repository cloning and source management.

---

## 🚀 Step-by-Step Setup

### Step 1: Clone the Repository
```bash
git clone https://github.com/vishwajitvm/OmniShell.git
cd OmniShell/saas_poc
```

---

### Step 2: Configure Environment Variables
Copy the template configuration file to create your local `.env`:

```bash
cp .env.template .env
```
*(On Windows Command Prompt, run `copy .env.template .env`)*

Open `.env` and verify your LLM configurations (e.g. OpenAI, Anthropic, Groq, NVIDIA NIM, or Ollama):
```env
# AI / LLM Configuration
LITELLM_MODEL=nvidia/deepseek-ai/deepseek-r1
NVIDIA_NIM_API_KEY=your_api_key_here

# Database & Cache
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=omnishell
REDIS_HOST=redis
REDIS_PORT=6379

# Host Daemon
OMNISHELL_EXECUTOR_URL=http://localhost:8003
```

---

### Step 3: Start the Dockerized AI Stack
Build and start the PostgreSQL database, Redis cache, FastAPI backend, and NestJS frontend:

```bash
docker-compose up --build -d
```

To view live container logs:
```bash
docker-compose logs -f
```

---

### Step 4: Start the Native Host Executor Daemon
Because the backend runs securely inside an isolated Docker container, physical desktop execution (launching apps, opening terminals, inspecting host metrics) is performed by the host daemon.

Open a **new terminal window** on your physical host machine and run:

```bash
# Install host daemon dependencies
pip install psutil

# Start the Host Executor Daemon (runs on port 8003)
python3 local_executor.py
```

> **Note:** Keep this terminal session running. The daemon listens on `http://localhost:8003` and runs background scheduler polls every 2 seconds.

---

### Step 5: Access the Control Center
Open your browser and navigate to:

```text
http://localhost:3000
```

Additional dashboards:
- **Command Center**: [http://localhost:3000](http://localhost:3000)
- **Pipeline & Scheduler Dashboard**: [http://localhost:3000/pipeline](http://localhost:3000/pipeline)
- **Analytics & Telemetry**: [http://localhost:3000/analytics](http://localhost:3000/analytics)
- **Backend Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🧪 Running Automated Tests

To run the automated capabilities and safety test suite:

```bash
python3 -m unittest tests/test_capabilities.py
```
*(32/32 tests should pass with 100% success rate)*
