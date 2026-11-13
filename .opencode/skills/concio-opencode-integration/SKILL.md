---
name: concio-opencode-integration
description: Bridge and coordinate Concio Studio with the OpenCode harness and Composio agent — trigger module execution, query RAG context, queue interventions, and orchestrate external SaaS actions via Composio CLI. Use when integrating Concio Studio with OpenCode, executing OpenCode tasks from Concio, or routing multi-agent workflows between Concio and OpenCode.
---

# Concio Studio & OpenCode Integration

This skill establishes the contract and operational protocol between **Concio Studio** (FastAPI backend + Pixel Art multi-agent interface) and the **OpenCode** autonomous coding harness, powered by **Composio CLI** for external SaaS actions.

## Architecture & Communication Flow

```
┌────────────────────────────────────────────────────────┐
│                   CONCIO STUDIO V2                     │
│  FastAPI (Port 8000) • SQLite queues • RAG FTS5 Engine │
└───────────┬────────────────────────────────┬───────────┘
            │                                │
            ▼ (1. Enqueue & Context)         ▼ (2. SaaS Tool Execution)
┌───────────────────────┐        ┌───────────────────────┐
│       OPENCODE        │        │     COMPOSIO CLI      │
│   Autonomous Harness  │◄───────┤ 1000+ External Apps   │
│ (.opencode/config.json)│        │ (Slack, GitHub, Gmail)│
└───────────────────────┘        └───────────────────────┘
```

## The Integration Protocol

### 1. Context Sync from Concio RAG to OpenCode
Before executing any agent prompt or OpenCode run, query Concio Studio's local RAG:
```python
from core import rag_engine
context = rag_engine.build_context("concio opencode integration", limit=3)
```
OpenCode receives this context in its system prompt or via `.opencode/skills/`.

### 2. OpenCode Configuration Management
Concio Studio generates and syncs `.opencode/config.json` via `core.llm_router.write_opencode_config()`:
- Points to OmniRoute or local model router (`baseURL`).
- Sets active model combo (`OMNIROUTE_COMBO`).
- Discovers skills automatically from `.opencode/skills/`.

### 3. Execution via Concio Orchestrator
To trigger OpenCode from Concio backend without blocking:
```python
from core import orchestrator
res = orchestrator.run_agent_cli(agent="opencode", prompt="Execute feature X with TDD", timeout=180)
```
Interventions and chat messages are logged to `workspace/devmaster.db`.

### 4. Composio SaaS Action Delegation
When an OpenCode or Concio agent needs to interact with an external service:
1. **Discover:** `composio search "<action>" --toolkits <app>`
2. **Schema:** `composio execute <SLUG> --get-schema`
3. **Verify Auth:** `composio connections list`
4. **Dry Run:** `composio execute <SLUG> --dry-run -d '{"param": "val"}'`
5. **Execute:** `composio execute <SLUG> -d '{"param": "val"}'`

## Quality Bar
- Every OpenCode invocation is recorded in `workspace/devmaster.db` with timing and exit code.
- Credentials for Composio and external SaaS never enter frontend code.
- RAG queries precede coding tasks to ensure architectural compliance.
- Dry-run verification is mandatory before write/destructive actions.

