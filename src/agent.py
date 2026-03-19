from __future__ import annotations

import io
import json
import os
import subprocess
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from contextvars import ContextVar
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from config import AgentConfig
from core_types import Agent, AgentStreamEvent, RunRequest, RunResponse
from memory import sync_long_term_memory
from scheduler.store import TaskStore, compute_next_run
from scheduler.types import ScheduledTask
from utils import get_logger

log = get_logger("agent")

SHARED_FILES = ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md"]
MAX_SKILL_PREVIEW_CHARS = 4_096
MAX_SKILL_READ_CHARS = 20_000


class LangGraphAgent(Agent):
    kind = "langgraph"

    def __init__(
        self,
        *,
        config: AgentConfig,
        workspaces_dir: Path,
        skills_dir: Path,
        scheduler_store: TaskStore | None = None,
    ) -> None:
        self.model = config.model
        self._base_system_prompt = config.system_prompt
        self._allowed_tools = set(config.allowed_tools)
        self._workspaces_dir = workspaces_dir.expanduser().resolve()
        self._skills_dir = skills_dir.expanduser().resolve()
        self._scheduler_store = scheduler_store
        self._history: dict[str, list[BaseMessage]] = {}
        self._history_summaries: dict[str, str] = {}
        self._history_keep_messages = max(4, int(config.history_keep_messages))
        self._history_compact_threshold = max(
            self._history_keep_messages + 1,
            int(config.history_compact_threshold),
        )
        self._history_summary_max_chars = max(1000, int(config.history_summary_max_chars))
        self._workspace_var: ContextVar[Path | None] = ContextVar(
            "active_workspace",
            default=None,
        )
        self._python_state: dict[str, dict[str, Any]] = {}

        if not config.api_key:
            raise RuntimeError(
                "Missing OPENAI_API_KEY in project .env. "
                "Please set OPENAI_API_KEY=<your_key> in .env"
            )

        self._model = ChatOpenAI(
            model=self.model,
            temperature=0,
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._tools = self._build_tools()
        self._agent_app = create_agent(
            model=self._model,
            tools=self._tools,
            # Dynamic context (workspace memory) is injected per request as a
            # SystemMessage; keep the create_agent baseline prompt minimal.
            system_prompt="You are a practical assistant. Use tools when needed.",
        )

    async def run(self, request: RunRequest) -> RunResponse:
        t0 = datetime.now(UTC)
        workspace_dir = self._prepare_workspace(request.conversation_id)
        payload = self._build_payload(
            conversation_id=request.conversation_id,
            workspace_dir=workspace_dir,
            user_text=request.text,
        )

        try:
            messages = await self._invoke_messages(payload, workspace_dir)
        except Exception as exc:
            if not _is_context_length_error(exc):
                raise
            self._force_compact_history(request.conversation_id)
            payload = self._build_payload(
                conversation_id=request.conversation_id,
                workspace_dir=workspace_dir,
                user_text=request.text,
            )
            messages = await self._invoke_messages(payload, workspace_dir)

        self._store_history(request.conversation_id, messages)

        text = _last_ai_text(messages)
        elapsed = int((datetime.now(UTC) - t0).total_seconds() * 1000)
        return RunResponse(text=text, elapsed_ms=elapsed, model=self.model)

    async def stream(self, request: RunRequest) -> AsyncGenerator[AgentStreamEvent, None]:
        t0 = datetime.now(UTC)
        workspace_dir = self._prepare_workspace(request.conversation_id)
        payload = self._build_payload(
            conversation_id=request.conversation_id,
            workspace_dir=workspace_dir,
            user_text=request.text,
        )

        messages: list[BaseMessage] = []
        streamed_any = False
        token = self._workspace_var.set(workspace_dir)
        try:
            try:
                async for event in self._agent_app.astream_events({"messages": payload}, version="v2"):
                    event_name = str(event.get("event", ""))
                    data = event.get("data", {}) or {}
                    if event_name == "on_tool_start":
                        streamed_any = True
                        yield AgentStreamEvent(
                            type="tool_use",
                            name=str(event.get("name", "tool")),
                            tool_input=_coerce_dict(data.get("input")),
                        )
                        continue

                    if event_name == "on_tool_end":
                        streamed_any = True
                        yield AgentStreamEvent(
                            type="tool_result",
                            name=str(event.get("name", "tool")),
                            text=_format_tool_output(data.get("output")),
                        )
                        continue

                    if event_name == "on_chat_model_stream":
                        chunk = data.get("chunk")
                        for thinking in _extract_thinking_deltas(chunk):
                            if not thinking:
                                continue
                            streamed_any = True
                            yield AgentStreamEvent(type="thinking_delta", text=thinking)
                        for text in _extract_text_deltas(chunk):
                            if not text:
                                continue
                            streamed_any = True
                            yield AgentStreamEvent(type="text_delta", text=text)
                        continue

                    if event_name == "on_chain_end":
                        output = data.get("output")
                        if isinstance(output, dict):
                            maybe_messages = output.get("messages")
                            if isinstance(maybe_messages, list):
                                messages = [msg for msg in maybe_messages if isinstance(msg, BaseMessage)]
            except Exception:
                # If provider/runtime doesn't support event streaming, fall back.
                streamed_any = False
                messages = []

            if not messages:
                try:
                    messages = await self._invoke_messages(payload, workspace_dir)
                except Exception as exc:
                    if not _is_context_length_error(exc):
                        raise
                    self._force_compact_history(request.conversation_id)
                    payload = self._build_payload(
                        conversation_id=request.conversation_id,
                        workspace_dir=workspace_dir,
                        user_text=request.text,
                    )
                    messages = await self._invoke_messages(payload, workspace_dir)
            self._store_history(request.conversation_id, messages)
        finally:
            self._workspace_var.reset(token)

        text = _last_ai_text(messages)
        response = RunResponse(
            text=text,
            elapsed_ms=int((datetime.now(UTC) - t0).total_seconds() * 1000),
            model=self.model,
        )
        # If nothing streamed from provider, degrade to chunked text streaming.
        if not streamed_any:
            for chunk in _chunk_text(text, 32):
                yield AgentStreamEvent(type="text_delta", text=chunk)
        yield AgentStreamEvent(type="done", response=response)

    async def _invoke_messages(
        self,
        payload: list[BaseMessage],
        workspace_dir: Path,
    ) -> list[BaseMessage]:
        token = self._workspace_var.set(workspace_dir)
        try:
            result = await self._agent_app.ainvoke({"messages": payload})
        finally:
            self._workspace_var.reset(token)
        return [msg for msg in result.get("messages", []) if isinstance(msg, BaseMessage)]

    def get_workspace_dir(self, conversation_id: str) -> str:
        return str(self._workspaces_dir / conversation_id.replace(":", "_"))

    async def clear_conversation(self, conversation_id: str) -> None:
        self._history.pop(conversation_id, None)
        self._history_summaries.pop(conversation_id, None)

    async def dispose(self) -> None:
        self._history.clear()
        self._history_summaries.clear()

    def _build_payload(
        self,
        *,
        conversation_id: str,
        workspace_dir: Path,
        user_text: str,
    ) -> list[BaseMessage]:
        prior = self._history.get(conversation_id, [])
        summary, prior = self._prepare_history_context(conversation_id, prior)

        payload: list[BaseMessage] = [
            SystemMessage(content=self._build_system_prompt(workspace_dir)),
        ]
        if summary:
            payload.append(
                SystemMessage(
                    content=(
                        "## Conversation Summary\n"
                        "Compressed historical context from earlier turns.\n"
                        f"{summary}"
                    )
                )
            )
        payload.extend(prior)
        payload.append(HumanMessage(content=user_text))
        return payload

    def _store_history(self, conversation_id: str, messages: list[BaseMessage]) -> None:
        history = [msg for msg in messages if not isinstance(msg, SystemMessage)]
        self._history[conversation_id] = history
        self._prepare_history_context(conversation_id, history)

    def _prepare_history_context(
        self,
        conversation_id: str,
        history: list[BaseMessage],
    ) -> tuple[str, list[BaseMessage]]:
        summary = self._history_summaries.get(conversation_id, "")
        if len(history) > self._history_compact_threshold:
            older = history[: -self._history_keep_messages]
            recent = history[-self._history_keep_messages :]
            summary = self._merge_history_summary(summary, older)
            self._history_summaries[conversation_id] = summary
            self._history[conversation_id] = recent
            return summary, recent
        if summary:
            self._history_summaries[conversation_id] = self._trim_summary(summary)
        return self._history_summaries.get(conversation_id, summary), history

    def _force_compact_history(self, conversation_id: str) -> None:
        history = self._history.get(conversation_id, [])
        if not history:
            return
        keep = min(6, self._history_keep_messages)
        older = history[:-keep]
        recent = history[-keep:]
        summary = self._history_summaries.get(conversation_id, "")
        summary = self._merge_history_summary(summary, older)
        if len(summary) > 2000:
            summary = summary[-2000:]
        self._history_summaries[conversation_id] = summary
        self._history[conversation_id] = recent

    def _merge_history_summary(self, existing: str, messages: list[BaseMessage]) -> str:
        lines: list[str] = []
        if existing.strip():
            lines.append(existing.strip())

        for msg in messages:
            text = _message_text(msg)
            if not text:
                continue
            compact = " ".join(text.split())
            if len(compact) > 260:
                compact = compact[:257] + "..."
            role = "User"
            if isinstance(msg, AIMessage):
                role = "Assistant"
            elif not isinstance(msg, HumanMessage):
                role = msg.type.capitalize()
            lines.append(f"- {role}: {compact}")

        return self._trim_summary("\n".join(lines).strip())

    def _trim_summary(self, summary: str) -> str:
        if len(summary) <= self._history_summary_max_chars:
            return summary
        marker = "[Older context truncated]\n"
        keep = max(0, self._history_summary_max_chars - len(marker))
        return marker + summary[-keep:]

    def _build_system_prompt(self, workspace_dir: Path) -> str:
        parts = [self._base_system_prompt]

        context_files = [
            ("AGENTS.md", "Agent Playbook"),
            ("SOUL.md", "Personality"),
            ("IDENTITY.md", "Identity"),
            ("USER.md", "User Profile"),
            ("MEMORY.md", "Long-term Memory"),
        ]

        for file_name, title in context_files:
            file_path = workspace_dir / file_name
            if not file_path.exists():
                continue
            if file_name == "MEMORY.md":
                try:
                    # Refresh TTL-based long-term memory view before injecting.
                    sync_long_term_memory(workspace_dir)
                except Exception:  # noqa: BLE001
                    log.exception("Failed to sync long-term memory view")
            content = file_path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            parts.append(f"## {title}\n{content}")

        skills_context = self._build_available_skills_block(
            self._collect_skills_metadata(workspace_dir)
        )
        if skills_context:
            parts.append(
                "## Skills Catalog\n"
                "Use the skills below by name. Load a full skill only when needed "
                "via tool `skill_read`.\n"
                f"{skills_context}"
            )

        return "\n\n".join(parts)

    def _collect_skills_metadata(self, workspace_dir: Path) -> list[dict[str, str]]:
        skills_root = workspace_dir / ".claude" / "skills"
        if not skills_root.exists():
            if self._skills_dir.exists():
                skills_root = self._skills_dir
            else:
                return []

        items: list[dict[str, str]] = []
        for skill_dir in sorted(skills_root.iterdir(), key=lambda p: p.name.lower()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            name, description = self._extract_skill_metadata(skill_dir.name, skill_file)
            items.append(
                {
                    "name": name,
                    "description": description,
                    "location": str(skill_file),
                }
            )

        return items

    def _extract_skill_metadata(
        self,
        default_name: str,
        skill_file: Path,
    ) -> tuple[str, str]:
        with skill_file.open("r", encoding="utf-8") as fp:
            preview = fp.read(MAX_SKILL_PREVIEW_CHARS)

        name = default_name
        description = ""
        body = preview

        if preview.startswith("---\n"):
            fence_idx = preview.find("\n---", 4)
            if fence_idx != -1:
                frontmatter = preview[4:fence_idx]
                body = preview[fence_idx + 4 :]
                for raw in frontmatter.splitlines():
                    line = raw.strip()
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip().strip('"').strip("'")
                    if key == "name" and value:
                        name = value
                    if key == "description" and value:
                        description = value

        if not description:
            for raw in body.splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith("---"):
                    continue
                description = line
                break

        if len(description) > 220:
            description = description[:217] + "..."
        if not description:
            description = "No description provided."
        return name, description

    def _build_available_skills_block(
        self,
        skills_metadata: list[dict[str, str]] | None = None,
    ) -> str:
        if not skills_metadata:
            return ""

        lines = ["<available_skills>"]
        for item in skills_metadata:
            lines.extend(
                [
                    "  <skill>",
                    f"    <name>{escape(item['name'])}</name>",
                    f"    <description>{escape(item['description'])}</description>",
                    f"    <location>{escape(item['location'])}</location>",
                    "  </skill>",
                ]
            )
        lines.append("</available_skills>")
        return "\n".join(lines) + "\n"

    def _prepare_workspace(self, conversation_id: str) -> Path:
        workspace_dir = self._workspaces_dir / conversation_id.replace(":", "_")
        workspace_dir.mkdir(parents=True, exist_ok=True)
        (workspace_dir / "memory").mkdir(parents=True, exist_ok=True)
        (workspace_dir / ".claude").mkdir(parents=True, exist_ok=True)

        source_templates = Path(__file__).parent / "templates"
        for file_name in SHARED_FILES:
            dest = workspace_dir / file_name
            if dest.exists():
                continue
            source = source_templates / file_name
            if source.exists():
                dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                dest.write_text("\n", encoding="utf-8")

        skills_link = workspace_dir / ".claude" / "skills"
        skills_target = self._skills_dir
        skills_target.mkdir(parents=True, exist_ok=True)

        if skills_link.is_symlink():
            try:
                current_target = skills_link.readlink()
                if not current_target.is_absolute():
                    current_target = skills_link.parent / current_target
                current_target_abs = os.path.abspath(str(current_target))
                desired_target_abs = os.path.abspath(str(skills_target))
                if current_target_abs != desired_target_abs:
                    skills_link.unlink(missing_ok=True)
            except OSError:
                # Broken/invalid symlink; recreate below.
                skills_link.unlink(missing_ok=True)

        # Path.exists() is False for broken symlinks. Handle symlink presence
        # explicitly so repeated starts are idempotent.
        if not skills_link.exists() and not skills_link.is_symlink():
            try:
                skills_link.symlink_to(skills_target, target_is_directory=True)
            except OSError:
                if skills_link.exists() or skills_link.is_symlink():
                    pass
                else:
                    skills_link.mkdir(parents=True, exist_ok=True)

        return workspace_dir

    def _active_workspace(self) -> Path:
        workspace = self._workspace_var.get()
        if workspace is None:
            raise RuntimeError(
                "No active workspace context. "
                "This tool must be called during an active agent run."
            )
        return workspace

    def _resolve_workspace_path(
        self,
        raw_path: str,
        *,
        create_parent: bool = False,
        allow_skills_dir: bool = False,
    ) -> Path:
        workspace = self._active_workspace().resolve()
        skills_dir = self._skills_dir.resolve()
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = (workspace / candidate).resolve()
        else:
            candidate = candidate.resolve()

        in_workspace = candidate == workspace or candidate.is_relative_to(workspace)
        in_skills = candidate == skills_dir or candidate.is_relative_to(skills_dir)

        if not in_workspace and not (allow_skills_dir and in_skills):
            if allow_skills_dir:
                raise ValueError(
                    f"Path is outside allowed roots (workspace + skills_dir): {raw_path}"
                )
            raise ValueError(f"Path is outside workspace: {raw_path}")

        if create_parent:
            candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def _build_tools(self):
        @tool
        def memory_search(query: str, limit: int = 5) -> str:
            """Search memory markdown files by keyword."""
            if not query.strip():
                return "Query is empty."
            matches: list[str] = []
            for path in self._workspaces_dir.glob("*/memory/*.md"):
                text = path.read_text(encoding="utf-8")
                if query.lower() not in text.lower():
                    continue
                snippet = text[:300].replace("\n", " ")
                matches.append(f"[{path.parent.parent.name}/{path.name}] {snippet}")
                if len(matches) >= limit:
                    break
            return "\n\n".join(matches) if matches else "No results found."

        @tool
        def memory_save(content: str, conversation_id: str) -> str:
            """Update workspace MEMORY.md using the full merged content."""
            workspace = Path(self.get_workspace_dir(conversation_id))
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "MEMORY.md").write_text(content.strip() + "\n", encoding="utf-8")
            return "Memory updated."

        @tool
        def schedule_task(prompt: str, schedule_type: str, schedule_value: str, chat_id: str) -> str:
            """Create scheduled tasks, supports cron and once."""
            if self._scheduler_store is None:
                return "Scheduler not configured."
            next_run = compute_next_run(schedule_type, schedule_value)
            if next_run is None:
                return "Invalid schedule or schedule in the past."
            task = ScheduledTask(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                prompt=prompt,
                schedule_type=schedule_type,  # type: ignore[arg-type]
                schedule_value=schedule_value,
                next_run=next_run,
                last_run=None,
                last_result=None,
                status="active",
                created_at=datetime.now(UTC),
            )
            self._scheduler_store.add(task)
            return f"Task created: {task.id[:8]}, next run: {next_run.isoformat()}"

        @tool
        def list_scheduled_tasks() -> str:
            """List active scheduled tasks."""
            if self._scheduler_store is None:
                return "Scheduler not configured."
            tasks = [task for task in self._scheduler_store.load() if task.status != "completed"]
            if not tasks:
                return "No active scheduled tasks."
            rows = [f"{task.id[:8]} | {task.schedule_type} {task.schedule_value} | {task.prompt}" for task in tasks]
            return "\n".join(rows)

        @tool
        def remove_scheduled_task(task_id: str) -> str:
            """Remove scheduled task by full id or short prefix."""
            if self._scheduler_store is None:
                return "Scheduler not configured."
            return "Task removed." if self._scheduler_store.remove(task_id) else "Task not found."

        @tool
        def skill_read(skill_name: str) -> str:
            """Load full SKILL.md content for a named skill when details are needed."""
            skill_file = self._skills_dir / skill_name / "SKILL.md"
            if not skill_file.exists():
                available = sorted(
                    path.name for path in self._skills_dir.iterdir() if path.is_dir()
                ) if self._skills_dir.exists() else []
                return (
                    f"Skill not found: {skill_name}. "
                    f"Available: {', '.join(available) if available else '(none)'}"
                )
            content = skill_file.read_text(encoding="utf-8")
            if len(content) <= MAX_SKILL_READ_CHARS:
                return content
            return content[:MAX_SKILL_READ_CHARS] + "\n\n[truncated]"

        @tool
        def terminal(command: str, timeout_seconds: int = 30) -> str:
            """Execute a shell command inside current workspace."""
            workspace = self._active_workspace()
            timeout = max(1, min(timeout_seconds, 300))
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                return f"Timeout after {timeout}s: {command}"
            except Exception as exc:  # noqa: BLE001
                return f"Terminal error: {exc}"

            output = (result.stdout or "") + (result.stderr or "")
            output = output.strip()
            if len(output) > 12000:
                output = output[:12000] + "\n...[truncated]"
            if not output:
                output = "(no output)"
            return f"exit_code={result.returncode}\n{output}"

        @tool
        def python_repl(code: str) -> str:
            """Run Python code in a workspace-scoped REPL state."""
            workspace = self._active_workspace()
            state = self._python_state.setdefault(str(workspace), {})
            if "__builtins__" not in state:
                state["__builtins__"] = __builtins__

            buffer = io.StringIO()
            mode: str
            compiled: Any
            try:
                compiled = compile(code, "<python_repl>", "eval")
                mode = "eval"
            except SyntaxError:
                try:
                    compiled = compile(code, "<python_repl>", "exec")
                except SyntaxError as exc:
                    return "".join(traceback.format_exception(exc, limit=3, chain=False)).strip()
                mode = "exec"

            try:
                with redirect_stdout(buffer), redirect_stderr(buffer):
                    if mode == "eval":
                        result = eval(compiled, state, state)
                    else:
                        exec(compiled, state, state)
                        result = None
            except Exception:  # noqa: BLE001
                return traceback.format_exc(limit=3, chain=False).strip()

            output = buffer.getvalue()
            if result is not None:
                output += repr(result)
            return output.strip() if output.strip() else "OK"

        @tool
        def read_file(path: str, max_chars: int = 20000) -> str:
            """Read a UTF-8 text file inside workspace."""
            try:
                target = self._resolve_workspace_path(path, allow_skills_dir=True)
            except ValueError as exc:
                return str(exc)
            if not target.exists():
                return f"File not found: {path}"
            if target.is_dir():
                return f"Path is a directory: {path}"
            text = target.read_text(encoding="utf-8")
            if len(text) > max_chars:
                return text[:max_chars] + "\n\n[truncated]"
            return text

        @tool
        def write_file(path: str, content: str, append: bool = False) -> str:
            """Write UTF-8 text file inside workspace."""
            try:
                target = self._resolve_workspace_path(path, create_parent=True)
            except ValueError as exc:
                return str(exc)
            mode = "a" if append else "w"
            with target.open(mode, encoding="utf-8") as fp:
                fp.write(content)
            action = "Appended" if append else "Wrote"
            return f"{action} {len(content)} chars to {target}"

        @tool
        def list_files(path: str = ".", recursive: bool = False, max_entries: int = 200) -> str:
            """List files/dirs under a workspace path."""
            try:
                target = self._resolve_workspace_path(path, allow_skills_dir=True)
            except ValueError as exc:
                return str(exc)
            if not target.exists():
                return f"Path not found: {path}"
            if target.is_file():
                return str(target.relative_to(self._active_workspace()))

            items = (
                sorted(target.rglob("*"))
                if recursive
                else sorted(target.iterdir())
            )
            rels = [str(item.relative_to(self._active_workspace())) for item in items[:max_entries]]
            if not rels:
                return "(empty)"
            suffix = "\n...[truncated]" if len(items) > max_entries else ""
            return "\n".join(rels) + suffix

        @tool
        def glob_files(pattern: str = "**/*", max_entries: int = 200) -> str:
            """Glob files under current workspace or skills directory."""
            workspace = self._active_workspace()
            if Path(pattern).is_absolute():
                return "Absolute glob pattern is not allowed."
            matches = sorted(workspace.glob(pattern))
            skills_matches: list[Path] = []
            if self._skills_dir.exists():
                skills_matches = sorted(self._skills_dir.glob(pattern))
            all_matches = sorted(set(matches + skills_matches))
            rels: list[str] = []
            for item in all_matches[:max_entries]:
                if item == workspace or item.is_relative_to(workspace):
                    rels.append(str(item.relative_to(workspace)))
                elif item == self._skills_dir or item.is_relative_to(self._skills_dir):
                    rels.append(f"skills::{item.relative_to(self._skills_dir)}")
                else:
                    rels.append(str(item))
            if not rels:
                return "(no matches)"
            suffix = "\n...[truncated]" if len(all_matches) > max_entries else ""
            return "\n".join(rels) + suffix

        candidates = [
            memory_search,
            memory_save,
            schedule_task,
            list_scheduled_tasks,
            remove_scheduled_task,
            skill_read,
            terminal,
            python_repl,
            read_file,
            write_file,
            list_files,
            glob_files,
        ]

        if not self._allowed_tools:
            return candidates

        return [tool_item for tool_item in candidates if tool_item.name in self._allowed_tools]


def _last_ai_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return _message_text(msg).strip()
    return ""


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                item_type = str(item.get("type", "")).lower()
                if item_type in {"text", "output_text", "text_delta"} or "text" in item:
                    parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    try:
        return json.dumps(content, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return str(content)


def _chunk_text(text: str, width: int) -> list[str]:
    if not text:
        return []
    return [text[i : i + width] for i in range(0, len(text), width)]


def _coerce_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _extract_text_deltas(chunk: Any) -> list[str]:
    text_types = {"text", "output_text", "text_delta"}
    if chunk is None:
        return []
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict):
                item_type = str(item.get("type", "")).lower()
                if item_type in text_types:
                    texts.append(str(item.get("text", "")))
                elif "text" in item and item_type not in {"thinking", "reasoning", "reasoning_content"}:
                    texts.append(str(item.get("text", "")))
        return texts
    if isinstance(chunk, str):
        return [chunk]
    return []


def _extract_thinking_deltas(chunk: Any) -> list[str]:
    thinking_types = {"thinking", "reasoning", "reasoning_content", "thinking_delta"}
    if chunk is None:
        return []

    texts: list[str] = []
    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "")).lower()
            if item_type in thinking_types and "text" in item:
                texts.append(str(item.get("text", "")))

    additional = getattr(chunk, "additional_kwargs", None)
    if isinstance(additional, dict):
        for key in ("reasoning", "thinking"):
            value = additional.get(key)
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, list):
                for entry in value:
                    if isinstance(entry, str):
                        texts.append(entry)
                    elif isinstance(entry, dict) and "text" in entry:
                        texts.append(str(entry.get("text", "")))

    return [text for text in texts if text]


def _format_tool_output(value: Any) -> str:
    if value is None:
        return "(no output)"

    content_value = value
    if isinstance(value, BaseMessage):
        content_value = value.content
    elif hasattr(value, "content"):
        content_value = getattr(value, "content")

    if isinstance(content_value, str):
        text = content_value
    elif isinstance(content_value, list):
        parts: list[str] = []
        for item in content_value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        text = "\n".join(part for part in parts if part)
    else:
        try:
            text = json.dumps(content_value, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            text = str(content_value)

    text = text.strip()
    if not text:
        return "(no output)"
    if len(text) > 5000:
        return text[:5000] + "\n...[truncated]"
    return text


def _is_context_length_error(exc: Exception) -> bool:
    text = str(exc).lower()
    keywords = (
        "context length",
        "maximum context",
        "token limit",
        "too many tokens",
        "prompt is too long",
    )
    return any(keyword in text for keyword in keywords)


__all__ = ["LangGraphAgent"]
