with open("backend/main.py", "r") as f:
    text = f.read()

old_mermaid = """    CRITICAL MERMAID RULES:
    Generate a HIGHLY DETAILED, NON-LINEAR flowchart mapping the exact agent architecture. 
    DO NOT just make a single straight line! Show parallel processes, decision trees, and data flows.
    DO NOT include 'graph TD;' at the start (the frontend will prepend it).
    Example of a safe detailed graph using ONLY brackets for shapes:
    Prompt[User Prompt] --> IntentPlan[Intent & Planning Agent]
    IntentPlan --> ContentGen[Content Generation Agent]
    IntentPlan --> SecGuard[Security Guard]
    ContentGen -.->|Drafts Body| ExecPlanner[Execution Planner]
    SecGuard -.->|Blocks Send| ExecPlanner
    ExecPlanner --> WebNode[Deep Link URL]
    ExecPlanner --> ShellNode[Shell Script]
    WebNode --> HostEngine[Host Execution]
    ShellNode --> HostEngine
    HostEngine --> Validator[Process Validation]
    Validator --> UI[Frontend UI]"""

new_mermaid = """    CRITICAL MERMAID RULES:
    You MUST generate a HIGHLY DETAILED, NON-LINEAR flowchart mapping the EXACT architecture and decision process for THIS specific task.
    DO NOT just make a single straight line! 
    - Show conditional decision trees (using diamond shapes {} for decisions).
    - Show parallel processing where multiple agents work at once.
    - Specifically label edges with WHAT the agent did or concluded (e.g., -->|Generated Draft Text|).
    DO NOT include 'graph TD;' at the start (the frontend will prepend it).
    Use safe Mermaid syntax: ALWAYS quote labels if they have spaces or special characters (e.g., NodeID["Text goes here"]).
    
    Example of an advanced graph:
    User["User Prompt"] --> Swarm["Agent Swarm Spawned"]
    Swarm -->|Step 1| IntentPlan["Intent Agent: Broke into multiple steps"]
    Swarm -->|Step 2| SysRecon["Recon Agent: Identified Linux text editors"]
    Swarm -->|Step 3| ContentGen["Content Agent: Wrote 5 lines about friend"]
    IntentPlan --> SecGuard{"Security Guard: Is it malicious?"}
    SysRecon --> CommandRes["Command Research: Found Bash Loop syntax"]
    ContentGen --> CommandRes
    SecGuard -->|No, Safe| ExecPlanner["Execution Planner: Assembled final script"]
    SecGuard -->|Yes, Block| Abort["Abort Operation"]
    CommandRes --> ExecPlanner
    ExecPlanner --> ShellNode["Bash Script Output"]
    ShellNode --> HostEngine["Host Execution"]"""

if old_mermaid in text:
    text = text.replace(old_mermaid, new_mermaid)
else:
    print("Could not find old mermaid string")

with open("backend/main.py", "w") as f:
    f.write(text)
