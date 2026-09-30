# 🔧 OmniShell Operational Runbook & Troubleshooting Guide

This guide provides step-by-step diagnostic and remediation procedures for common operational issues encountered in OmniShell.

---

## 🚨 Common Issues Quick Reference

| Issue / Symptom | Probable Cause | Quick Fix |
|---|---|---|
| **Host Executor Offline Badge in UI** | `local_executor.py` is not running on port 8003 | Run `python3 local_executor.py` in a physical terminal |
| **Command Fails: `docker-compose not found`** | Docker Compose v2 uses `docker compose` | Use `docker compose up -d` |
| **Scheduled Window Doesn't Pop Up** | Browser pop-up blocker or daemon stopped | Allow popups on `localhost:3000` & check daemon logs |
| **LLM Model Error / Timeout** | API key missing or provider rate limit | Check `.env` and verify fallback model list |
| **Desktop Notifications Not Showing** | Missing `libnotify-bin` (Linux) or focus mode | Run `sudo apt install libnotify-bin` |

---

## 1. 💻 Host Executor Connection Troubleshooting (`:8003`)

### Symptom: UI displays "(Host Executor offline)"
1. Check if the daemon process is active:
   ```bash
   curl http://localhost:8003/health
   ```
2. If unreachable, launch the daemon natively on your physical OS:
   ```bash
   pip install psutil
   python3 local_executor.py
   ```
3. Check for port conflicts (ensure no other process is bound to port 8003):
   ```bash
   lsof -i :8003 || netstat -tuln | grep 8003
   ```

---

## 2. 🐳 Docker Stack & Database Diagnostics

### Inspect Container Health:
```bash
docker compose ps
```
Ensure all four containers report `healthy` or `running`:
- `saas_poc-backend-1` (Port 8000)
- `saas_poc-frontend-1` (Port 3000)
- `saas_poc-postgres-1` (Port 5432)
- `saas_poc-redis-1` (Port 6379)

### Check Backend Logs:
```bash
docker compose logs -f backend
```

### Reset PostgreSQL Database / Scheduled Tasks:
If database migrations or locked scheduled tasks need resetting:
```bash
docker compose down -v
docker compose up --build -d
```

---

## 3. 🌐 Browser Pop-up & Deep-Link Debugging

### Scheduled Approval Window Does Not Open Automatically
1. Ensure your browser allows pop-ups for `http://localhost:3000`.
2. Check `local_executor.py` terminal output for `[Scheduler] Due task detected... Opening approval window`.
3. If blocked by the OS, open the manual URL printed in the terminal:
   ```text
   http://localhost:3000/scheduled-approval/<token>?taskId=<id>
   ```

---

## 4. 🔔 Desktop Notification Setup by OS

- **Linux (Ubuntu / Debian / Arch)**:
  Ensure `notify-send` is installed:
  ```bash
  sudo apt install libnotify-bin
  ```
- **macOS**:
  Ensure Terminal / Python has permission under **System Preferences → Notifications**.
- **Windows**:
  Ensure PowerShell notifications are permitted in **Settings → System → Notifications**.

---

## 5. 🧪 Running System Diagnostic Tests

To verify that all 19 capabilities, scheduling calculations, and guardrails are working correctly:

```bash
python3 -m unittest tests/test_capabilities.py
```
*(Expected output: `Ran 32 tests ... OK`)*
