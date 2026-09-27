import re

with open('README.md', 'r', encoding='utf-8') as f:
    readme = f.read()

# Add links to the new files at the bottom
new_links = """## 📚 Deep Dive Documentation
Want to see the exact architecture flowcharts or how the agent swarm works under the hood? Check out the /docs folder!

### Guides & Technicals
- [🛠️ Local Setup Guide (Step-by-Step)](docs/LOCAL_SETUP.md)
- [💻 Tech Stack Breakdown](docs/TECH_STACK.md)
- [🏗️ Architecture Deep Dive](docs/ARCHITECTURE.md)
- [🚀 Deployment Guide](docs/DEPLOYMENT.md)

### Flowcharts & Diagrams
- [Project Overview](docs/PROJECT_OVERVIEW.md)
- [System Architecture Diagram](docs/diagrams/architecture.mmd)
- [Example Flow: Complex Gmail Deep Linking](docs/diagrams/example_gmail_flow.mmd)
"""

readme = re.sub(r'## 📚 Deep Dive Documentation.*', new_links, readme, flags=re.DOTALL)

with open('README.md', 'w', encoding='utf-8') as f:
    f.write(readme)

print("Updated README.md")
