import re

with open('README.md', 'r', encoding='utf-8') as f:
    readme = f.read()

# I will cleanly rewrite the entire Setup section
setup_text = '''## 🚀 Setup & Installation

### Prerequisites
- Docker & Docker Compose
- Python 3.10+ (Installed natively on your host machine)
- A GitHub/LiteLLM compatible API key (configured in your .env file)

### Step-by-Step

1. **Clone the repository:**
`ash
git clone https://github.com/vishwajitvm/OmniShell.git
cd OmniShell
`

2. **Start the AI Brain & UI (Docker):**
This spins up the secure Backend API, the Redis cache, the Postgres Database, and the Frontend UI.
`ash
docker-compose up --build -d
`

3. **Start the Muscle (Native Host Executor):**
Open a terminal natively on your Windows/Linux machine (NOT inside Docker) and run:
`ash
pip install psutil
python local_executor.py
`
*(Leave this window open! This is what listens for approved commands from the UI and executes them on your desktop).*

4. **Access the UI:**
Open your browser and navigate to http://localhost:3000. Type your command and watch OmniShell go to work!
'''

# Find everything between "## 🚀 Setup & Installation" and "## 📚 Deep Dive Documentation"
readme = re.sub(r'## 🚀 Setup & Installation.*?## 📚 Deep Dive Documentation', setup_text + '\n## 📚 Deep Dive Documentation', readme, flags=re.DOTALL)

with open('README.md', 'w', encoding='utf-8') as f:
    f.write(readme)

print("Rewrote setup section cleanly.")
