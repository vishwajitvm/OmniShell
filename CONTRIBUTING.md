# Contributing to OmniShell

First off, thank you for considering contributing to OmniShell! 🎉

Every contribution — whether it's fixing a typo, reporting a bug, suggesting a feature, or submitting a pull request — helps make OmniShell better for everyone.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Style Guidelines](#style-guidelines)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)

## Code of Conduct

This project and everyone participating in it is governed by the [OmniShell Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How Can I Contribute?

### 🐛 Reporting Bugs

Before creating a bug report, please check existing issues to avoid duplicates.

When filing a bug report, include:

- **Clear title** describing the issue
- **Steps to reproduce** the behavior
- **Expected behavior** vs. **actual behavior**
- **Screenshots or GIFs** if applicable
- **Environment details**: OS, Docker version, browser, Python version
- **Logs**: Backend logs (`docker logs saas_poc-backend-1`), frontend logs, executor logs

### 💡 Suggesting Features

Feature requests are welcome! Please include:

- **Clear description** of the proposed feature
- **Use case**: Why is this feature needed?
- **Proposed solution**: How do you envision it working?
- **Alternatives considered**: Any workarounds you've tried?

### 🔧 Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Getting Started

### Prerequisites

- Docker & Docker Compose
- Python 3.10+
- Node.js 18+
- Git

### Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/OmniShell.git
cd OmniShell/saas_poc

# Copy environment config
cp .env.template .env

# Start the stack
docker-compose up --build -d

# Start host executor (in a separate terminal)
pip install psutil
python3 local_executor.py

# Run tests
python3 -m unittest tests/test_capabilities.py
```

### Running Tests

```bash
# Run all tests
python3 -m unittest tests/test_capabilities.py

# Run specific test class
python3 -m unittest tests.test_capabilities.TestCapabilitiesClassification

# Run with verbose output
python3 -m unittest tests/test_capabilities.py -v
```

## Pull Request Process

1. **Update tests**: Add or update tests for any new functionality
2. **Pass all tests**: Ensure `python3 -m unittest tests/test_capabilities.py` passes 100%
3. **Follow style guidelines**: See below
4. **Update documentation**: If your change affects the API, architecture, or user-facing features
5. **Write a clear PR description**: Explain what and why, not just how

## Style Guidelines

### Python (Backend)

- Follow PEP 8
- Use type hints where practical
- Write docstrings for public functions
- Use meaningful variable names
- Keep functions focused and small

### JavaScript/Handlebars (Frontend)

- Use consistent indentation (2 spaces)
- Keep template logic minimal
- Comment complex UI interactions

### Commit Messages

- Use present tense: "Add feature" not "Added feature"
- Use imperative mood: "Fix bug" not "Fixes bug"
- Keep the first line under 72 characters
- Reference issues when applicable: "Fix #123: Handle edge case in scheduler"

## 🏗️ Project Structure

```
saas_poc/
├── backend/            # FastAPI backend (main.py)
│   └── tests/          # Backend-specific tests
├── frontend/           # NestJS + Handlebars UI
│   └── views/          # HBS templates
├── executor/           # Host executor module
├── tests/              # Integration tests
├── docs/               # Documentation
├── assets/             # GIFs, images, media
├── docker-compose.yml  # Container orchestration
├── local_executor.py   # Host daemon
└── README.md           # Project overview
```

## ❓ Questions?

Feel free to open an issue with the `question` label, or start a discussion in the repository.

---

Thank you for contributing! 🚀

— **Vishwajit VM**
