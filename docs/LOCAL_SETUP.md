# 🛠️ Local Setup Guide

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
```

## ⚙️ Step 2: Configure Environment Variables
You need to provide your LLM API keys so the Agent Swarm can function.

1. Copy the template file to create your .env file:
`ash
cp .env.template .env
```
*(On Windows Command Prompt, use copy .env.template .env)*

2. Open the .env file in your favorite text editor and add your API keys (e.g., Groq, OpenAI, or OpenRouter).

## 🐳 Step 3: Spin Up the AI Brain (Docker)
Start the PostgreSQL database, Redis cache, FastAPI backend, and NestJS frontend.

`ash
docker-compose up --build -d
```
> **Note:** The -d flag runs it in the background. To see the logs, you can run docker-compose logs -f.

## 💻 Step 4: Start the Host Executor V2 (Native OS)
The AI Brain is safely isolated in Docker. To allow it to execute approved commands on your actual Windows/Linux desktop, you must run the Host Executor natively.

Open a **new terminal window** on your physical machine and run:

```bash
pip install psutil
python local_executor.py
```
*(Leave this terminal window open! It listens on Port 8003 for approved commands. The V2 executor runs safely in the background.)*

## 🌐 Step 5: Open the UI
Everything is now running! Open your browser and navigate to:

```text
http://localhost:3000
```

Try typing: Open Gmail and draft an email to hello@example.com saying I will be late.
