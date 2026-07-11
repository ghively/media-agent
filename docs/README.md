# Media Agent — Documentation Wiki

> Complete reference for the media-agent project. Designed for both human developers and AI agents.

## Documents

| Document | Purpose | Audience |
|---|---|---|
| **[../README.md](../README.md)** | Project overview, quick start, interface reference | Everyone (start here) |
| **[../CLAUDE.md](../CLAUDE.md)** | AI development context — conventions, patterns, gotchas | AI agents working on this codebase |
| **[../ARCHITECTURE.md](../ARCHITECTURE.md)** | System architecture, data flow, component reference | Architects, developers |
| **[tool-reference.md](tool-reference.md)** | Complete reference for all 66 tools | Developers, tool authors |
| **[development-guide.md](development-guide.md)** | Step-by-step guide to developing on this project | New developers, AI agents |
| **[deployment-guide.md](deployment-guide.md)** | Build, deploy, configure, troubleshoot | Operators, DevOps |
| **[api-reference.md](api-reference.md)** | OpenAI-compatible API specification | API consumers, Open WebUI admins |
| **[../SPEC.md](../SPEC.md)** | Historical design specification (original vision) | Reference only |

## How to Use This Wiki

### I want to understand the system
→ Read [../README.md](../README.md) → [../ARCHITECTURE.md](../ARCHITECTURE.md)

### I want to add a new tool or feature
→ Read [../CLAUDE.md](../CLAUDE.md) → [development-guide.md](development-guide.md) → [tool-reference.md](tool-reference.md)

### I want to deploy or rebuild
→ Read [deployment-guide.md](deployment-guide.md)

### I want to connect an app to the API
→ Read [api-reference.md](api-reference.md)

### I want to know what a specific tool does
→ Look it up in [tool-reference.md](tool-reference.md)

## Project Facts

- **66 tools** across 12 source files
- **4,230 lines** of Python
- **1 Docker container** on your-gpu-host
- **3 physical hosts** in the media stack (your-gpu-host, your-nas, your-media-host)
- **Local LLM** (Qwen 3.5 9B via Ollama — zero API cost)
- **OpenAI-compatible API** (mount in any OpenAI-compatible client)
- **3 interfaces**: CLI, Web Dashboard, API (Telegram pending)

## Living Documentation Policy

These docs are **living** — they change with the code. Rules:
1. Every runtime change → update docs in the same commit
2. Code and docs disagree? The code is right → fix the docs
3. New tool → add to [tool-reference.md](tool-reference.md) immediately
4. New pattern → document in [development-guide.md](development-guide.md)
5. Architecture change → update [../ARCHITECTURE.md](../ARCHITECTURE.md)

---

*Last updated: 2026-07-11*
