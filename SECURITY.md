# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | ✅ Active support  |

## Reporting a Vulnerability

If you discover a security vulnerability within OmniShell, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email: **vishwajitvm@users.noreply.github.com**

### What to include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline:

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix or mitigation**: Within 2 weeks for critical issues

## Security Architecture

OmniShell implements a **4-Layer Defense System**:

1. **Intent Classification Layer**: Deterministic regex-based routing prevents prompt injection
2. **Policy & Safety Gate**: AST pattern filtering blocks dangerous commands (rm -rf, fork bombs, etc.)
3. **Human-in-the-Loop (HITL)**: Explicit user approval for elevated operations
4. **Process Verification**: psutil-based exit code and process state verification

For detailed security architecture, see [docs/SECURITY_AND_GUARDRAILS.md](docs/SECURITY_AND_GUARDRAILS.md).
