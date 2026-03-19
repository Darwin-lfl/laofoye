# Empress Dowager Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python RunClaw-style agent stack with uv + LangChain/LangGraph.

**Architecture:** Gateway -> Dispatcher -> Agent pipeline with memory and scheduler subsystems. Use LangGraph ReAct for tool-calling behavior and JSON store for scheduled tasks.

**Tech Stack:** Python 3.11+, uv, langchain 1.x, langgraph 1.x, pytest.

---

### Task 1: Test Scaffold

**Files:**
- Create: `tests/test_config.py`
- Create: `tests/test_dispatcher.py`
- Create: `tests/test_memory_daily.py`
- Create: `tests/test_scheduler_store.py`

- [x] **Step 1: Write failing tests first**
- [x] **Step 2: Run tests to verify RED**

### Task 2: Core Modules

**Files:**
- Create: `src/types.py`
- Create: `src/config.py`
- Create: `src/dispatcher.py`
- Create: `src/memory/*.py`
- Create: `src/scheduler/*.py`

- [x] **Step 1: Implement minimal code for failing tests**
- [x] **Step 2: Re-run tests for GREEN**

### Task 3: Agent + Runtime

**Files:**
- Create: `src/agent.py`
- Create: `src/gateway/cli.py`
- Create: `src/main.py`
- Modify: `pyproject.toml`

- [x] **Step 1: Implement LangGraph agent and runtime wiring**
- [x] **Step 2: Validate entrypoint and package install**

### Task 4: Verification

**Files:**
- Modify: `README.md`

- [x] **Step 1: Run `uv run --extra dev pytest -q`**
- [x] **Step 2: Run `uv run empress-dowager --help`**
