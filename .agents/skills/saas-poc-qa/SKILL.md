---
name: saas-poc-qa
description: >-
  Use this skill to identify bugs, improve the system architecture, and test the saas_poc project.
---

# SaaS POC QA and Improvement Protocol

Follow these steps strictly to improve and test the `saas_poc` project.

## Step 1: Identify Flaws and Bugs
Analyze the current codebase (`backend/main.py`, `frontend/src/app/page.tsx`) to identify potential bugs. 
Look for:
- Missing error boundary/fallback in the frontend if the Mermaid diagram syntax is invalid.
- Missing timeout handling in the frontend fetch request.
- Inefficient or blocking code in the FastAPI backend.
- Lack of detailed logging for troubleshooting API key failures.

## Step 2: Implement Fixes
Apply the necessary code improvements:
1. **Backend Improvements:** 
   - Add proper Python `logging` to `main.py` instead of raw `print` statements.
   - Improve the exception handling in the fallback loop to log the exact failure reason clearly.
2. **Frontend Improvements:** 
   - Add robust error handling to `page.tsx` for network timeouts or invalid JSON responses.
   - Add a fallback mechanism if Mermaid fails to render a hallucinated diagram syntax.

## Step 3: Test and Validate
1. Rebuild the affected Docker containers using `docker-compose up -d --build`.
2. Validate the backend health check endpoint via the browser or `curl`.
3. Deploy a browser subagent to verify the frontend correctly renders the workflow and handles errors smoothly.
