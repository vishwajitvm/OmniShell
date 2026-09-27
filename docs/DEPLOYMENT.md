# 🚀 Deployment Guide

OmniShell's decoupled architecture means you can deploy the **Brain** (Docker) in the cloud, while keeping the **Muscle** (Host Executor) running securely on your local machine.

## ☁️ Cloud Deployment (The Brain & UI)
You can host the Dockerized stack on any VPS (AWS EC2, DigitalOcean, Linode).

1. SSH into your VPS.
2. Clone the repository:
`ash
git clone https://github.com/vishwajitvm/OmniShell.git
cd OmniShell
`
3. Set up your .env file with production API keys.
4. Run Docker Compose:
`ash
docker-compose up --build -d
`
5. Ensure Port 3000 (Frontend) is exposed to the web, or place it behind a reverse proxy like Nginx or Traefik.

## 🔌 Connecting Your Local Machine
If the Brain is in the cloud, how does it control your laptop?

1. You must update the Frontend UI to send execution commands to your localhost:8003, or use a secure tunnel (like **Ngrok** or **Cloudflare Tunnels**) to expose your local executor to your cloud instance.
2. Run the executor natively on your machine:
`ash
python local_executor.py
`

> **⚠️ SECURITY WARNING:** Never expose port 8003 to the public internet without strict authentication. The local_executor.py script has full execution privileges on your host machine.
