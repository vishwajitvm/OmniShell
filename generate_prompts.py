#!/usr/bin/env python3
import json

CATEGORIES = {
    "Q&A & Knowledge": {
        "icon": "💬",
        "badge": "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
        "prompts": [
            "What is the capital of India and its major historical landmarks?",
            "What is the capital of Maharashtra and its major historical landmarks?",
            "What is the capital of France and its most famous monuments?",
            "What is the capital of Japan and its major cultural heritage sites?",
            "What is the capital of the United States and its major landmarks?",
            "What is the capital of Germany and its historical landmarks?",
            "What is the capital of the United Kingdom and its iconic monuments?",
            "What is the capital of Italy and its famous ancient landmarks?",
            "What is the capital of Australia and its government institutions?",
            "What is the capital of Canada and its prominent cultural sites?",
            "What is the capital of Karnataka and why is it known as the Silicon Valley of India?",
            "What is the capital of Tamil Nadu and its famous Dravidian architectural landmarks?",
            "What is the capital of Gujarat and its major historical monuments?",
            "What is the capital of Rajasthan and its famous royal palaces?",
            "What is the capital of West Bengal and its colonial heritage landmarks?",
            "Explain how Docker containers work and the difference between images and containers",
            "What are the ACID properties in database management systems and why are they important?",
            "Explain the difference between Kubernetes Deployment, StatefulSet, and DaemonSet",
            "How does the Linux Completely Fair Scheduler (CFS) allocate CPU runtime?",
            "What is the difference between REST, GraphQL, and gRPC APIs?",
            "Explain the TCP 3-way handshake and 4-way termination process",
            "What is the difference between synchronous and asynchronous I/O in Node.js?",
            "Explain how Git stores objects internally using blobs, trees, and commits",
            "What are JWT tokens, how do they work, and what are their security vulnerabilities?",
            "Explain Kafka architecture, topics, partitions, and consumer groups",
            "Calculate compound interest on $10,000 at 8% annual return compounded annually over 5 years",
            "Calculate the monthly payment on a $300,000 mortgage at 6.5% interest over 30 years",
            "What is the difference between Process and Thread in operating systems?",
            "Explain how Redis achieves sub-millisecond latency and in-memory persistence",
            "What are the differences between symmetric and asymmetric encryption?"
        ]
    },
    "System Diagnostics": {
        "icon": "🔍",
        "badge": "bg-sky-500/10 text-sky-300 border-sky-500/30",
        "prompts": [
            "Inspect current system memory, RAM distribution, and CPU load utilization",
            "Inspect all listening TCP/UDP ports and active network socket connections",
            "Check disk space usage, root partition capacity, and filesystem mount points",
            "List top 10 memory-consuming processes sorted by resident memory size",
            "List top 10 CPU-consuming processes sorted by processor utilization",
            "Inspect system uptime, OS kernel release version, and host hostname",
            "Inspect network interfaces, assigned IP addresses, and routing table",
            "Check swap memory allocation, active swap partitions, and swap usage",
            "Inspect hardware CPU model, core count, thread count, and cache sizes",
            "Check available disk inodes and usage across all mounted filesystems",
            "Inspect active systemd service units and check for any failed services",
            "Inspect system thermal zones and CPU temperature sensors",
            "Check battery status, charging level, and power draw metrics",
            "Inspect currently logged-in users and recent system login history",
            "Inspect open file descriptors and system-wide file handle limits",
            "Check DNS resolver configuration in /etc/resolv.conf and ping gateway",
            "Inspect kernel ring buffer logs for critical hardware or driver errors",
            "Check status and resource consumption of local Docker containers",
            "Inspect local firewall rules and open iptables/ufw filter chains",
            "Inspect shared memory segments and IPC message queues",
            "Check disk I/O performance and read/write throughput statistics",
            "Inspect PCI bus devices, graphics controller, and NVMe drives",
            "Inspect USB connected peripherals and bus device hierarchy",
            "Check current system timezone, local time, and NTP sync status",
            "Inspect available virtual memory and dirty page writeback statistics",
            "Check zombie and defunct processes count in current process tree",
            "Inspect system limits for maximum user processes and open files",
            "Check system load average over 1, 5, and 15 minute windows",
            "Inspect host architecture, glibc version, and default system shell",
            "Check network socket connection states: ESTABLISHED, TIME_WAIT, LISTEN"
        ]
    },
    "Browser & Web": {
        "icon": "🌐",
        "badge": "bg-cyan-500/10 text-cyan-300 border-cyan-500/30",
        "prompts": [
            "open gmail on brave browser and draft an email to wolverinevm001@gmail.com with subject Internal Call with Team and body I cannot be able to join meeting today",
            "Open Brave browser to https://github.com/vishwajitvm",
            "Open Brave browser and search for latest AI agent frameworks on Google",
            "Open YouTube Music on Brave browser and search for Lo-Fi Beats",
            "Open Google Chrome and search for Kubernetes production best practices",
            "Open Firefox and navigate to https://news.ycombinator.com",
            "Open Brave browser and navigate to https://hub.docker.com",
            "Open Chrome browser to https://developer.mozilla.org/en-US/docs/Web/JavaScript",
            "Open Brave browser to Python official documentation at https://docs.python.org/3/",
            "Open Brave browser to FastAPI documentation at https://fastapi.tiangolo.com",
            "Open Brave browser to Next.js documentation at https://nextjs.org/docs",
            "Open Brave browser and search on GitHub for open source LLM orchestration tools",
            "Open Brave browser and open speedtest at https://fast.com",
            "Open Brave browser to https://stackoverflow.com/questions",
            "Open Brave browser and search for NestJS microservices architecture",
            "Open Brave browser to Tailwind CSS documentation at https://tailwindcss.com/docs",
            "Open Brave browser to PostgreSQL official documentation at https://www.postgresql.org/docs/",
            "Open Brave browser to Redis documentation at https://redis.io/docs/",
            "Open Brave browser and navigate to https://arxiv.org/list/cs.AI/recent",
            "Open Brave browser to https://www.kernel.org",
            "Open Brave browser and search YouTube for Docker Compose multi-container tutorial",
            "Open Brave browser and search Google for Linux performance tuning with sysctl",
            "Open Brave browser to TypeScript Handbook at https://www.typescriptlang.org/docs/",
            "Open Brave browser to https://dev.to for trending software engineering articles",
            "Open Brave browser to https://crates.io for Rust package registry",
            "Open Brave browser to https://pypi.org for Python Package Index",
            "Open Brave browser to https://www.npmjs.com for Node.js package search",
            "Open Brave browser and search Google for Vite React Tailwind CSS setup guide",
            "Open Brave browser to Grafana documentation at https://grafana.com/docs/",
            "Open Brave browser to Prometheus monitoring docs at https://prometheus.io/docs/"
        ]
    },
    "App & Host Operations": {
        "icon": "🚀",
        "badge": "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
        "prompts": [
            "Open Visual Studio Code in current project directory",
            "Open native calculator application on host machine",
            "Open text editor and create a new scratchpad document",
            "Open terminal window on host machine",
            "Open file manager application in current working folder",
            "Open system performance monitor on host machine",
            "Check if Docker service daemon is currently running on the host",
            "Check which Python and Node.js versions are installed on my host",
            "Inspect installed Git version and configured global git user email",
            "Check if Rust compiler rustc and Cargo package manager are installed",
            "Check if Go programming language compiler is installed on host",
            "Inspect installed GCC and G++ compiler toolchain versions",
            "Check if Nginx web server binary is available on host machine",
            "Check if PostgreSQL client psql binary is available in PATH",
            "Check if Redis CLI tool redis-cli is installed and accessible",
            "Check if JQ JSON command-line processor is installed on host",
            "Check if cURL and Wget HTTP utility binaries are installed",
            "Inspect active shell environment variables in current user session",
            "Inspect user identity, UID, GID, and assigned secondary groups",
            "Check default desktop environment and window manager on Linux host",
            "Inspect current user home directory path and available quota",
            "Check all installed package managers (apt, snap, flatpak, pip, npm)",
            "Check if OpenSSH client and SSH agent daemon are currently running",
            "Inspect available locales and language encoding configuration",
            "Check system hostname resolution and localhost alias entries",
            "Check if Tmux or Screen terminal multiplexers are installed",
            "Check if Make and CMake build utilities are installed on host",
            "Inspect user process ulimit settings and resource constraints",
            "Check available fonts and fontconfig cache status on Linux host",
            "Check if FFmpeg media processing tool is available in host PATH"
        ]
    },
    "File Operations": {
        "icon": "📁",
        "badge": "bg-amber-500/10 text-amber-300 border-amber-500/30",
        "prompts": [
            "Create a new file named project_notes.txt with content 'OmniShell architecture validation passed successfully'",
            "Create directory structure named build_artifacts and check its contents",
            "List all files in current directory with human-readable permissions and file sizes",
            "Find all Python script files larger than 10KB in current directory",
            "Count total lines of code across all Python files in the repository",
            "Search for the string 'TODO' across all source code files in the directory",
            "Calculate SHA256 checksum hash of package.json file",
            "Find all files modified in the last 24 hours in the project folder",
            "Archive current project directory into a compressed tar.gz backup file",
            "Create a JSON configuration file named config.dev.json with sample API keys",
            "Find and display all hidden dotfiles and configuration directories in home folder",
            "Find all empty directories in current workspace and list them",
            "Display disk usage breakdown of the top 5 largest directories in project",
            "Check file permissions and octal mode for all shell script (.sh) files",
            "Find all broken symbolic links in the current workspace directory",
            "Create a new markdown file named CHANGELOG.md with initial v1.0.0 release notes",
            "Count the number of TypeScript (.ts) and Handlebars (.hbs) files in frontend",
            "Extract text between specific headers from README.md file",
            "Find all log files ending with .log and calculate their total combined size",
            "Replace all occurrences of localhost:8000 with api.omnishell.internal in env file",
            "Create a secure directory with restricted 700 permissions for private keys",
            "Search for all JSON files containing the key 'version' in the project",
            "Create a backup copy of .env file named .env.backup with timestamp",
            "Inspect the last 50 lines of the latest backend application log file",
            "Find duplicate filenames across multiple nested project subdirectories",
            "Check word count and character count in project documentation markdown files",
            "Format JSON files in the workspace with 2-space indentation",
            "Find all files owned by root in the current non-root workspace",
            "Create a symbolic link from docs/README.md to root README.md",
            "List all files sorted chronologically by last modification timestamp"
        ]
    },
    "Multi-Step Pipelines": {
        "icon": "📋",
        "badge": "bg-violet-500/10 text-violet-300 border-violet-500/30",
        "prompts": [
            "First check disk space, then inspect memory usage, and finally list running docker containers",
            "Step 1: check git status; Step 2: run tests; Step 3: check build directory",
            "Check network connectivity, inspect DNS resolution, and verify ping to 8.8.8.8",
            "First inspect system load, then list top 5 CPU processes, and finally check free RAM",
            "Create backup directory, copy config files to backup, and verify backup file sizes",
            "Step 1: pull latest git changes, Step 2: install dependencies, Step 3: build project",
            "Step 1: inspect open ports, Step 2: find process using port 8000, Step 3: verify health",
            "Initialize new Node.js package, create index.js entrypoint, and run syntax check",
            "Create Python virtual environment .venv, activate it, and install pytest",
            "Inspect Docker container status, check container logs, and inspect CPU usage",
            "Create release directory, generate build artifact tarball, and compute SHA256 checksum",
            "Step 1: clean build cache, Step 2: compile TypeScript files, Step 3: check exit code",
            "Test HTTP server endpoint, measure response latency, and check HTTP status code 200",
            "Step 1: inspect system swap, Step 2: sync filesystem buffers, Step 3: drop caches",
            "Create git feature branch, stage modified files, and verify git diff status",
            "Check database connection, inspect schema tables count, and check active queries",
            "Verify SSL certificate validity, inspect certificate expiry date, and test TLS handshake",
            "Step 1: check nginx configuration syntax, Step 2: test port 80 binding, Step 3: reload",
            "Step 1: verify disk read speed, Step 2: verify disk write speed, Step 3: report IOPS",
            "Step 1: fetch remote git tags, Step 2: create new semantic tag v1.2.0, Step 3: verify log",
            "Step 1: inspect Redis ping, Step 2: check memory used by Redis, Step 3: count total keys",
            "Step 1: check Docker disk usage, Step 2: prune dangling builder cache, Step 3: verify space",
            "Step 1: lint source code, Step 2: run unit test suite, Step 3: generate coverage report",
            "Step 1: export database schema dump, Step 2: compress SQL file, Step 3: verify size",
            "Step 1: check firewall status, Step 2: list active rules, Step 3: test allowed port 443",
            "Step 1: scan local subnet, Step 2: identify active host IPs, Step 3: resolve hostnames",
            "Step 1: inspect systemd journal size, Step 2: vacuum journal logs older than 7 days, Step 3: verify",
            "Step 1: verify Python dependencies, Step 2: check for outdated packages, Step 3: report vulnerabilities",
            "Step 1: check battery level, Step 2: check AC power adapter, Step 3: report estimated battery life",
            "Step 1: check CPU frequency governor, Step 2: inspect core clock speeds, Step 3: report thermal status"
        ]
    },
    "Scheduled Tasks": {
        "icon": "⏰",
        "badge": "bg-blue-500/10 text-blue-300 border-blue-500/30",
        "prompts": [
            "Open Spotify in the browser after 10 minutes",
            "Schedule a system memory and disk diagnostic tomorrow at 10:00 AM",
            "Schedule host backup and log archive in 15 minutes",
            "Schedule health check and service report in 30 minutes",
            "Run system inspection report in 5 minutes",
            "Schedule database backup and compression snapshot in 2 hours",
            "Open Google Meet in browser in 20 minutes for team sync",
            "Schedule disk space alert check after 45 minutes",
            "Run automated test suite execution in 1 hour",
            "Schedule Docker container resource audit in 10 minutes",
            "Open GitHub pull requests dashboard in browser in 15 minutes",
            "Schedule temporary file cleanup in 30 minutes",
            "Schedule network latency and packet loss test in 25 minutes",
            "Open Brave browser to news.ycombinator.com in 5 minutes",
            "Schedule system uptime and load average snapshot tomorrow at 8:00 AM",
            "Schedule log rotation and archive in 4 hours",
            "Schedule Redis memory usage inspection in 15 minutes",
            "Open AWS CloudWatch or Grafana dashboard in browser in 10 minutes",
            "Schedule Git repository remote synchronization in 35 minutes",
            "Run security vulnerability dependency scan in 50 minutes",
            "Schedule web service endpoint health check in 8 minutes",
            "Schedule system reboot notification banner in 3 hours",
            "Open documentation portal in browser in 12 minutes",
            "Schedule CPU throttling and temperature check in 18 minutes",
            "Schedule disk I/O performance benchmark in 1 hour",
            "Open YouTube Music playlist in browser in 3 minutes",
            "Schedule cache invalidation and warm-up script in 40 minutes",
            "Schedule database connection pool status check in 20 minutes",
            "Run file integrity and checksum verification in 2 hours",
            "Schedule system diagnostic summary broadcast in 30 minutes"
        ]
    },
    "Recurring & Cron": {
        "icon": "🔁",
        "badge": "bg-teal-500/10 text-teal-300 border-teal-500/30",
        "prompts": [
            "Check disk free space every 10 seconds and report",
            "Check system uptime every day at 09:00",
            "Check system memory and CPU utilization every 5 minutes",
            "Inspect docker container health and running status every hour",
            "Monitor network socket connection count every 30 seconds",
            "Check database connection pool metrics every 15 minutes",
            "Poll API endpoint health status every 2 minutes",
            "Inspect system load average and active processes every 1 minute",
            "Check CPU temperature and thermal zone throttling every 3 minutes",
            "Run automated backup archive verification every night at midnight",
            "Audit failed SSH login attempts in auth.log every 10 minutes",
            "Check free RAM and swap memory usage every 5 minutes",
            "Check available disk inodes across all mounts every 30 minutes",
            "Monitor Redis memory consumption and key count every 10 minutes",
            "Check Nginx access log request rate and 5xx errors every 5 minutes",
            "Scan for zombie or defunct processes every 15 minutes",
            "Check SSL certificate expiration date every day at 08:00",
            "Verify DNS resolution response times every 10 minutes",
            "Check PostgreSQL active transactions and lock contention every 5 minutes",
            "Clean old temporary build cache files every Sunday at 02:00",
            "Check Docker daemon disk and volume usage every 6 hours",
            "Monitor network interface bandwidth traffic every 1 minute",
            "Check for available operating system package updates every day at 12:00",
            "Audit systemd unit service statuses every 20 minutes",
            "Check Git repository for new remote commits every 15 minutes",
            "Inspect open file descriptors count against system limits every 5 minutes",
            "Monitor background job queue latency and backlog every 2 minutes",
            "Check system battery health and power consumption every 10 minutes",
            "Audit filesystem permissions on sensitive configuration files every day at 03:00",
            "Check kernel error messages in dmesg every 30 minutes"
        ]
    },
    "Conditional & Thresholds": {
        "icon": "🔀",
        "badge": "bg-rose-500/10 text-rose-300 border-rose-500/30",
        "prompts": [
            "empty my trash as soon as it reaches 30% and above",
            "schedule and check every 1 minutes for that max attemt still be three",
            "If memory usage is greater than 90% then alert me and clean temporary cache",
            "If disk usage is greater than 85% then purge old temporary log files",
            "If Docker service is not running then alert me with system diagnosis",
            "If CPU load average exceeds 4.0 then list top 10 CPU consuming processes",
            "If free disk space falls below 10GB then send emergency notification",
            "If swap usage is greater than 50% then inspect memory allocation",
            "If CPU temperature exceeds 80 degrees Celsius then trigger fan cooling alert",
            "If system RAM usage is greater than 80% then drop page caches",
            "If web port 8000 is not responding then check service status and logs",
            "If total process count exceeds 300 then inspect for fork bomb or runaway threads",
            "If database connection count reaches 90% of pool limit then alert admin",
            "If battery level drops below 20% then enable power saving recommendations",
            "If network ping packet loss to 8.8.8.8 exceeds 20% then diagnose network interface",
            "If /tmp partition usage exceeds 75% then clean temporary session files",
            "If zombie processes count is greater than 5 then identify parent PIDs",
            "If open file descriptors reach 80% of max limit then report leaking processes",
            "If Nginx error log contains 502 Bad Gateway then test backend upstream",
            "If Docker container exits with non-zero code then display last 50 lines of logs",
            "If disk write I/O latency exceeds 50ms then inspect disk queue length",
            "If system uptime exceeds 30 days then schedule maintenance review",
            "If available swap is zero then trigger high memory alert immediately",
            "If Redis memory usage exceeds 1GB then inspect largest memory keys",
            "If DNS query resolution fails then switch to backup DNS resolver 1.1.1.1",
            "If file transfer speeds drop below 1MB/s then diagnose network link quality",
            "If system load average exceeds number of CPU cores then log process snapshot",
            "If SSL certificate expires in less than 14 days then trigger renewal alert",
            "If unmerged git branches count exceeds 10 then generate branch report",
            "If background queue backlog exceeds 500 items then scale worker processes"
        ]
    },
    "Recovery & Human Approval": {
        "icon": "🛡️",
        "badge": "bg-amber-500/10 text-amber-300 border-amber-500/30",
        "prompts": [
            "clean my trash",
            "Delete all temporary cache files and empty trash files immediately",
            "Purge old temporary build artifacts in /tmp directory",
            "Stop and remove all exited Docker containers on host machine",
            "Restart the web service with automatic rollback on error if it fails",
            "Restart Nginx web server and retry up to 3 times with diagnostic check if it fails",
            "Run deployment script with auto-heal and fallback to previous stable release on error",
            "Execute database migration with automatic rollback if any SQL constraint fails",
            "Kill zombie and stuck processes listening on port 8000 after human confirmation",
            "Prune all unused Docker images, containers, and build cache with docker system prune -a",
            "Drop temporary database tables created during test run after approval",
            "Purge old Linux kernel headers and clean apt package cache after confirmation",
            "Reset local firewall rules to default policy with safety authorization",
            "Truncate oversized application debug log files larger than 500MB",
            "Flush local DNS cache and restart systemd-resolved service with auto-recovery",
            "Release stuck dpkg lock files and repair interrupted package installations",
            "Restore corrupted configuration files from the latest verified backup archive",
            "Reset network interface controller and renew DHCP lease with rollback on disconnect",
            "Kill runaway memory-leaking process and restart service with auto-healing",
            "Rebuild corrupted local Git index and verify repository object integrity",
            "Clean NPM global cache and repair broken node_modules dependencies",
            "Prune all dangling Docker volumes consuming disk space after confirmation",
            "Reset Redis database keys matching prefix 'temp:*' after human review",
            "Re-index corrupted SQLite database file with automatic transaction rollback",
            "Purge cached thumbnail images in user directory to recover disk storage",
            "Restart crashed PostgreSQL service and execute WAL recovery check",
            "Recover unsaved editor swap files and restore latest edit buffers",
            "Rollback recent Git commit and reset working directory to clean HEAD state",
            "Purge outdated pip cache and re-verify installed package requirements",
            "Execute system recovery plan: clear temp, kill stale workers, and restart daemons"
        ]
    }
}

