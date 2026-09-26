# 🐚 OmniShell

**OmniShell** is an advanced, multi-agent execution environment that bridges the gap between AI reasoning and your physical operating system. 

Ever wished you could just type *"Open Gmail and draft an apology email for missing the meeting"* and have your computer actually do it for you? That's what OmniShell does. It translates natural language into secure, native OS execution and advanced web automation.

## 🤔 Why this project? What does it solve?
Most AI tools today (like ChatGPT) are trapped in a chat box. They can tell you *how* to do something, but they can't do it for you. Tools like AutoGPT attempt to solve this, but they are often highly dangerous, prone to breaking, and execute commands blindly in the background without user consent.

**OmniShell solves this by combining the power of AI with strict Human-in-the-Loop security.** 
It uses a "Swarm" of specialized agents to plan out your request, but before a single line of code touches your computer, the UI halts and asks for your explicit permission. When it executes, it does so in a highly visible, native terminal window so you can see exactly what is happening. No background shadow processes, no blind executions.

## 🧠 How it works (In Layman's Terms)
When you type a command, it goes through three stages:

1. **The Brain (Agent Swarm):** Your command is sent to a secure Docker container where 4 AI agents argue about how to fulfill it. 
   - *Agent 1* figures out what you want.
   - *Agent 2* writes any necessary text (like making your rough email notes sound professional).
   - *Agent 3 (Security Guard)* makes sure you aren't trying to do something dangerous, and stops the AI from doing things like sending emails without your final click.
   - *Agent 4* writes the final PowerShell script or Web Deep-Link.
2. **The Checkpoint (UI):** The website shows you exactly what the AI planned. It draws a nice flowchart of their thoughts and gives you a "Yes/No" popup.
3. **The Muscle (Host Executor):** If you click Yes, the command is sent to a tiny script running on your actual computer. This script physically pops open a new terminal window, runs the task (like opening VS Code, or launching Brave Browser to Gmail), double checks that it worked, and then closes itself.

## 🚀 Setup & Installation

### Prerequisites
- Docker & Docker Compose
- Python 3.10+ (Installed natively on your host machine)
- A GitHub/LiteLLM compatible API key (configured in your .env file)

### Step-by-Step

1. **Clone the repository:**
   \\\ash
   git clone https://github.com/vishwajitvm/OmniShell.git
   cd OmniShell
   \\\

2. **Start the AI Brain & UI (Docker):**
   This spins up the secure Backend API, the Redis cache, the Postgres Database, and the Frontend UI.
   \\\ash
   docker-compose up --build -d
   \\\

3. **Start the Muscle (Native Host Executor):**
   Open a terminal natively on your Windows/Linux machine (NOT inside Docker) and run:
   \\\ash
   pip install psutil
   python local_executor.py
   \\\
   *(Leave this window open! This is what listens for approved commands from the UI and executes them on your desktop).*

4. **Access the UI:**
   Open your browser and navigate to http://localhost:3000. Type your command and watch OmniShell go to work!

## 📚 Deep Dive Documentation
Want to see the exact architecture flowcharts or how the agent swarm works under the hood? Check out the /docs folder!
- [Project Overview & Architecture Details](docs/PROJECT_OVERVIEW.md)
- [System Architecture Flowchart](docs/diagrams/architecture.mmd)
- [Example Flow: Complex Gmail Deep Linking](docs/diagrams/example_gmail_flow.mmd)

