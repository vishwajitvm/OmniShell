# 🔌 OmniShell API Reference Specification

This document provides the complete API specification for the **OmniShell Backend Engine (`http://localhost:8000`)** and the **Native Host Executor Daemon (`http://localhost:8003`)**.

---

## 📑 API Table of Contents

1. [Backend API Overview (`:8000`)](#1-backend-api-overview-8000)
   - [`POST /generate-workflow`](#post-generate-workflow)
   - [`GET /api/scheduled-tasks`](#get-apischeduled-tasks)
   - [`GET /api/scheduled-tasks/{id}`](#get-apischeduled-tasksid)
   - [`POST /api/scheduled-tasks/{id}/approve`](#post-apischeduled-tasksidapprove)
   - [`POST /api/scheduled-tasks/{id}/deny`](#post-apischeduled-tasksiddeny)
   - [`POST /api/scheduled-tasks/{id}/cancel`](#post-apischeduled-tasksidcancel)
   - [`GET /api/scheduled-tasks/internal/poll`](#get-apischeduled-tasksinternalpoll)
   - [`POST /api/scheduled-tasks/{id}/result`](#post-apischeduled-tasksidresult)
   - [`GET /health`](#get-health)
2. [Native Host Executor Daemon API (`:8003`)](#2-native-host-executor-daemon-api-8003)
   - [`GET /health`](#get-health-host)
   - [`GET /capabilities`](#get-capabilities)
   - [`GET /system/metrics`](#get-systemmetrics)
   - [`GET /browsers`](#get-browsers)
   - [`POST /execute`](#post-execute)
   - [`POST /execute/multi-step`](#post-executemulti-step)
   - [`POST /execute/conditional`](#post-executeconditional)
   - [`POST /notify`](#post-notify)

---

## 1. Backend API Overview (`:8000`)

### `POST /generate-workflow`
Primary entry point for natural language prompts. Dispatches prompt to the 8-Agent Swarm Syndicate, evaluates capabilities, applies security guardrails, and constructs the execution payload.

#### Request Body
```json
{
  "natural_language_prompt": "Open Gmail on Brave and draft an email to team@example.com",
  "user_agent_os": "Linux",
  "local_time": "2026-09-30T03:30:00Z"
}
```

#### Response Body (`MultiAgentResult`)
```json
{
  "capability_type": "browser_operation",
  "direct_answer": null,
  "is_safe": true,
  "target_os": "Linux",
  "requires_browser": true,
  "target_url": "https://mail.google.com/mail/?view=cm&fs=1&to=team%40example.com...",
  "shell_script": "brave-browser 'https://mail.google.com/...' || xdg-open 'https://...'",
  "expected_process": "brave",
  "mermaid_diagram_body": "graph TD\n...",
  "multi_agent_discussion": [
    {
      "agent_name": "Intent & Planning Agent",
      "thought": "Deconstructed prompt..."
    }
  ],
  "timing": {
    "safety": 0.001,
    "llm_reasoning": 0.12,
    "research": 0.00,
    "validation": 0.01,
    "execution": 0.00,
    "total": 0.131
  }
}
```

---

### `GET /api/scheduled-tasks`
Retrieves a paginated list of all active, historic, and recurring scheduled workflows.

#### Query Parameters
- `status` *(optional, string)*: Filter by status (`scheduled`, `awaiting_approval`, `approved`, `completed`, `denied`, `expired`, `failed`).
- `limit` *(optional, integer, default: 50)*: Number of records to return.

---

### `POST /api/scheduled-tasks/{id}/approve`
Validates the cryptographic SHA-256 token and transitions task state to `approved`.

#### Request Body
```json
{
  "token": "dGhpcy1pcy1hLXNlY3VyZS10b2tlbg..."
}
```

#### Response Body
```json
{
  "status": "approved",
  "task_id": 42,
  "message": "Task approved successfully. Host daemon notified."
}
```

---

### `GET /api/scheduled-tasks/internal/poll`
Internal polling endpoint called by the Native Host Executor Daemon every 2 seconds. Performs an atomic lock (`FOR UPDATE SKIP LOCKED`) on tasks where `scheduled_for <= NOW()`.

#### Response Body
```json
{
  "has_due_task": true,
  "task": {
    "id": 42,
    "original_prompt": "Open Spotify after 10 minutes",
    "target_os": "Linux",
    "shell_script": "xdg-open 'https://open.spotify.com'",
    "approval_token": "token_urlsafe_secret_key",
    "status": "awaiting_approval"
  }
}
```

---

## 2. Native Host Executor Daemon API (`:8003`)

### `GET /health` (Host)
Reports host daemon status, active operating system, and supported capabilities count.

#### Response Body
```json
{
  "status": "ok",
  "service": "OmniShell Host Executor",
  "version": "4.0",
  "os": "Linux",
  "port": 8003,
  "capabilities_supported": 19
}
```

---

### `GET /system/metrics`
Collects and streams live hardware telemetry using `psutil`.

#### Response Body
```json
{
  "timestamp": 1790718990.412,
  "os": "Linux",
  "cpu_percent": 14.2,
  "cpu_count": 8,
  "memory": {
    "total_gb": 31.2,
    "available_gb": 22.4,
    "percent_used": 28.2
  },
  "disk": {
    "total_gb": 468.5,
    "free_gb": 312.1,
    "percent_used": 33.4
  }
}
```

---

### `POST /execute`
Executes an approved shell command with stdout/stderr stream piping and process hierarchy verification.

#### Request Body
```json
{
  "command": "python3 --version",
  "expected_process": "python3",
  "timeout_seconds": 30
}
```

#### Response Body
```json
{
  "status": "success",
  "exit_code": 0,
  "stdout": "Python 3.11.9\n",
  "stderr": "",
  "execution_duration_ms": 12.4,
  "process_verified": true
}
```

---

### `POST /notify`
Dispatches a native cross-platform desktop notification banner.

#### Request Body
```json
{
  "title": "OmniShell Reminder",
  "message": "Stand up and drink water."
}
```

#### Response Body
```json
{
  "status": "delivered",
  "notification_id": "notif_89234"
}
```
