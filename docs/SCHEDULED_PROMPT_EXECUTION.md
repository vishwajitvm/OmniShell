# ⏱️ Scheduled Prompt Execution

## Feature Overview

OmniShell supports fully autonomous scheduling of actions via Natural Language. A user can request to run a command or open a web application at a specific future time. 

Unlike basic web-based reminders, OmniShell's scheduling system is **browser-independent**. You can close the original OmniShell tab entirely, and the native Host Executor (`local_executor.py`) will remain on duty. When the time arrives, it will pop open a completely new, secure approval window on the host machine asking for explicit permission before executing.

### 📝 Example Prompts
- *"Open Spotify in the browser after 10 minutes"*
- *"Run git pull tomorrow at 10 AM"*
- *"Open Gmail at 6 PM"*

## 🏗️ Architecture & Lifecycle

The lifecycle follows a strict sequence to ensure security and prevent unauthorized execution.

![Scheduled Prompt Execution Diagram](diagrams/scheduled_prompt_execution.mmd)

### 1. Intent Resolution (The Brain)
When the user issues a scheduling request:
1. The **7-Agent Syndicate** parses the intent.
2. The agent sets `is_scheduled=true` and calculates the exact `scheduled_time` (UTC).
3. The backend resolves the ENTIRE executable workflow immediately (e.g. converting "Open Spotify" into a browser launch command targeting `https://open.spotify.com`).
4. The workflow is stored in the PostgreSQL `scheduled_tasks` table with a status of `scheduled`.

### 2. The Host Scheduler (The Muscle)
Because browsers can be closed or put to sleep by the OS, scheduling relies on the **Native Host Executor** (`local_executor.py`).
1. A lightweight background thread in the executor polls `/api/scheduled-tasks/internal/poll`.
2. When a task is due (`scheduled_for <= NOW()`), the backend performs an **atomic claim** using a database transaction (`FOR UPDATE SKIP LOCKED`).
3. The backend generates a cryptographically secure, single-use `approval_token`, transitions the task to `awaiting_approval`, and returns the task payload to the executor.

### 3. Human-in-the-Loop (Secure Approval)
Security is paramount. A scheduled task represents an *intent* to ask later, **not** an authorization to execute later.
1. The Host Executor receives the due task and dynamically launches a **NEW** browser window pointing to `http://localhost:3000/scheduled-approval/<token>?taskId=<id>`.
2. This standalone page displays the original intent, action type, payload, and a countdown timer.
3. The user must click **Approve & Execute**. (Denial transitions the task to `denied`).
4. If no action is taken within the configurable timeout (e.g., 300 seconds), the token expires and the task transitions to `expired`.

### 4. Execution & Logging
Once the user clicks approve:
1. The backend API validates the token and sets the state to `approved`.
2. The Host Executor (which is polling for the status change) observes the `approved` state.
3. The Host Executor runs its standard, rigorous security classification (re-verifying the local policy).
4. The command is executed.
5. The `psutil` validation confirms success or failure.
6. The final result is sent to the backend and stored in PostgreSQL, and the status becomes `completed` or `failed`.

## 🗄️ Database Model (`scheduled_tasks`)

- `id`: Primary key
- `original_prompt`: The user's exact input
- `target_os`: Operating System
- `requires_browser`: Boolean flag
- `target_url` / `shell_script`: The resolved payload
- `scheduled_for`: UTC Timestamp
- `status`: Lifecycle state (`scheduled`, `awaiting_approval`, `approved`, `completed`, `denied`, `failed`, `cancelled`, `expired`)
- `approval_token`: Secure one-time use token
- `execution_id`: Foreign key link to the Execution Registry

## 🌐 API Endpoints

- `GET /api/scheduled-tasks`: List active and past tasks
- `GET /api/scheduled-tasks/{id}`: View specific task status
- `POST /api/scheduled-tasks/{id}/cancel`: Cancel a pending task
- `GET /api/scheduled-tasks/internal/poll`: Atomic claim endpoint for the Host Executor
- `POST /api/scheduled-tasks/{id}/approve`: Secure approval endpoint (requires `token`)
- `POST /api/scheduled-tasks/{id}/deny`: Secure denial endpoint (requires `token`)
- `POST /api/scheduled-tasks/{id}/expire`: Marks a timeout
- `POST /api/scheduled-tasks/{id}/result`: Stores execution telemetry

## 🔧 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OMNISHELL_SCHEDULER_ENABLED` | `true` | Toggles the background polling thread in `local_executor.py` |
| `OMNISHELL_SCHEDULER_INTERVAL_SECONDS` | `2` | Polling frequency for due tasks |
| `OMNISHELL_APPROVAL_TIMEOUT_SECONDS` | `300` | How long the user has to approve before the token expires |