# Generate JavaScript Array
js_items = []
total_count = 0
for cat_name, cat_data in CATEGORIES.items():
    icon = cat_data["icon"]
    badge = cat_data["badge"]
    for p_text in cat_data["prompts"]:
        total_count += 1
        # Escape single quotes and backslashes for JS string
        safe_text = p_text.replace('\\', '\\\\').replace("'", "\\'")
        js_items.append(f"            {{ category: '{cat_name}', icon: '{icon}', badgeClass: '{badge}', text: '{safe_text}' }},")

print(f"Total Prompts Generated: {total_count}")

# Generate Markdown Document
md_lines = [
    "# 📚 OmniShell 300+ Curated Multi-Agent Prompt Test Suite",
    "",
    "> **Universal Autonomous Syndicate Prompt Library**  ",
    "> Interactive, click-to-copy, and categorized test prompts across all 10 core capability dimensions.",
    "",
    f"**Total Curated Presets:** `{total_count}` prompts  ",
    f"**Categories:** `{len(CATEGORIES)}` distinct operational domains (30 prompts per category)  ",
    "**Host Compatibility:** Linux (Bash), macOS (Zsh/Darwin), Windows (PowerShell)",
    "",
    "---",
    "",
    "## 📑 Table of Contents",
    ""
]

