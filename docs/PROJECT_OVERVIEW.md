# 🐚 OmniShell - Project Overview

## What is this?
OmniShell is a multi-agent orchestration platform that bridges the gap between Large Language Models (LLMs) and native Operating System execution. 

Typically, AI is stuck inside a chat box. If you ask an AI to "open my downloads folder" or "draft an email", it can only give you instructions on how to do it yourself. OmniShell changes that by utilizing a sophisticated Swarm of Agents that translates your natural language into native executable code or deep-linked URLs, and safely executes them directly on your host machine (Windows or Linux).

## The Architecture Deep Dive
OmniShell is split into three main layers:

### 1. The Frontend UI (NestJS + Handlebars)
A clean, visual interface where the user types their command. This layer is responsible for:
- Displaying the real-time reasoning of the AI agents.
- Rendering the dynamic Mermaid diagrams so the user can visually see the AI's execution plan.
- Popping up **SweetAlert2 Human-in-the-Loop** confirmation dialogues before ANY code touches the host machine.

### 2. The Agentic Backend (FastAPI + Docker)
Running securely inside an isolated Docker container, the Backend receives the prompt and passes it to an intelligent Agent Swarm powered by LiteLLM. The swarm consists of four distinct agents:
*   **Intent & Planning Agent:** Breaks the raw English down into logical steps.
*   **Content Generation Agent:** Expands rough instructions (e.g. "say sorry for missing meeting") into professional, contextual text, and URL-encodes it.
*   **Security Guard:** A strict rule-engine agent. If a user asks to do something destructive (like formatting a drive) or something that violates operational rules (like trying to silently send an email without human review), this agent blocks it or downgrades the intent (e.g., forcing a "Send Email" intent into a "Draft Email" intent).
*   **Execution Planner:** The final architect. It decides if the task requires interacting with a web application (creating a Deep Link URL like https://mail.google.com/mail/?view=cm...) or if it requires a local OS action (writing a robust PowerShell script).

**Infrastructure Support:**
*   **PostgreSQL & Redis:** Maintains execution history, state, and handles rate limiting.
*   **TraceNest Logging:** A dedicated tracing system that logs the exact internal thoughts and decisions of the LLMs for debugging.

### 3. The Native Host Executor (local_executor.py)
Because the backend runs inside an isolated Docker container, it physically cannot open applications on your Windows desktop. We bridge this gap using local_executor.py—a lightweight Python server running natively on your host machine (Port 8003). 
When the Frontend receives the generated script from the AI, it sends it to the Host Executor. The Host Executor uses native Windows APIs (CREATE_NEW_CONSOLE = 0x00000010) to pop open a highly visible, physical terminal window, runs the command, validates the process using psutil, and reports success back to the UI.
