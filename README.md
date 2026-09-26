# 🐚 OmniShell

**OmniShell** is an advanced, multi-agent execution environment that bridges the gap between AI reasoning and your physical operating system. 

Ever wished you could just type *"Open Gmail and draft an apology email for missing the meeting"* and have your computer actually do it for you? That's what OmniShell does. It translates natural language into secure, native OS execution and advanced web automation.

## 🤔 Why this project? What does it solve?
Most AI tools today (like ChatGPT) are trapped in a chat box. They can tell you *how* to do something, but they can't do it for you. Tools like AutoGPT attempt to solve this, but they are often highly dangerous, prone to breaking, and execute commands blindly in the background without user consent.

**OmniShell solves this by combining the power of AI with strict Human-in-the-Loop security.** 
It uses a "Swarm" of specialized agents to plan out your request, but before a single line of code touches your computer, the UI halts and asks for your explicit permission. When it executes, it does so in a highly visible, native terminal window so you can see exactly what is happening. No background shadow processes, no blind executions.

## 🧠 How it works (In Layman's Terms)

![System Architecture](https://mermaid.ink/img/Z3JhcGggVEQ7CiAgICAlJSBDb3JlIFVzZXJzICYgSW50ZXJmYWNlcwogICAgVXNlcigoVXNlcikpIC0tPnxOYXR1cmFsIExhbmd1YWdlfCBVSVtGcm9udGVuZCBVSSAtIE5lc3RKU10KICAgIFVJIC0tPnxIVFRQIFBPU1R8IEJhY2tlbmRbQmFja2VuZCBBUEkgLSBGYXN0QVBJXQoKICAgICUlIEluZnJhc3RydWN0dXJlICYgVHJhY2luZwogICAgQmFja2VuZCAtLi0+fExvZ3MgQWdlbnQgVGhvdWdodHN8IFRyYWNlTmVzdFsoVHJhY2VOZXN0IExvZ2dlcildCiAgICBCYWNrZW5kIC0uLT58Q2FjaGVzIFN0YXRlfCBSZWRpc1soUmVkaXMgQ2FjaGUpXQogICAgQmFja2VuZCAtLi0+fFNhdmVzIEhpc3Rvcnl8IFBvc3RncmVzWyhQb3N0Z3JlU1FMIERCKV0KCiAgICAlJSBBZ2VudCBTd2FybSAoVGhlIFN5bmRpY2F0ZSkKICAgIHN1YmdyYXBoIEFnZW50IFN3YXJtCiAgICAgICAgQmFja2VuZCAtLT4gSW50ZW50UGxhblsxLiBJbnRlbnQgJiBQbGFubmluZyBBZ2VudF0KICAgICAgICBJbnRlbnRQbGFuIC0tPiBDb250ZW50R2VuWzIuIENvbnRlbnQgR2VuZXJhdGlvbiBBZ2VudF0KICAgICAgICBDb250ZW50R2VuIC0tPiBTZWNHdWFyZFszLiBTZWN1cml0eSBHdWFyZF0KICAgICAgICBTZWNHdWFyZCAtLT4gRXhlY1BsYW5uZXJbNC4gRXhlY3V0aW9uIFBsYW5uZXJdCiAgICBlbmQKCiAgICAlJSBTZWN1cml0eSBMb2dpYwogICAgU2VjR3VhcmQgLS0+fE1hbGljaW91cyAvIERlc3RydWN0aXZlfCBCbG9jaygoQkxPQ0tFRCkpCiAgICBTZWNHdWFyZCAtLi0+fERvd25ncmFkZXMgJ1NlbmQnIHRvICdEcmFmdCd8IEV4ZWNQbGFubmVyCgogICAgJSUgRXhlY3V0aW9uIFJvdXRpbmcKICAgIEV4ZWNQbGFubmVyIC0tPnxEZWNpc2lvbjogV2ViL1VSTD98IFdlYlRhc2tbcmVxdWlyZXNfYnJvd3Nlcj1UcnVlXQogICAgRXhlY1BsYW5uZXIgLS0+fERlY2lzaW9uOiBMb2NhbCBPUz98IExvY2FsVGFza1tzaGVsbF9zY3JpcHQ9R2VuZXJhdGVkIENvZGVdCgogICAgV2ViVGFzayAtLT4gRG9ja2VyQnJpZGdle0RvY2tlci10by1Ib3N0IEJyaWRnZX0KICAgIExvY2FsVGFzayAtLT4gRG9ja2VyQnJpZGdlCgogICAgJSUgSG9zdCBFeGVjdXRpb24KICAgIHN1YmdyYXBoIE5hdGl2ZSBIb3N0IE1hY2hpbmUKICAgICAgICBEb2NrZXJCcmlkZ2UgLS0+fFBvcnQgODAwM3wgTG9jYWxFeGVjdXRvcltsb2NhbF9leGVjdXRvci5weV0KICAgICAgICBMb2NhbEV4ZWN1dG9yIC0tPnxXZWIgVGFza3wgT3BlbkJyb3dzZXJbUG9wIE9wZW4gQnJvd3NlciBOYXRpdmVdCiAgICAgICAgTG9jYWxFeGVjdXRvciAtLT58TG9jYWwgVGFza3wgT3BlblRlcm1pbmFsW0NSRUFURV9ORVdfQ09OU09MRSBwb3B1cF0KICAgICAgICBPcGVuVGVybWluYWwgLS0+IFZhbGlkYXRpb25bcHN1dGlsIFZhbGlkYXRpb246IERpZCBpdCBsYXVuY2g/XQogICAgICAgIE9wZW5Ccm93c2VyIC0tPiBWYWxpZGF0aW9uCiAgICBlbmQKCiAgICBWYWxpZGF0aW9uIC0tPnxWYWxpZGF0aW9uIE91dHB1dHwgVUkK)

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

![Gmail Example Diagram](https://mermaid.ink/img/Z3JhcGggVEQ7CiAgICAlJSBUaGUgU3BlY2lmaWMgR21haWwgRXhhbXBsZQogICAgUHJvbXB0Wy8iUHJvbXB0OiBvcGVuIGdtYWlsIG9uIGJyYXZlIGJyb3dzZXIgYW5kIGRyYWZ0IGFuIGVtYWlsIHRvIHdvbHZlcmluZXZtMDAxQGdtYWlsLmNvbSBhbmQgd3JpdGUgbWVzc2FnZSB0aGF0IGkgY2Fubm90IGJlIGFibGUgdG8gam9pbiBtZWV0aW5nIHRvZGF5Ii9dIC0tPiBJbnRlbnRBZ2VudFtJbnRlbnQgJiBQbGFubmluZyBBZ2VudF0KCiAgICBzdWJncmFwaCBBZ2VudGljIEJyZWFrZG93bgogICAgICAgIEludGVudEFnZW50IC0tPnxCcmVha3MgaW50byBzdGVwc3wgU3RlcDFbU3RlcCAxOiBPcGVuIEJyb3dzZXJdCiAgICAgICAgSW50ZW50QWdlbnQgLS0+IFN0ZXAyW1N0ZXAgMjogRHJhZnQgRW1haWwgdG8gd29sdmVyaW5ldm0wMDFAZ21haWwuY29tXQogICAgICAgIEludGVudEFnZW50IC0tPiBTdGVwM1tTdGVwIDM6IEFwb2xvZ3kgbWVzc2FnZSBmb3IgbWlzc2luZyBtZWV0aW5nXQogICAgICAgIAogICAgICAgIFN0ZXAzIC0tPiBDb250ZW50QWdlbnRbQ29udGVudCBHZW5lcmF0aW9uIEFnZW50XQogICAgICAgIENvbnRlbnRBZ2VudCAtLT58R2VuZXJhdGVzIFByb2Zlc3Npb25hbCBUZXh0fCBCb2R5VGV4dFsiRGVhciB0ZWFtLCBJIGFwb2xvZ2l6ZSBidXQgSSB3aWxsIG5vdCBiZSBhYmxlIHRvIGpvaW4gdG9kYXkncyBtZWV0aW5nLiBSZWdhcmRzLiJdCiAgICAgICAgQ29udGVudEFnZW50IC0tPnxVUkwgRW5jb2RlcyBEYXRhfCBFbmNvZGVkQm9keVsiRGVhciUyMHRlYW0lMkMlMjBJJTIwYXBvbG9naXplLi4uIl0KICAgICAgICAKICAgICAgICBFbmNvZGVkQm9keSAtLT4gU2VjR3VhcmRbU2VjdXJpdHkgR3VhcmQgQWdlbnRdCiAgICAgICAgU3RlcDIgLS0+IFNlY0d1YXJkCiAgICBlbmQKCiAgICBzdWJncmFwaCBTZWN1cml0eSBDaGVjawogICAgICAgIFNlY0d1YXJkIC0tPnxDaGVja3MgZm9yICdTZW5kJyBjb21tYW5kfCBDaGVja1NlbmR7RGlkIHVzZXIgc2F5IFNlbmQ/fQogICAgICAgIENoZWNrU2VuZCAtLT58Tm8sIGp1c3QgZHJhZnR8IFNhZmVbU3RhdHVzOiBTQUZFXQogICAgICAgIENoZWNrU2VuZCAtLT58WWVzfCBCbG9ja1NlbmRbR3VhcmRyYWlsOiBEb3duZ3JhZGUgdG8gRHJhZnRdCiAgICAgICAgU2FmZSAtLT4gRXhlY1BsYW5uZXJbRXhlY3V0aW9uIFBsYW5uZXIgQWdlbnRdCiAgICBlbmQKCiAgICBzdWJncmFwaCBGaW5hbCBBc3NlbWJseQogICAgICAgIEV4ZWNQbGFubmVyIC0tPnxCdWlsZHMgRGVlcCBMaW5rIFVSTHwgRmluYWxVUkxbImh0dHBzOi8vbWFpbC5nb29nbGUuY29tL21haWwvP3ZpZXc9Y20mZnM9MSZ0bz13b2x2ZXJpbmV2bTAwMUBnbWFpbC5jb20mc3U9TWVldGluZyZib2R5PURlYXIlMjB0ZWFtLi4uIl0KICAgICAgICBGaW5hbFVSTCAtLT4gT3V0cHV0SlNPTlsiSlNPTjogeyByZXF1aXJlc19icm93c2VyOiB0cnVlLCB0YXJnZXRfdXJsOiAnLi4uJyB9Il0KICAgIGVuZAoKICAgIHN1YmdyYXBoIEV4ZWN1dGlvbgogICAgICAgIE91dHB1dEpTT04gLS0+IE1pZGRsZXdhcmVbQWdlbnRpYyBNaWRkbGV3YXJlXQogICAgICAgIE1pZGRsZXdhcmUgLS0+fERldGVjdHMgcmVxdWlyZXNfYnJvd3NlcnwgVUlSb3V0ZXJbRnJvbnRlbmQgVUkgUm91dGVyXQogICAgICAgIFVJUm91dGVyIC0tPnxBc2tzIGZvciBIdW1hbiBBcHByb3ZhbHwgU3dlZXRBbGVydHtTd2VldEFsZXJ0IFBvcHVwfQogICAgICAgIAogICAgICAgIFN3ZWV0QWxlcnQgLS0+fERlbmllZHwgQ2FuY2VsKChBY3Rpb24gQ2FuY2VsbGVkKSkKICAgICAgICBTd2VldEFsZXJ0IC0tPnxBcHByb3ZlZDogU2VsZWN0cyBCcmF2ZXwgSG9zdEFQSVtQT1NUIGh0dHA6Ly9sb2NhbGhvc3Q6ODAwMy9leGVjdXRlXQogICAgICAgIEhvc3RBUEkgLS0+IExvY2FsUHlbbG9jYWxfZXhlY3V0b3IucHkgb24gSG9zdF0KICAgICAgICBMb2NhbFB5IC0tPiBCcmF2ZUxhdW5jaFtTdGFydC1Qcm9jZXNzICdicmF2ZScgLUFyZ3VtZW50TGlzdCAnaHR0cHM6Ly9tYWlsLmdvb2dsZS5jb20vLi4uJ10KICAgICAgICBCcmF2ZUxhdW5jaCAtLT4gVUlbVXNlciBzZWVzIHByZS1kcmFmdGVkIGVtYWlsIGluIEJyYXZlIV0KICAgIGVuZAo=)