for cat_name, cat_data in CATEGORIES.items():
    slug = cat_name.lower().replace(" & ", "-").replace(" ", "-")
    md_lines.append(f"- [{cat_data['icon']} {cat_name} (30 Presets)](#-{slug}-30-presets)")

md_lines.append("")
md_lines.append("---")
md_lines.append("")

for cat_name, cat_data in CATEGORIES.items():
    slug = cat_name.lower().replace(" & ", "-").replace(" ", "-")
    icon = cat_data["icon"]
    md_lines.append(f"## {icon} {cat_name} (30 Presets)")
    md_lines.append("")
    md_lines.append("| # | Prompt (Click to Copy) | Target Capability / Mode | Expected Agent Pipeline Behavior |")
    md_lines.append("|---|---|---|---|")
    
    for idx, p_text in enumerate(cat_data["prompts"], start=1):
        escaped_pipe = p_text.replace("|", "\\|")
        md_lines.append(f"| **{idx:02d}** | `{escaped_pipe}` | **{cat_name}** | Autonomous intent deconstruction, policy gating, execution & host verification |")
    
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

md_content = "\n".join(md_lines)

# Write to docs/PROMPT_TEST_SUITE.md
with open("docs/PROMPT_TEST_SUITE.md", "w") as f:
    f.write(md_content)

print("Wrote docs/PROMPT_TEST_SUITE.md successfully.")

# Output JS for inclusion
with open("/tmp/prompt_library_js.txt", "w") as f:
    f.write("\n".join(js_items))

print("Wrote /tmp/prompt_library_js.txt successfully.")
