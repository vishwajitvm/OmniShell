# 🏗️ Architecture Deep Dive

OmniShell relies on a strict separation of concerns to maintain security while executing AI-generated commands.

## The 4-Agent Syndicate
Within the FastAPI backend, requests are processed by a multi-agent system before any code is generated:
1. **Intent & Planning:** Parses natural language.
2. **Content Generation:** Translates rough notes into URL-encoded, professional text payloads.
3. **Security Guard:** A rigid rule-engine that strips out destructive commands and forces compliance (e.g., downgrading a "send" command to a "draft" command).
4. **Execution Planner:** Maps the finalized intent to either a 
equires_browser=True Deep Link URL, or a shell_script for local OS execution.

## Docker-to-Host Bridging
Because the FastAPI backend lives inside an isolated Docker network, it cannot natively launch applications on the host Windows/Linux machine. 

To solve this, OmniShell uses an asynchronous bridge:
1. The AI generates the script/URL.
2. The UI intercepts it and triggers a **SweetAlert2** popup for human approval.
3. Upon approval, the UI sends an HTTP POST request to http://localhost:8003.
4. local_executor.py intercepts this on the host machine.
5. On Windows, it uses creationflags=0x00000010 (CREATE_NEW_CONSOLE) to physically pop open a highly visible terminal to execute the command, avoiding Session 0 isolation issues.
