from __future__ import annotations

import heapq
import itertools
import json
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Protocol

from .config import AppConfig
from .graph_agent import GraphAgent
from .model_client import OpenAICompatibleModelClient, UsageRecord
from .planner import TaskPlanner
from .rendering import ConsoleRenderer, NullRenderer
from .task_store import (
    TaskCheckpointRecord,
    TaskIpcMessageRecord,
    TaskProcessRecord,
    TaskStore,
    TaskTargetRecord,
    TaskUnitRecord,
)
from .tools import ToolExecutionContext, ToolRegistry


class ProcessState(str, Enum):
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    ZOMBIE = "zombie"


class PriorityClass(str, Enum):
    REALTIME = "realtime"
    HIGH = "high"
    NORMAL = "normal"
    BACKGROUND = "background"


class UnitState(str, Enum):
    INACTIVE = "inactive"
    ACTIVATING = "activating"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class RestartPolicy(str, Enum):
    NEVER = "never"
    ON_FAILURE = "on_failure"


class TargetState(str, Enum):
    INACTIVE = "inactive"
    ACTIVATING = "activating"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class Capability(str, Enum):
    PLAN_TASK = "plan_task"
    ROUTE_TASK = "route_task"
    RETRIEVE_MEMORY = "retrieve_memory"
    USE_TOOLS = "use_tools"
    SPAWN_CHILD = "spawn_child"
    JOIN_PROCESS = "join_process"
    AWAIT_IPC = "await_ipc"
    PUMP_SCHEDULER = "pump_scheduler"
    USE_IPC = "use_ipc"
    CRITIQUE_OUTPUT = "critique_output"
    VERIFY_OUTPUT = "verify_output"
    COMPRESS_CONTEXT = "compress_context"
    WRITE_MEMORY = "write_memory"
    MANAGE_TASK = "manage_task"
    RESTORE_CHECKPOINT = "restore_checkpoint"
    WEB_ACCESS = "web_access"


@dataclass
class AgentNamespace:
    task_namespace: str
    repo_namespace: list[str]
    memory_namespace: list[str]
    tool_allowlist: list[str]
    identity: str
    network_access: bool
    mounts: dict[str, str]


@dataclass
class ResourceQuota:
    token_budget: int
    tool_call_budget: int
    child_agent_budget: int
    retry_budget: int
    tool_calls_used: int = 0
    child_agents_used: int = 0


@dataclass
class AgentProcess:
    process_id: str
    task_id: str
    parent_process_id: str
    agent_type: str
    priority: str
    state: str
    wait_kind: str
    wait_target: str
    wait_payload: dict[str, Any]
    capabilities: set[str]
    namespace: AgentNamespace
    quota: ResourceQuota
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] = field(default_factory=dict)
    last_error: str = ""
    created_at: str = field(default_factory=lambda: _utcnow())
    updated_at: str = field(default_factory=lambda: _utcnow())


@dataclass(frozen=True)
class ProcessResult:
    payload: dict[str, Any]
    summary: str
    usage: UsageRecord | None = None


@dataclass(frozen=True)
class UnitTemplate:
    template_name: str
    agent_type: str
    default_priority: str
    restart_policy: str = RestartPolicy.NEVER.value
    max_restart_attempts: int = 0
    timeout_seconds: int = 0
    after_templates: tuple[str, ...] = ()
    before_templates: tuple[str, ...] = ()
    on_failure_templates: tuple[str, ...] = ()
    on_success_templates: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class TargetTemplate:
    template_name: str
    default_dependencies: tuple[str, ...] = ()
    on_success_targets: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class UnitRunSpec:
    unit_name: str
    template_name: str
    payload: dict[str, Any]
    priority: str | None = None
    parent_process_id: str = ""
    capabilities: set[str] | None = None
    namespace: AgentNamespace | None = None
    quota: ResourceQuota | None = None
    dependencies: list[str] | None = None
    step_index: int = 0
    parent_unit_name: str = ""
    metadata: dict[str, Any] | None = None
    auto_activate: bool = True


class ProcessBlocked(RuntimeError):
    def __init__(
        self,
        *,
        wait_kind: str,
        wait_target: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(summary)
        self.wait_kind = wait_kind
        self.wait_target = wait_target
        self.summary = summary
        self.payload = payload or {}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _elapsed_seconds_since(value: str) -> float:
    return max(0.0, (datetime.now(timezone.utc) - _parse_iso_timestamp(value)).total_seconds())


def _truncate(text: str, limit: int = 280) -> str:
    compact = " ".join(str(text).split())
    return compact[:limit]


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_dataclass(value):
        return {key: _json_ready(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return str(value)


def _preview_payload(payload: dict[str, Any]) -> str:
    try:
        serialized = json.dumps(_json_ready(payload), ensure_ascii=False)
    except TypeError:
        serialized = str(payload)
    return _truncate(serialized, limit=400)


def _extract_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("No JSON payload returned")
    if stripped.startswith("```"):
        parts = stripped.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                return json.loads(candidate)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return json.loads(stripped[start : end + 1])
    raise ValueError("No JSON object found")


def _looks_like_unexecuted_tool_markup(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    if stripped.startswith("<tool_call"):
        return True
    return "<function=" in stripped and "<parameter=" in stripped


def _result_is_error_text(text: str) -> bool:
    lowered = str(text).strip().lower()
    return any(
        lowered.startswith(prefix)
        for prefix in (
            "tool_error:",
            "file_error:",
            "search_error:",
            "browser_error:",
            "calculation_error:",
        )
    )


def _default_tool_allowlist(base_tool_names: set[str]) -> list[str]:
    preferred_order = [
        "current_time",
        "calculator",
        "server_health",
        "list_workspace_files",
        "read_workspace_file",
        "search_workspace_text",
        "write_workspace_file",
        "replace_text_in_workspace_file",
        "web_search",
        "browser_fetch",
    ]
    return [name for name in preferred_order if name in base_tool_names]


def _normalize_route_name(
    route: str,
    *,
    needs_web: bool = False,
    needs_files: bool = False,
    requires_multimodal: bool = False,
) -> str:
    normalized = str(route).strip().lower()
    aliases = {
        "workspace_execution": "development",
        "development": "development",
        "coding": "development",
        "code": "development",
        "web_research": "research",
        "research": "research",
        "analysis": "analysis",
        "qa": "qa",
        "multimodal": "multimodal",
        "task": "task",
    }
    if normalized in aliases:
        return aliases[normalized]
    if needs_web:
        return "research"
    if needs_files:
        return "development"
    if requires_multimodal:
        return "multimodal"
    return "task"


def _contains_any_marker(*texts: str, markers: list[str]) -> bool:
    for marker in markers:
        if not marker:
            continue
        for text in texts:
            if marker in text:
                return True
    return False


def _heuristic_route(
    user_request: str,
    attachments: list[dict[str, str]],
    tool_names: set[str],
) -> dict[str, Any]:
    request = user_request.lower()
    request_raw = user_request
    attachment_count = len(attachments)
    needs_web = _contains_any_marker(
        request,
        request_raw,
        markers=[
            "联网",
            "搜索",
            "查一下",
            "最新",
            "调研",
            "资料",
            "来源",
            "引用",
            "web",
            "网站",
            "news",
            "openapi",
        ],
    ) and ("web_search" in tool_names or "browser_fetch" in tool_names)
    needs_files = _contains_any_marker(
        request,
        request_raw,
        markers=[
            "文件",
            "代码",
            "workspace",
            "写入",
            "读取",
            "修改",
            "替换",
            "开发",
            "实现",
            "编写",
            "创建",
            "制作",
            "构建",
            "搭建",
            "修复",
            "重构",
            "项目",
            "应用",
            "程序",
            "网站",
            "系统",
            "游戏",
            "功能",
            "接口",
            "组件",
            "页面",
            "agent",
            "repo",
            "仓库",
            "read",
            "write",
            "edit",
            "file",
            "files",
            "code",
            "project",
            "app",
            "game",
            "system",
            "bug",
            "fix",
            "refactor",
            "implement",
            "develop",
            "build",
            "create",
        ],
    )
    route = _normalize_route_name(
        "multimodal" if attachment_count else "task",
        needs_web=needs_web,
        needs_files=needs_files,
        requires_multimodal=bool(attachment_count),
    )
    if needs_web:
        route = "research"
    elif needs_files:
        route = "development"

    allowlist = ["current_time", "calculator", "server_health"]
    if needs_files:
        allowlist.extend(
            [
                "list_workspace_files",
                "read_workspace_file",
                "search_workspace_text",
                "write_workspace_file",
                "replace_text_in_workspace_file",
            ]
        )
    if needs_web:
        allowlist.append("web_search")
        allowlist.append("browser_fetch")

    filtered_allowlist = [name for name in allowlist if name in tool_names]
    return {
        "route": route,
        "needs_retrieval": True,
        "needs_web": needs_web,
        "needs_files": needs_files,
        "requires_multimodal": bool(attachment_count),
        "suggested_tool_allowlist": filtered_allowlist or _default_tool_allowlist(tool_names),
        "reason": "Heuristic route selected based on request keywords and attachment presence.",
        "execution_notes": "When using tools or files, preserve groundedness and mention concrete evidence.",
    }


def _model_json_call(
    *,
    client: OpenAICompatibleModelClient,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    temperature: float,
) -> tuple[dict[str, Any] | None, str, UsageRecord]:
    response = client.stream_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        tools=[],
        renderer=NullRenderer(),
        allow_tools=False,
        max_tokens_override=max_tokens,
        temperature_override=temperature,
        top_p_override=0.9,
    )
    raw = response.assistant_message.get("content", "").strip()
    try:
        return _extract_json_payload(raw), raw, response.usage
    except Exception:
        return None, raw, response.usage


class HarnessAgent(Protocol):
    agent_type: str

    def run(
        self,
        *,
        kernel: "AgentKernel",
        process: AgentProcess,
        payload: dict[str, Any],
    ) -> ProcessResult:
        ...


class AgentScheduler:
    _WEIGHTS = {
        PriorityClass.REALTIME.value: 0,
        PriorityClass.HIGH.value: 1,
        PriorityClass.NORMAL.value: 2,
        PriorityClass.BACKGROUND.value: 3,
    }

    def __init__(self) -> None:
        self._queue: list[tuple[int, int, str]] = []
        self._counter = itertools.count()

    def enqueue(self, process: AgentProcess, *, weight_override: int | None = None) -> None:
        heapq.heappush(
            self._queue,
            (
                (
                    weight_override
                    if weight_override is not None
                    else self._WEIGHTS.get(
                        process.priority,
                        self._WEIGHTS[PriorityClass.NORMAL.value],
                    )
                ),
                next(self._counter),
                process.process_id,
            ),
        )

    def pop(
        self,
        processes: dict[str, AgentProcess],
        *,
        task_id: str | None = None,
    ) -> AgentProcess | None:
        skipped: list[tuple[int, int, str]] = []
        while self._queue:
            priority, order, process_id = heapq.heappop(self._queue)
            process = processes.get(process_id)
            if (
                process is not None
                and process.state == ProcessState.READY.value
                and (task_id is None or process.task_id == task_id)
            ):
                for item in skipped:
                    heapq.heappush(self._queue, item)
                return process
            skipped.append((priority, order, process_id))
        for item in skipped:
            heapq.heappush(self._queue, item)
        return None


class ProcessToolRegistry:
    def __init__(
        self,
        base_registry: ToolRegistry,
        broker: "SyscallBroker",
        process: AgentProcess,
    ) -> None:
        self._base_registry = base_registry
        self._broker = broker
        self._process = process

    @property
    def openai_tools(self) -> list[dict[str, Any]]:
        allowlist = set(self._process.namespace.tool_allowlist)
        return self._base_registry.to_openai_tools(allowlist) + self._broker.openai_tools_for(
            self._process
        )

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        return self._broker.call(self._process, name, arguments)


class SyscallBroker:
    def __init__(
        self,
        *,
        base_registry: ToolRegistry,
        task_store: TaskStore,
        renderer: ConsoleRenderer,
        spawn_process: Callable[..., Any],
        run_process: Callable[..., Any],
        pump_scheduler: Callable[..., Any],
        restore_checkpoint: Callable[..., Any],
        list_agent_types: Callable[..., Any],
        notify_ipc_delivery: Callable[..., Any],
        persist_process: Callable[..., Any],
        emit_event: Callable[..., Any],
    ) -> None:
        self._base_registry = base_registry
        self._task_store = task_store
        self._renderer = renderer
        self._spawn_kernel_process = spawn_process
        self._run_kernel_process = run_process
        self._pump_kernel_scheduler = pump_scheduler
        self._restore_kernel_checkpoint = restore_checkpoint
        self._list_kernel_agent_types = list_agent_types
        self._notify_ipc_delivery = notify_ipc_delivery
        self._persist_process = persist_process
        self._emit_event = emit_event
        self._syscall_specs = {
            "spawn_agent": self._spawn_agent_tool_spec,
            "run_process": self._run_process_tool_spec,
            "join_process": self._join_process_tool_spec,
            "pump_scheduler": self._pump_scheduler_tool_spec,
            "send_ipc_message": self._send_ipc_message_tool_spec,
            "read_ipc_messages": self._read_ipc_messages_tool_spec,
            "await_ipc_message": self._await_ipc_message_tool_spec,
            "restore_checkpoint": self._restore_checkpoint_tool_spec,
        }

    def _record_tool_trace(
        self,
        *,
        process: AgentProcess,
        kind: str,
        name: str,
        arguments: dict[str, Any],
        result: str,
        success: bool | None = None,
    ) -> None:
        self._task_store.record_tool_trace(
            task_id=process.task_id,
            process_id=process.process_id,
            kind=kind,
            name=name,
            arguments=_json_ready(arguments),
            result=result,
            success=(not _result_is_error_text(result)) if success is None else success,
        )

    def registry_for(self, process: AgentProcess) -> ProcessToolRegistry:
        return ProcessToolRegistry(self._base_registry, self, process)

    def openai_tools_for(self, process: AgentProcess) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        if Capability.USE_TOOLS.value not in process.capabilities:
            return tools

        if Capability.SPAWN_CHILD.value in process.capabilities:
            tools.extend(
                [
                    self._spawn_agent_tool_spec(),
                    self._run_process_tool_spec(),
                    self._join_process_tool_spec(),
                    self._pump_scheduler_tool_spec(),
                ]
            )
        if Capability.USE_IPC.value in process.capabilities:
            tools.extend(
                [
                    self._send_ipc_message_tool_spec(),
                    self._read_ipc_messages_tool_spec(),
                    self._await_ipc_message_tool_spec(),
                ]
            )
        if Capability.RESTORE_CHECKPOINT.value in process.capabilities:
            tools.append(self._restore_checkpoint_tool_spec())
        return tools

    def call(self, process: AgentProcess, name: str, arguments: dict[str, Any]) -> str:
        if name in self._syscall_specs:
            return self.call_syscall(process, name, arguments)
        return self.call_tool(process, name, arguments)

    def call_tool(self, process: AgentProcess, name: str, arguments: dict[str, Any]) -> str:
        error = self._reserve_syscall_invocation(process, name, "syscall.tool", arguments)
        if error:
            self._record_tool_trace(
                process=process,
                kind="tool",
                name=name,
                arguments=arguments,
                result=error,
            )
            return error
        if name not in process.namespace.tool_allowlist:
            result = f"tool_error: namespace denied tool '{name}'"
            self._record_tool_trace(
                process=process,
                kind="tool",
                name=name,
                arguments=arguments,
                result=result,
            )
            return result
        if (
            name == "web_search"
            and Capability.WEB_ACCESS.value not in process.capabilities
        ) or (name == "web_search" and not process.namespace.network_access):
            result = "tool_error: network namespace denied web access"
            self._record_tool_trace(
                process=process,
                kind="tool",
                name=name,
                arguments=arguments,
                result=result,
            )
            return result
        result = self._base_registry.call(
            name,
            arguments,
            context=ToolExecutionContext(
                process_id=process.process_id,
                task_id=process.task_id,
                identity=process.namespace.identity,
                task_namespace=process.namespace.task_namespace,
                repo_namespace=tuple(process.namespace.repo_namespace),
                memory_namespace=tuple(process.namespace.memory_namespace),
                mounts=dict(process.namespace.mounts),
            ),
        )
        self._record_tool_trace(
            process=process,
            kind="tool",
            name=name,
            arguments=arguments,
            result=result,
        )
        return result

    def call_syscall(self, process: AgentProcess, name: str, arguments: dict[str, Any]) -> str:
        error = self._reserve_syscall_invocation(process, name, "syscall.kernel", arguments)
        if error:
            self._record_tool_trace(
                process=process,
                kind="syscall",
                name=name,
                arguments=arguments,
                result=error,
            )
            return error
        result = f"tool_error: unknown syscall '{name}'"
        try:
            if name == "spawn_agent":
                result = self._spawn_agent(process, arguments)
            elif name == "run_process":
                result = self._run_process(process, arguments)
            elif name == "join_process":
                result = self._join_process(process, arguments)
            elif name == "pump_scheduler":
                result = self._pump_scheduler(process, arguments)
            elif name == "send_ipc_message":
                result = self._send_ipc_message(process, arguments)
            elif name == "read_ipc_messages":
                result = self._read_ipc_messages(process, arguments)
            elif name == "await_ipc_message":
                result = self._await_ipc_message(process, arguments)
            elif name == "restore_checkpoint":
                result = self._restore_checkpoint(process, arguments)
        except ProcessBlocked as blocked:
            self._record_tool_trace(
                process=process,
                kind="syscall",
                name=name,
                arguments=arguments,
                result=f"blocked: {blocked.summary}",
                success=False,
            )
            raise
        self._record_tool_trace(
            process=process,
            kind="syscall",
            name=name,
            arguments=arguments,
            result=result,
        )
        return result

    def _reserve_syscall_invocation(
        self,
        process: AgentProcess,
        name: str,
        kind: str,
        arguments: dict[str, Any],
    ) -> str:
        if Capability.USE_TOOLS.value not in process.capabilities:
            return "tool_error: capability denied: use_tools"
        if process.quota.tool_calls_used >= process.quota.tool_call_budget:
            return "tool_error: tool call quota exhausted"
        process.quota.tool_calls_used += 1
        process.updated_at = _utcnow()
        self._persist_process(process)
        self._emit_event(
            task_id=process.task_id,
            process_id=process.process_id,
            parent_process_id=process.parent_process_id,
            kind=kind,
            level="info",
            message=f"{process.agent_type} called {name}",
            payload={"arguments": _json_ready(arguments)},
        )
        return ""

    def _spawn_agent_tool_spec(self) -> dict[str, Any]:
        agent_types = ", ".join(sorted(self._list_kernel_agent_types()))
        return {
            "type": "function",
            "function": {
                "name": "spawn_agent",
                "description": (
                    "Spawn a harness child process inside the same AgentOS task namespace. "
                    f"Available child agent types: {agent_types}."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "Harness agent type to spawn.",
                        },
                        "payload": {
                            "type": "object",
                            "description": "Input payload passed to the child process.",
                            "additionalProperties": True,
                        },
                        "priority": {
                            "type": "string",
                            "description": "Process priority: realtime, high, normal, or background.",
                        },
                        "run_mode": {
                            "type": "string",
                            "description": "Use 'queued' to create the child without executing it yet, or 'immediate' to run it now.",
                            "enum": ["queued", "immediate"],
                        },
                        "tool_allowlist": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional tool allowlist for the child namespace.",
                        },
                        "repo_namespace": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional Agent VFS repo mounts visible to the child.",
                        },
                        "memory_namespace": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional Agent VFS memory mounts visible to the child.",
                        },
                        "network_access": {
                            "type": "boolean",
                            "description": "Whether the child namespace may access the network.",
                        },
                        "child_token_budget": {"type": "integer", "minimum": 0},
                        "child_tool_call_budget": {"type": "integer", "minimum": 0},
                        "child_agent_budget": {"type": "integer", "minimum": 0},
                        "child_retry_budget": {"type": "integer", "minimum": 0},
                    },
                    "required": ["agent_type", "payload"],
                    "additionalProperties": False,
                },
            },
        }

    def _run_process_tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "run_process",
                "description": "Run a queued or waiting child process in the current AgentOS task.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "process_id": {
                            "type": "string",
                            "description": "Process ID to dispatch.",
                        }
                    },
                    "required": ["process_id"],
                    "additionalProperties": False,
                },
            },
        }

    def _join_process_tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "join_process",
                "description": "Wait for a child process to complete. If unavailable, the caller becomes WAITING.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "process_id": {
                            "type": "string",
                            "description": "Child process ID to join.",
                        },
                        "blocking": {
                            "type": "boolean",
                            "description": "Whether to block the caller when the child is not finished yet.",
                        },
                    },
                    "required": ["process_id"],
                    "additionalProperties": False,
                },
            },
        }

    def _pump_scheduler_tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "pump_scheduler",
                "description": "Run queued READY processes for the current task namespace until the scheduler quiesces.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 32,
                            "description": "Maximum number of processes to run in one pump.",
                        }
                    },
                    "additionalProperties": False,
                },
            },
        }

    def _send_ipc_message_tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "send_ipc_message",
                "description": "Send a persisted IPC message to another process in the same task namespace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "recipient_process_id": {
                            "type": "string",
                            "description": "Recipient process ID.",
                        },
                        "channel": {
                            "type": "string",
                            "description": "Logical IPC channel name.",
                        },
                        "message": {
                            "type": "string",
                            "description": "Short human-readable IPC message.",
                        },
                        "payload": {
                            "type": "object",
                            "description": "Optional structured IPC payload.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["recipient_process_id", "message"],
                    "additionalProperties": False,
                },
            },
        }

    def _read_ipc_messages_tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "read_ipc_messages",
                "description": "Read IPC messages addressed to the current process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Optional channel filter.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                            "description": "Maximum number of messages to return.",
                        },
                        "consume": {
                            "type": "boolean",
                            "description": "When true, marks returned messages as delivered.",
                        },
                    },
                    "additionalProperties": False,
                },
            },
        }

    def _await_ipc_message_tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "await_ipc_message",
                "description": "Wait for an IPC message addressed to the current process. If none is pending, the caller becomes WAITING.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Optional channel filter.",
                        },
                        "blocking": {
                            "type": "boolean",
                            "description": "Whether to block the caller when no IPC message is pending.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                            "description": "Maximum number of messages to consume.",
                        },
                    },
                    "additionalProperties": False,
                },
            },
        }

    def _restore_checkpoint_tool_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "restore_checkpoint",
                "description": "Restore a process from a persisted checkpoint snapshot and optionally rerun it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "checkpoint_id": {
                            "type": "string",
                            "description": "Specific checkpoint ID to restore.",
                        },
                        "process_id": {
                            "type": "string",
                            "description": "Restore the latest executable checkpoint for this process.",
                        },
                        "run_mode": {
                            "type": "string",
                            "enum": ["queued", "immediate"],
                            "description": "Use 'queued' to only recreate the process, or 'immediate' to rerun it now.",
                        },
                        "priority": {
                            "type": "string",
                            "description": "Optional priority override for the restored process.",
                        },
                    },
                    "additionalProperties": False,
                },
            },
        }

    def _spawn_agent(self, process: AgentProcess, arguments: dict[str, Any]) -> str:
        if Capability.SPAWN_CHILD.value not in process.capabilities:
            return "tool_error: capability denied: spawn_child"

        agent_type = str(arguments.get("agent_type", "")).strip()
        if not agent_type:
            return "tool_error: missing agent_type"
        if agent_type not in self._list_kernel_agent_types():
            return f"tool_error: unknown child agent type '{agent_type}'"

        payload = arguments.get("payload", {})
        if not isinstance(payload, dict):
            return "tool_error: payload must be an object"

        run_mode = str(arguments.get("run_mode", "immediate")).strip().lower() or "immediate"
        if run_mode not in {"queued", "immediate"}:
            return "tool_error: run_mode must be 'queued' or 'immediate'"

        tool_allowlist = arguments.get("tool_allowlist")
        repo_namespace = arguments.get("repo_namespace")
        memory_namespace = arguments.get("memory_namespace")
        child_namespace = AgentNamespace(
            task_namespace=process.namespace.task_namespace,
            repo_namespace=(
                [str(item) for item in repo_namespace]
                if isinstance(repo_namespace, list) and repo_namespace
                else list(process.namespace.repo_namespace)
            ),
            memory_namespace=(
                [str(item) for item in memory_namespace]
                if isinstance(memory_namespace, list) and memory_namespace
                else list(process.namespace.memory_namespace)
            ),
            tool_allowlist=(
                [str(item) for item in tool_allowlist]
                if isinstance(tool_allowlist, list) and tool_allowlist
                else list(process.namespace.tool_allowlist)
            ),
            identity=agent_type,
            network_access=bool(
                arguments.get("network_access", process.namespace.network_access)
            ),
            mounts=dict(process.namespace.mounts),
        )
        child_quota = ResourceQuota(
            token_budget=max(
                0,
                int(arguments.get("child_token_budget", process.quota.token_budget)),
            ),
            tool_call_budget=max(
                0,
                int(
                    arguments.get(
                        "child_tool_call_budget",
                        process.quota.tool_call_budget,
                    )
                ),
            ),
            child_agent_budget=max(
                0,
                int(
                    arguments.get(
                        "child_agent_budget",
                        process.quota.child_agent_budget,
                    )
                ),
            ),
            retry_budget=max(
                0,
                int(arguments.get("child_retry_budget", process.quota.retry_budget)),
            ),
        )
        priority = (
            str(arguments.get("priority", process.priority)).strip() or process.priority
        )

        try:
            child = self._spawn_kernel_process(
                task_id=process.task_id,
                agent_type=agent_type,
                payload=payload,
                priority=priority,
                parent_process_id=process.process_id,
                capabilities=None,
                namespace=child_namespace,
                quota=child_quota,
            )
        except Exception as exc:
            return f"tool_error: {exc}"

        response: dict[str, Any] = {
            "process_id": child.process_id,
            "agent_type": child.agent_type,
            "state": child.state,
            "run_mode": run_mode,
            "parent_process_id": child.parent_process_id,
            "parent_child_agents_used": process.quota.child_agents_used,
            "parent_child_agent_budget": process.quota.child_agent_budget,
        }
        if run_mode == "immediate":
            try:
                result = self._run_kernel_process(child.process_id)
            except Exception as exc:
                response["state"] = ProcessState.FAILED.value
                response["error"] = str(exc)
            else:
                response["state"] = child.state
                response["summary"] = result.summary
                response["result_payload"] = _json_ready(result.payload)
        return json.dumps(response, ensure_ascii=False, indent=2)

    def _run_process(self, process: AgentProcess, arguments: dict[str, Any]) -> str:
        if Capability.SPAWN_CHILD.value not in process.capabilities and Capability.MANAGE_TASK.value not in process.capabilities:
            return "tool_error: capability denied: spawn_child"

        target_process_id = str(arguments.get("process_id", "")).strip()
        if not target_process_id:
            return "tool_error: missing process_id"

        try:
            target = self._task_store.get_process(target_process_id)
        except KeyError:
            return f"tool_error: unknown process_id '{target_process_id}'"
        if target.task_id != process.task_id:
            return "tool_error: cannot run a process from another task namespace"
        if (
            Capability.MANAGE_TASK.value not in process.capabilities
            and target.parent_process_id not in {"", process.process_id}
            and target.process_id != process.process_id
        ):
            return "tool_error: cannot run a non-child process without manage_task"

        try:
            result = self._run_kernel_process(target_process_id)
        except Exception as exc:
            return f"tool_error: {exc}"
        return json.dumps(
            {
                "process_id": target_process_id,
                "state": self._task_store.get_process(target_process_id).state,
                "summary": result.summary,
                "result_payload": _json_ready(result.payload),
            },
            ensure_ascii=False,
            indent=2,
        )

    def _join_process(self, process: AgentProcess, arguments: dict[str, Any]) -> str:
        if (
            Capability.JOIN_PROCESS.value not in process.capabilities
            and Capability.MANAGE_TASK.value not in process.capabilities
        ):
            return "tool_error: capability denied: join_process"

        target_process_id = str(arguments.get("process_id", "")).strip()
        if not target_process_id:
            return "tool_error: missing process_id"

        try:
            target = self._task_store.get_process(target_process_id)
        except KeyError:
            return f"tool_error: unknown process_id '{target_process_id}'"
        if target.task_id != process.task_id:
            return "tool_error: cannot join a process from another task namespace"
        if target.process_id == process.process_id:
            return "tool_error: a process cannot join itself"
        if (
            Capability.MANAGE_TASK.value not in process.capabilities
            and target.parent_process_id not in {"", process.process_id}
        ):
            return "tool_error: cannot join a non-child process without manage_task"

        blocking = bool(arguments.get("blocking", True))
        if target.state in {ProcessState.COMPLETED.value, ProcessState.FAILED.value}:
            return json.dumps(
                {
                    "process_id": target.process_id,
                    "state": target.state,
                    "last_error": target.last_error,
                    "summary": target.output_preview or target.last_error,
                    "joined": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        if not blocking:
            return json.dumps(
                {
                    "process_id": target.process_id,
                    "state": target.state,
                    "joined": False,
                    "waiting": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        raise ProcessBlocked(
            wait_kind="process",
            wait_target=target.process_id,
            summary=f"waiting for process {target.process_id}",
            payload={
                "blocking": True,
                "target_state": target.state,
                "parent_process_id": process.process_id,
            },
        )

    def _pump_scheduler(self, process: AgentProcess, arguments: dict[str, Any]) -> str:
        if (
            Capability.PUMP_SCHEDULER.value not in process.capabilities
            and Capability.MANAGE_TASK.value not in process.capabilities
        ):
            return "tool_error: capability denied: pump_scheduler"

        limit = max(1, min(int(arguments.get("limit", 32)), 64))
        result = self._pump_kernel_scheduler(
            task_id=process.task_id,
            limit=limit,
            requested_by_process_id=process.process_id,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _await_ipc_message(self, process: AgentProcess, arguments: dict[str, Any]) -> str:
        if (
            Capability.AWAIT_IPC.value not in process.capabilities
            and Capability.MANAGE_TASK.value not in process.capabilities
        ):
            return "tool_error: capability denied: await_ipc"

        channel = str(arguments.get("channel", "")).strip()
        limit = max(1, min(int(arguments.get("limit", 20)), 50))
        consume = bool(arguments.get("consume", True))
        blocking = bool(arguments.get("blocking", True))

        messages = self._task_store.list_ipc_messages(
            process.task_id,
            recipient_process_id=process.process_id,
            channel=channel,
            limit=limit,
            include_delivered=False,
        )
        if messages:
            if consume:
                messages = self._task_store.consume_ipc_messages(
                    task_id=process.task_id,
                    recipient_process_id=process.process_id,
                    channel=channel,
                    limit=limit,
                )
            return json.dumps(
                {
                    "count": len(messages),
                    "waiting": False,
                    "messages": [
                        {
                            "message_id": item.message_id,
                            "sender_process_id": item.sender_process_id,
                            "recipient_process_id": item.recipient_process_id,
                            "channel": item.channel,
                            "message": item.message,
                            "payload": _json_ready(item.payload),
                            "status": item.status,
                            "created_at": item.created_at,
                            "read_at": item.read_at,
                        }
                        for item in messages
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        if not blocking:
            return json.dumps(
                {
                    "count": 0,
                    "waiting": True,
                    "channel": channel or "default",
                    "consume": consume,
                },
                ensure_ascii=False,
                indent=2,
            )
        raise ProcessBlocked(
            wait_kind="ipc",
            wait_target=process.process_id,
            summary=f"waiting for IPC on {channel or 'default'}",
            payload={
                "channel": channel,
                "consume": consume,
                "limit": limit,
            },
        )

    def _send_ipc_message(self, process: AgentProcess, arguments: dict[str, Any]) -> str:
        if Capability.USE_IPC.value not in process.capabilities:
            return "tool_error: capability denied: use_ipc"

        recipient_process_id = str(arguments.get("recipient_process_id", "")).strip()
        if not recipient_process_id:
            return "tool_error: missing recipient_process_id"
        try:
            recipient = self._task_store.get_process(recipient_process_id)
        except KeyError:
            return f"tool_error: unknown process_id '{recipient_process_id}'"
        if recipient.task_id != process.task_id:
            return "tool_error: cannot send IPC across task namespaces"

        message = str(arguments.get("message", "")).strip()
        if not message:
            return "tool_error: missing message"
        channel = str(arguments.get("channel", "default")).strip() or "default"
        payload = arguments.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return "tool_error: payload must be an object"

        record = self._task_store.create_ipc_message(
            task_id=process.task_id,
            sender_process_id=process.process_id,
            recipient_process_id=recipient_process_id,
            channel=channel,
            message=message,
            payload=_json_ready(payload),
        )
        woken = self._notify_ipc_delivery(
            task_id=process.task_id,
            recipient_process_id=recipient_process_id,
            channel=channel,
            message_id=record.message_id,
        )
        self._emit_event(
            task_id=process.task_id,
            process_id=process.process_id,
            parent_process_id=process.parent_process_id,
            kind="ipc.send",
            level="info",
            message=f"{process.process_id} sent IPC to {recipient_process_id}",
            payload={
                "message_id": record.message_id,
                "channel": channel,
                "woken": woken,
            },
        )
        return json.dumps(
            {
                "message_id": record.message_id,
                "recipient_process_id": recipient_process_id,
                "channel": channel,
                "status": record.status,
                "woken": woken,
            },
            ensure_ascii=False,
            indent=2,
        )

    def _read_ipc_messages(self, process: AgentProcess, arguments: dict[str, Any]) -> str:
        if Capability.USE_IPC.value not in process.capabilities:
            return "tool_error: capability denied: use_ipc"

        channel = str(arguments.get("channel", "")).strip()
        limit = max(1, min(int(arguments.get("limit", 20)), 50))
        consume = bool(arguments.get("consume", True))

        if consume:
            messages = self._task_store.consume_ipc_messages(
                task_id=process.task_id,
                recipient_process_id=process.process_id,
                channel=channel,
                limit=limit,
            )
        else:
            messages = self._task_store.list_ipc_messages(
                process.task_id,
                recipient_process_id=process.process_id,
                channel=channel,
                limit=limit,
                include_delivered=False,
            )
        return json.dumps(
            {
                "count": len(messages),
                "messages": [
                    {
                        "message_id": item.message_id,
                        "sender_process_id": item.sender_process_id,
                        "recipient_process_id": item.recipient_process_id,
                        "channel": item.channel,
                        "message": item.message,
                        "payload": _json_ready(item.payload),
                        "status": item.status,
                        "created_at": item.created_at,
                        "read_at": item.read_at,
                    }
                    for item in messages
                ],
            },
            ensure_ascii=False,
            indent=2,
        )

    def _restore_checkpoint(self, process: AgentProcess, arguments: dict[str, Any]) -> str:
        if Capability.RESTORE_CHECKPOINT.value not in process.capabilities and Capability.MANAGE_TASK.value not in process.capabilities:
            return "tool_error: capability denied: restore_checkpoint"

        checkpoint_id = str(arguments.get("checkpoint_id", "")).strip()
        process_id = str(arguments.get("process_id", "")).strip()
        if not checkpoint_id and not process_id:
            return "tool_error: provide checkpoint_id or process_id"
        run_mode = str(arguments.get("run_mode", "immediate")).strip().lower() or "immediate"
        if run_mode not in {"queued", "immediate"}:
            return "tool_error: run_mode must be 'queued' or 'immediate'"
        priority = str(arguments.get("priority", "")).strip()

        try:
            restored_process, checkpoint, result = self._restore_kernel_checkpoint(
                checkpoint_id=checkpoint_id or None,
                process_id=process_id or None,
                run_immediately=(run_mode == "immediate"),
                priority_override=priority or None,
                requested_by_process_id=process.process_id,
            )
        except Exception as exc:
            return f"tool_error: {exc}"

        response: dict[str, Any] = {
            "checkpoint_id": checkpoint.checkpoint_id,
            "restored_process_id": restored_process.process_id,
            "agent_type": restored_process.agent_type,
            "state": restored_process.state,
            "run_mode": run_mode,
        }
        if result is not None:
            response["summary"] = result.summary
            response["result_payload"] = _json_ready(result.payload)
        return json.dumps(response, ensure_ascii=False, indent=2)


class RouterHarnessAgent:
    agent_type = "router"

    def run(
        self,
        *,
        kernel: "AgentKernel",
        process: AgentProcess,
        payload: dict[str, Any],
    ) -> ProcessResult:
        if Capability.ROUTE_TASK.value not in process.capabilities:
            raise PermissionError("Router missing route_task capability")

        user_request = str(payload.get("user_request", "")).strip()
        attachments = list(payload.get("attachments", []))
        tool_names = set(kernel.base_tools.tool_names)

        parsed, raw, usage = _model_json_call(
            client=kernel.client,
            system_prompt=(
                "You are a routing agent for an AgentOS kernel. Decide which execution path "
                "fits the task. Return JSON only with keys: route (string), needs_retrieval "
                "(boolean), needs_web (boolean), needs_files (boolean), requires_multimodal "
                "(boolean), suggested_tool_allowlist (array of strings), reason (string), "
                "execution_notes (string). Be conservative and grounded."
            ),
            user_content=(
                f"User request:\n{user_request}\n\n"
                f"Attachments:\n{json.dumps(attachments, ensure_ascii=False)}\n\n"
                f"Available tools:\n{sorted(tool_names)}"
            ),
            max_tokens=512,
            temperature=0.1,
        )
        if parsed is None:
            route = _heuristic_route(user_request, attachments, tool_names)
            route["reason"] = f"{route['reason']} Model route fallback used."
            return ProcessResult(payload=route, summary=route["reason"], usage=usage)

        allowlist = [
            name
            for name in parsed.get("suggested_tool_allowlist", [])
            if isinstance(name, str) and name in tool_names
        ]
        route = {
            "route": _normalize_route_name(
                str(parsed.get("route", "task")).strip() or "task",
                needs_web=bool(parsed.get("needs_web", False)),
                needs_files=bool(parsed.get("needs_files", False)),
                requires_multimodal=bool(parsed.get("requires_multimodal", bool(attachments))),
            ),
            "needs_retrieval": bool(parsed.get("needs_retrieval", True)),
            "needs_web": bool(parsed.get("needs_web", False)),
            "needs_files": bool(parsed.get("needs_files", False)),
            "requires_multimodal": bool(parsed.get("requires_multimodal", bool(attachments))),
            "suggested_tool_allowlist": allowlist or _default_tool_allowlist(tool_names),
            "reason": str(parsed.get("reason", "Model router selected execution path.")).strip(),
            "execution_notes": str(
                parsed.get("execution_notes", "Route task carefully and preserve evidence.")
            ).strip(),
            "raw": _truncate(raw, limit=240),
        }
        return ProcessResult(
            payload=route,
            summary=f"Route={route['route']} | web={route['needs_web']} | files={route['needs_files']}",
            usage=usage,
        )


class RetrieverHarnessAgent:
    agent_type = "retriever"

    def run(
        self,
        *,
        kernel: "AgentKernel",
        process: AgentProcess,
        payload: dict[str, Any],
    ) -> ProcessResult:
        if Capability.RETRIEVE_MEMORY.value not in process.capabilities:
            raise PermissionError("Retriever missing retrieve_memory capability")

        query = str(payload.get("query", "")).strip()
        limit = max(1, int(payload.get("limit", kernel.config.storage.memory_search_limit)))
        memories = kernel.task_store.search_memories(query, limit)
        summary = f"Retrieved {len(memories)} memory records"
        return ProcessResult(
            payload={
                "query": query,
                "memories": memories,
                "memory_summaries": [item.summary for item in memories],
            },
            summary=summary,
        )


class PlannerHarnessAgent:
    agent_type = "planner"

    def run(
        self,
        *,
        kernel: "AgentKernel",
        process: AgentProcess,
        payload: dict[str, Any],
    ) -> ProcessResult:
        if Capability.PLAN_TASK.value not in process.capabilities:
            raise PermissionError("Planner missing plan_task capability")

        route_notes = str(payload.get("route_notes", "")).strip()
        user_request = str(payload.get("user_request", ""))
        if route_notes:
            user_request = f"{user_request}\n\nRouting notes:\n{route_notes}"

        plan, usage = kernel.planner.plan_with_usage(
            user_request=user_request,
            memories=list(payload.get("memories", [])),
            recent_tasks=list(payload.get("recent_tasks", [])),
        )
        return ProcessResult(
            payload={"plan": plan, "usage": usage},
            summary=f"Planned {len(plan.steps)} step(s) for '{plan.title}'",
            usage=usage,
        )


class ExecutorHarnessAgent:
    agent_type = "executor"

    def run(
        self,
        *,
        kernel: "AgentKernel",
        process: AgentProcess,
        payload: dict[str, Any],
    ) -> ProcessResult:
        messages = list(payload.get("messages", []))
        if not messages:
            raise ValueError("Executor received no messages")

        process_registry = kernel.syscall_broker.registry_for(process)
        executor = GraphAgent(kernel.config, kernel.client, process_registry, kernel.renderer)
        result, turn_summary, transcript, metadata = executor.run_messages_detailed(messages)
        tool_transcript = [
            item
            for item in transcript
            if item.get("role") in {"tool", "assistant"}
        ]
        finish_reason = str(metadata.get("finish_reason", "")).strip()
        raw_tool_markup_detected = _looks_like_unexecuted_tool_markup(result)
        summary = _truncate(result or "No executor output")
        if finish_reason == "length":
            summary = "executor output reached the model length limit"
        elif raw_tool_markup_detected:
            summary = "executor returned raw tool markup instead of a completed step result"
        return ProcessResult(
            payload={
                "content": result,
                "turn_summary": turn_summary,
                "tool_transcript": tool_transcript,
                "executor_finish_reason": finish_reason,
                "tool_rounds_used": int(metadata.get("tool_rounds_used", 0)),
                "max_tool_rounds_reached": bool(
                    metadata.get("max_tool_rounds_reached", False)
                ),
                "last_allow_tools": bool(metadata.get("last_allow_tools", True)),
                "raw_tool_markup_detected": raw_tool_markup_detected,
            },
            summary=summary,
        )


class CriticHarnessAgent:
    agent_type = "critic"

    def run(
        self,
        *,
        kernel: "AgentKernel",
        process: AgentProcess,
        payload: dict[str, Any],
    ) -> ProcessResult:
        if Capability.CRITIQUE_OUTPUT.value not in process.capabilities:
            raise PermissionError("Critic missing critique_output capability")

        parsed, raw, usage = _model_json_call(
            client=kernel.client,
            system_prompt=(
                "You are an adversarial critic inside an AgentOS runtime. Think like a GAN "
                "discriminator: try to detect fabricated claims, weak grounding, missing tool "
                "evidence, and brittle reasoning in the candidate output. Return JSON only with "
                "keys: approved (boolean), risk_score (number 0-1), summary (string), "
                "revision_request (string), failure_modes (array of strings)."
            ),
            user_content=(
                f"Task goal:\n{payload.get('task_goal', '')}\n\n"
                f"Step title:\n{payload.get('step_title', '')}\n\n"
                f"Step description:\n{payload.get('step_description', '')}\n\n"
                f"Tool transcript:\n{payload.get('tool_transcript', '')}\n\n"
                f"Candidate output:\n{payload.get('candidate_output', '')}\n\n"
                f"Prior results:\n{payload.get('prior_results', '')}\n\n"
                "Use the tool transcript as execution evidence. Judge harshly but fairly, but do "
                "not reject a result just because the final prose is concise if the tool evidence "
                "shows the required work actually happened."
            ),
            max_tokens=640,
            temperature=0.1,
        )
        if parsed is None:
            lowered = raw.lower()
            rejected_markers = [
                '"approved": false',
                "not approved",
                "needs revision",
                "please revise",
                "fabricated",
                "ungrounded",
            ]
            rejected = any(marker in lowered for marker in rejected_markers)
            result = {
                "approved": not rejected,
                "risk_score": 0.8 if rejected else 0.2,
                "summary": (
                    "Critic returned non-JSON output; fallback classification applied."
                ),
                "revision_request": _truncate(raw, limit=220) if rejected else "",
                "failure_modes": ["non_json_fallback"] if rejected else [],
            }
        else:
            failure_modes = [
                str(item).strip()
                for item in parsed.get("failure_modes", [])
                if str(item).strip()
            ]
            result = {
                "approved": bool(parsed.get("approved", True)),
                "risk_score": float(parsed.get("risk_score", 0.0)),
                "summary": str(parsed.get("summary", "")).strip(),
                "revision_request": str(parsed.get("revision_request", "")).strip(),
                "failure_modes": failure_modes,
            }
        return ProcessResult(
            payload={**result, "usage": usage},
            summary=result["summary"] or f"critic risk={result['risk_score']:.2f}",
            usage=usage,
        )


class VerifierHarnessAgent:
    agent_type = "verifier"

    def run(
        self,
        *,
        kernel: "AgentKernel",
        process: AgentProcess,
        payload: dict[str, Any],
    ) -> ProcessResult:
        if Capability.VERIFY_OUTPUT.value not in process.capabilities:
            raise PermissionError("Verifier missing verify_output capability")

        step_title = str(payload.get("step_title", "Step")).strip() or "Step"
        step_description = str(payload.get("step_description", "")).strip()
        candidate_output = str(payload.get("candidate_output", "")).strip()
        prior_results = str(payload.get("prior_results", "")).strip()

        parsed, raw, usage = _model_json_call(
            client=kernel.client,
            system_prompt=(
                "You are a strict execution verifier. Judge whether the candidate step result "
                "is grounded, complete enough for the requested step, and safe to accept. "
                "Return JSON only with keys: approved (boolean), status (string), summary "
                "(string), revision_request (string)."
            ),
            user_content=(
                f"Step title: {step_title}\n"
                f"Step description: {step_description}\n\n"
                f"Prior completed steps:\n{prior_results or 'None'}\n\n"
                f"Candidate output:\n{candidate_output}"
            ),
            max_tokens=512,
            temperature=0.1,
        )
        if parsed is None:
            lowered = raw.lower()
            rejected_markers = [
                '"approved": false',
                "not approved",
                "needs revision",
                "please revise",
                "revise the answer",
            ]
            approved = not any(marker in lowered for marker in rejected_markers)
            status = "approved" if approved else "revise"
            if approved:
                summary = "Verifier returned non-JSON output; accepted by fallback policy."
                revision_request = ""
            else:
                summary = _truncate(raw, limit=120)
                revision_request = _truncate(raw, limit=220)
        else:
            approved = bool(parsed.get("approved", True))
            status = str(parsed.get("status", "approved" if approved else "revise"))
            summary = str(parsed.get("summary", "")).strip()
            revision_request = str(parsed.get("revision_request", "")).strip()

        return ProcessResult(
            payload={
                "approved": approved,
                "status": status,
                "summary": summary,
                "revision_request": revision_request,
                "usage": usage,
            },
            summary=summary or status,
            usage=usage,
        )


class CompressorHarnessAgent:
    agent_type = "compressor"

    def run(
        self,
        *,
        kernel: "AgentKernel",
        process: AgentProcess,
        payload: dict[str, Any],
    ) -> ProcessResult:
        if Capability.COMPRESS_CONTEXT.value not in process.capabilities:
            raise PermissionError("Compressor missing compress_context capability")

        parsed, raw, usage = _model_json_call(
            client=kernel.client,
            system_prompt=(
                "You are a context compressor for long-running AgentOS tasks. Distill only the "
                "facts, file paths, decisions, unresolved risks, and constraints needed to keep "
                "future steps grounded. Return JSON only with keys: compressed_context (string), "
                "salient_facts (array of strings), open_questions (array of strings)."
            ),
            user_content=(
                f"Task goal:\n{payload.get('task_goal', '')}\n\n"
                f"Route notes:\n{payload.get('route_notes', '')}\n\n"
                f"Completed steps:\n{payload.get('completed_steps', '')}\n\n"
                f"Retrieved memories:\n{payload.get('memories', '')}\n\n"
                f"Existing compressed context:\n{payload.get('existing_summary', '')}\n\n"
                "Create a compact context package for subsequent execution."
            ),
            max_tokens=768,
            temperature=0.1,
        )
        if parsed is None:
            completed_steps = str(payload.get("completed_steps", "")).strip()
            route_notes = str(payload.get("route_notes", "")).strip()
            result = {
                "compressed_context": _truncate(f"{route_notes}\n{completed_steps}", limit=1200),
                "salient_facts": [],
                "open_questions": [],
                "raw": _truncate(raw, limit=180),
            }
        else:
            result = {
                "compressed_context": str(parsed.get("compressed_context", "")).strip(),
                "salient_facts": [
                    str(item).strip()
                    for item in parsed.get("salient_facts", [])
                    if str(item).strip()
                ],
                "open_questions": [
                    str(item).strip()
                    for item in parsed.get("open_questions", [])
                    if str(item).strip()
                ],
                "raw": _truncate(raw, limit=180),
            }
        return ProcessResult(
            payload={**result, "usage": usage},
            summary=_truncate(result["compressed_context"] or "Compressed execution context", limit=140),
            usage=usage,
        )


class ArchivistHarnessAgent:
    agent_type = "archivist"

    def run(
        self,
        *,
        kernel: "AgentKernel",
        process: AgentProcess,
        payload: dict[str, Any],
    ) -> ProcessResult:
        if Capability.WRITE_MEMORY.value not in process.capabilities:
            raise PermissionError("Archivist missing write_memory capability")

        summary = str(payload.get("summary", "")).strip()
        content = str(payload.get("content", "")).strip()
        tags = [str(tag) for tag in payload.get("tags", []) if str(tag).strip()]
        source_task_id = str(payload.get("source_task_id", process.task_id)).strip()
        kind = str(payload.get("kind", "task")).strip() or "task"

        kernel.task_store.create_memory(
            kind=kind,
            summary=summary,
            content=content,
            tags=tags,
            source_task_id=source_task_id,
        )
        return ProcessResult(
            payload={"stored": True, "summary": summary, "tags": tags},
            summary=f"Archived memory '{summary or source_task_id}'",
        )


class UnitManager:
    def __init__(self, kernel: "AgentKernel") -> None:
        self._kernel = kernel
        self._auto_activating_tasks: set[str] = set()
        self._templates: dict[str, UnitTemplate] = {
            "router.service": UnitTemplate(
                template_name="router.service",
                agent_type="router",
                default_priority=PriorityClass.REALTIME.value,
                timeout_seconds=45,
                before_templates=("retriever.service", "planner.service"),
                description="Route the root task request into an execution path.",
            ),
            "retriever.service": UnitTemplate(
                template_name="retriever.service",
                agent_type="retriever",
                default_priority=PriorityClass.HIGH.value,
                timeout_seconds=90,
                after_templates=("router.service",),
                before_templates=("planner.service",),
                description="Load relevant session and archive memory before planning.",
            ),
            "planner.service": UnitTemplate(
                template_name="planner.service",
                agent_type="planner",
                default_priority=PriorityClass.HIGH.value,
                timeout_seconds=120,
                after_templates=("router.service", "retriever.service"),
                before_templates=("executor.service", "compressor.service", "archivist.service"),
                description="Produce the task plan and phase graph.",
            ),
            "executor.service": UnitTemplate(
                template_name="executor.service",
                agent_type="executor",
                default_priority=PriorityClass.NORMAL.value,
                restart_policy=RestartPolicy.ON_FAILURE.value,
                max_restart_attempts=1,
                timeout_seconds=600,
                after_templates=("planner.service",),
                before_templates=("critic.service", "verifier.service"),
                on_failure_templates=("compressor.service",),
                description="Execute a concrete task step through tools and syscalls.",
            ),
            "critic.service": UnitTemplate(
                template_name="critic.service",
                agent_type="critic",
                default_priority=PriorityClass.HIGH.value,
                timeout_seconds=90,
                after_templates=("executor.service",),
                before_templates=("verifier.service",),
                description="Adversarially review an executor attempt.",
            ),
            "verifier.service": UnitTemplate(
                template_name="verifier.service",
                agent_type="verifier",
                default_priority=PriorityClass.HIGH.value,
                timeout_seconds=90,
                after_templates=("executor.service",),
                description="Verify a candidate step result.",
            ),
            "compressor.service": UnitTemplate(
                template_name="compressor.service",
                agent_type="compressor",
                default_priority=PriorityClass.BACKGROUND.value,
                timeout_seconds=60,
                after_templates=("planner.service",),
                description="Compress long-running task context.",
            ),
            "archivist.service": UnitTemplate(
                template_name="archivist.service",
                agent_type="archivist",
                default_priority=PriorityClass.BACKGROUND.value,
                timeout_seconds=60,
                after_templates=("planner.service",),
                description="Persist durable memory after task completion.",
            ),
        }

    def template_for(self, template_name: str) -> UnitTemplate:
        template = self._templates.get(template_name)
        if template is None:
            raise KeyError(f"Unknown unit template: {template_name}")
        return template

    def list_templates(self) -> list[str]:
        return sorted(self._templates)

    def _activation_request_metadata(
        self,
        *,
        payload: dict[str, Any],
        priority: str | None,
        parent_process_id: str,
        capabilities: set[str] | None,
        namespace: AgentNamespace | None,
        quota: ResourceQuota | None,
        dependencies: list[str],
        step_index: int,
        parent_unit_name: str,
        auto_activate: bool,
    ) -> dict[str, Any]:
        return {
            "auto_activate": auto_activate,
            "activation_request": {
                "payload": _json_ready(payload),
                "priority": priority,
                "parent_process_id": parent_process_id,
                "capabilities": sorted(capabilities or []),
                "namespace": _json_ready(namespace) if namespace is not None else None,
                "quota": _json_ready(quota) if quota is not None else None,
                "dependencies": list(dependencies),
                "step_index": step_index,
                "parent_unit_name": parent_unit_name,
            },
        }

    def _activation_request_for_unit(self, unit: TaskUnitRecord) -> dict[str, Any] | None:
        request = unit.metadata.get("activation_request")
        if isinstance(request, dict):
            return dict(request)
        return None

    def _target_allows_member_activation(self, unit: TaskUnitRecord) -> bool:
        owner_target_name = str(unit.metadata.get("owner_target_name", "")).strip()
        if not owner_target_name:
            return True
        owner_target = self._kernel.task_store.find_target(unit.task_id, owner_target_name)
        if owner_target is None:
            return False
        return owner_target.state == TargetState.ACTIVATING.value

    def _dependencies_satisfied(self, task_id: str, dependencies: list[str]) -> bool:
        try:
            self._ensure_dependencies_satisfied(task_id, dependencies)
        except RuntimeError:
            return False
        return True

    def _can_auto_activate_unit(self, unit: TaskUnitRecord) -> bool:
        if unit.state not in {UnitState.INACTIVE.value, UnitState.WAITING.value}:
            return False
        if not bool(unit.metadata.get("auto_activate", False)):
            return False
        if self._activation_request_for_unit(unit) is None:
            return False
        if not self._target_allows_member_activation(unit):
            return False
        return self._dependencies_satisfied(unit.task_id, unit.dependencies)

    def queue_unit(
        self,
        *,
        task_id: str,
        unit_name: str,
        template_name: str,
        payload: dict[str, Any],
        priority: str | None,
        parent_process_id: str,
        namespace: AgentNamespace | None,
        quota: ResourceQuota | None,
        capabilities: set[str] | None,
        dependencies: list[str] | None = None,
        step_index: int = 0,
        parent_unit_name: str = "",
        metadata: dict[str, Any] | None = None,
        auto_activate: bool = True,
    ) -> TaskUnitRecord:
        dependency_list = [str(item) for item in (dependencies or []) if str(item).strip()]
        activation_metadata = self._activation_request_metadata(
            payload=payload,
            priority=priority,
            parent_process_id=parent_process_id,
            capabilities=capabilities,
            namespace=namespace,
            quota=quota,
            dependencies=dependency_list,
            step_index=step_index,
            parent_unit_name=parent_unit_name,
            auto_activate=auto_activate,
        )
        queued = self.ensure_unit(
            task_id=task_id,
            unit_name=unit_name,
            template_name=template_name,
            step_index=step_index,
            parent_unit_name=parent_unit_name,
            dependencies=dependency_list,
            metadata={**(metadata or {}), **activation_metadata},
            state=UnitState.WAITING.value,
            summary=f"queued {template_name} for dependency-aware activation",
        )
        if auto_activate and self._can_auto_activate_unit(queued):
            activated, _process, _result = self.activate_registered_unit(
                task_id=task_id,
                unit_name=unit_name,
                requested_by_process_id=parent_process_id,
            )
            return activated
        return queued

    def activate_registered_unit(
        self,
        *,
        task_id: str,
        unit_name: str,
        requested_by_process_id: str,
    ) -> tuple[TaskUnitRecord, AgentProcess, ProcessResult]:
        unit = self._kernel.task_store.get_unit(task_id, unit_name)
        request = self._activation_request_for_unit(unit)
        if request is None:
            raise RuntimeError(f"unit {unit_name} has no activation request")
        namespace_payload = request.get("namespace")
        quota_payload = request.get("quota")
        namespace = (
            self._kernel._namespace_from_record(namespace_payload, task_id)
            if isinstance(namespace_payload, dict)
            else None
        )
        quota = (
            self._kernel._quota_from_record(quota_payload)
            if isinstance(quota_payload, dict)
            else None
        )
        capabilities_payload = request.get("capabilities")
        capabilities = (
            {str(item) for item in capabilities_payload}
            if isinstance(capabilities_payload, list)
            else None
        )
        return self.run_unit(
            task_id=task_id,
            unit_name=unit_name,
            template_name=unit.template_name,
            payload=dict(request.get("payload", {})),
            priority=str(request.get("priority", "")).strip() or None,
            parent_process_id=(
                str(request.get("parent_process_id", "")).strip()
                or requested_by_process_id
            ),
            namespace=namespace,
            quota=quota,
            capabilities=capabilities,
            dependencies=[
                str(item)
                for item in request.get("dependencies", unit.dependencies)
                if str(item).strip()
            ],
            step_index=int(request.get("step_index", unit.step_index or 0) or 0),
            parent_unit_name=(
                str(request.get("parent_unit_name", "")).strip()
                or unit.parent_unit_name
            ),
            metadata=unit.metadata,
        )

    def activate_ready_units(
        self,
        *,
        task_id: str,
        requested_by_process_id: str,
    ) -> list[str]:
        if task_id in self._auto_activating_tasks:
            return []
        self._auto_activating_tasks.add(task_id)
        activated: list[str] = []
        try:
            made_progress = True
            safety_counter = 0
            while made_progress and safety_counter < 32:
                safety_counter += 1
                made_progress = False
                for unit in self._kernel.task_store.list_units(task_id, limit=500):
                    if not self._can_auto_activate_unit(unit):
                        continue
                    self.activate_registered_unit(
                        task_id=task_id,
                        unit_name=unit.unit_name,
                        requested_by_process_id=requested_by_process_id,
                    )
                    activated.append(unit.unit_name)
                    made_progress = True
            return activated
        finally:
            self._auto_activating_tasks.discard(task_id)

    def _template_matches_scope(
        self,
        unit: TaskUnitRecord,
        *,
        step_index: int,
        parent_unit_name: str,
    ) -> bool:
        if step_index and unit.step_index not in {0, step_index}:
            return False
        if parent_unit_name and unit.parent_unit_name and unit.parent_unit_name != parent_unit_name:
            return False
        return True

    def _resolve_template_unit_names(
        self,
        *,
        task_id: str,
        template_names: tuple[str, ...],
        step_index: int,
        parent_unit_name: str,
    ) -> list[str]:
        if not template_names:
            return []
        resolved: list[str] = []
        units = self._kernel.task_store.list_units(task_id, limit=500)
        for template_name in template_names:
            for unit in units:
                if unit.template_name != template_name:
                    continue
                if not self._template_matches_scope(
                    unit,
                    step_index=step_index,
                    parent_unit_name=parent_unit_name,
                ):
                    continue
                if unit.unit_name not in resolved:
                    resolved.append(unit.unit_name)
        return resolved

    def _resolve_before_dependencies(
        self,
        *,
        task_id: str,
        template_name: str,
        step_index: int,
        parent_unit_name: str,
    ) -> list[str]:
        resolved: list[str] = []
        units = self._kernel.task_store.list_units(task_id, limit=500)
        for unit in units:
            template = self._templates.get(unit.template_name)
            if template is None:
                continue
            if template_name not in template.before_templates:
                continue
            if not self._template_matches_scope(
                unit,
                step_index=step_index,
                parent_unit_name=parent_unit_name,
            ):
                continue
            if unit.unit_name not in resolved:
                resolved.append(unit.unit_name)
        return resolved

    def _default_failure_followup_unit_name(
        self,
        failed_unit: TaskUnitRecord,
        template_name: str,
    ) -> str:
        stem = template_name.replace(".service", "")
        source_name = failed_unit.unit_name
        if source_name.endswith(".service"):
            source_name = source_name[: -len(".service")]
        if failed_unit.step_index:
            return f"{stem}@failure-step-{failed_unit.step_index}.service"
        return f"{stem}@failure-of-{self._kernel.task_store._safe_component(source_name)}.service"

    def _default_success_followup_unit_name(
        self,
        completed_unit: TaskUnitRecord,
        template_name: str,
    ) -> str:
        stem = template_name.replace(".service", "")
        source_name = completed_unit.unit_name
        if source_name.endswith(".service"):
            source_name = source_name[: -len(".service")]
        if completed_unit.step_index:
            return f"{stem}@success-step-{completed_unit.step_index}.service"
        return f"{stem}@success-of-{self._kernel.task_store._safe_component(source_name)}.service"

    def _build_failure_followup_payload(
        self,
        *,
        template_name: str,
        failed_unit: TaskUnitRecord,
    ) -> dict[str, Any]:
        task = self._kernel.task_store.get_task(failed_unit.task_id)
        events = self._kernel.task_store.list_events(failed_unit.task_id, limit=12)
        checkpoints = self._kernel.task_store.list_checkpoints(failed_unit.task_id, limit=12)
        if template_name == "compressor.service":
            completed_steps = [
                f"- Step {step.step_index} {step.title}: {step.result}"
                for step in task.steps
                if step.status == "completed" and step.result
            ]
            recent_events = [
                f"- {event.created_at} {event.kind}: {event.message}"
                for event in reversed(events[-8:])
            ]
            recent_checkpoints = [
                f"- {checkpoint.process_id} {checkpoint.phase}: {checkpoint.summary}"
                for checkpoint in reversed(checkpoints[-8:])
            ]
            return {
                "task_goal": task.goal,
                "route_notes": "Triggered by unit OnFailure handler.",
                "completed_steps": "\n".join(completed_steps) or "None",
                "memories": "\n".join(recent_events + recent_checkpoints) or "None",
                "existing_summary": (
                    f"Failed unit: {failed_unit.unit_name}\n"
                    f"Summary: {failed_unit.summary}\n"
                    f"State: {failed_unit.state}\n"
                    f"Restart attempts: {failed_unit.restart_attempts}/{failed_unit.max_restart_attempts}"
                ),
            }
        return {
            "failed_unit": failed_unit.unit_name,
            "summary": failed_unit.summary,
            "task_goal": task.goal,
        }

    def _build_success_followup_payload(
        self,
        *,
        template_name: str,
        completed_unit: TaskUnitRecord,
        result: ProcessResult,
    ) -> dict[str, Any]:
        task = self._kernel.task_store.get_task(completed_unit.task_id)
        return {
            "completed_unit": completed_unit.unit_name,
            "summary": result.summary,
            "result": _json_ready(result.payload),
            "task_goal": task.goal,
            "task_title": task.title,
        }

    def _run_on_failure_followups(
        self,
        failed_unit: TaskUnitRecord,
        *,
        requested_by_process_id: str,
    ) -> None:
        if not failed_unit.on_failure_units or failed_unit.metadata.get("on_failure_followups_ran"):
            return
        failed_unit = self.ensure_unit(
            task_id=failed_unit.task_id,
            unit_name=failed_unit.unit_name,
            template_name=failed_unit.template_name,
            step_index=failed_unit.step_index,
            parent_unit_name=failed_unit.parent_unit_name,
            dependencies=failed_unit.dependencies,
            metadata={**failed_unit.metadata, "on_failure_followups_ran": True},
            state=failed_unit.state,
            summary=failed_unit.summary,
            process_id=failed_unit.process_id,
            restart_attempts=failed_unit.restart_attempts,
        )
        for template_name in failed_unit.on_failure_units:
            try:
                template = self.template_for(template_name)
            except KeyError:
                continue
            payload = self._build_failure_followup_payload(
                template_name=template_name,
                failed_unit=failed_unit,
            )
            try:
                followup_name = self._default_failure_followup_unit_name(failed_unit, template_name)
                followup_unit = self.queue_unit(
                    task_id=failed_unit.task_id,
                    unit_name=followup_name,
                    template_name=template_name,
                    payload=payload,
                    priority=template.default_priority,
                    parent_process_id=requested_by_process_id,
                    capabilities=None,
                    namespace=AgentNamespace(
                        task_namespace=failed_unit.task_id,
                        repo_namespace=["/workspace/repo", "/skills"],
                        memory_namespace=["/memory/session", "/memory/archive"],
                        tool_allowlist=[],
                        identity=template.agent_type,
                        network_access=False,
                        mounts=dict(self._kernel.config.agentos.vfs_mounts),
                    ),
                    quota=None,
                    step_index=failed_unit.step_index,
                    parent_unit_name=failed_unit.unit_name,
                    dependencies=[],
                    metadata={"trigger": "on_failure", "failed_unit": failed_unit.unit_name},
                    auto_activate=True,
                )
                self._kernel.emit_event(
                    task_id=failed_unit.task_id,
                    kind="unit.on_failure.queued",
                    level="warning",
                    message=f"queued on-failure unit {followup_name}",
                    payload={
                        "template_name": template_name,
                        "failed_unit": failed_unit.unit_name,
                        "process_id": followup_unit.process_id,
                    },
                    process_id=followup_unit.process_id,
                    parent_process_id=requested_by_process_id,
                )
            except Exception as exc:
                self._kernel.emit_event(
                    task_id=failed_unit.task_id,
                    kind="unit.on_failure.failed",
                    level="error",
                    message=f"on-failure unit {template_name} failed for {failed_unit.unit_name}",
                    payload={"error": str(exc)},
                    process_id=requested_by_process_id,
                )

    def _run_on_success_followups(
        self,
        completed_unit: TaskUnitRecord,
        *,
        result: ProcessResult,
        requested_by_process_id: str,
    ) -> None:
        if not completed_unit.on_success_units or completed_unit.metadata.get("on_success_followups_ran"):
            return
        completed_unit = self.ensure_unit(
            task_id=completed_unit.task_id,
            unit_name=completed_unit.unit_name,
            template_name=completed_unit.template_name,
            step_index=completed_unit.step_index,
            parent_unit_name=completed_unit.parent_unit_name,
            dependencies=completed_unit.dependencies,
            metadata={**completed_unit.metadata, "on_success_followups_ran": True},
            state=completed_unit.state,
            summary=completed_unit.summary,
            process_id=completed_unit.process_id,
            restart_attempts=completed_unit.restart_attempts,
        )
        for template_name in completed_unit.on_success_units:
            try:
                template = self.template_for(template_name)
            except KeyError:
                continue
            payload = self._build_success_followup_payload(
                template_name=template_name,
                completed_unit=completed_unit,
                result=result,
            )
            try:
                followup_name = self._default_success_followup_unit_name(
                    completed_unit,
                    template_name,
                )
                followup_unit = self.queue_unit(
                    task_id=completed_unit.task_id,
                    unit_name=followup_name,
                    template_name=template_name,
                    payload=payload,
                    priority=template.default_priority,
                    parent_process_id=requested_by_process_id,
                    capabilities=None,
                    namespace=AgentNamespace(
                        task_namespace=completed_unit.task_id,
                        repo_namespace=["/workspace/repo", "/skills"],
                        memory_namespace=["/memory/session", "/memory/archive"],
                        tool_allowlist=[],
                        identity=template.agent_type,
                        network_access=False,
                        mounts=dict(self._kernel.config.agentos.vfs_mounts),
                    ),
                    quota=None,
                    step_index=completed_unit.step_index,
                    parent_unit_name=completed_unit.unit_name,
                    dependencies=[completed_unit.unit_name],
                    metadata={"trigger": "on_success", "completed_unit": completed_unit.unit_name},
                    auto_activate=True,
                )
                self._kernel.emit_event(
                    task_id=completed_unit.task_id,
                    kind="unit.on_success.queued",
                    level="info",
                    message=f"queued on-success unit {followup_name}",
                    payload={
                        "template_name": template_name,
                        "completed_unit": completed_unit.unit_name,
                        "process_id": followup_unit.process_id,
                    },
                    process_id=followup_unit.process_id,
                    parent_process_id=requested_by_process_id,
                )
            except Exception as exc:
                self._kernel.emit_event(
                    task_id=completed_unit.task_id,
                    kind="unit.on_success.failed",
                    level="error",
                    message=f"on-success unit {template_name} failed for {completed_unit.unit_name}",
                    payload={"error": str(exc)},
                    process_id=requested_by_process_id,
                )

    def ensure_unit(
        self,
        *,
        task_id: str,
        unit_name: str,
        template_name: str,
        step_index: int = 0,
        parent_unit_name: str = "",
        dependencies: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        state: str | None = None,
        summary: str | None = None,
        process_id: str | None = None,
        restart_attempts: int | None = None,
    ) -> TaskUnitRecord:
        dependencies = [str(item) for item in (dependencies or []) if str(item).strip()]
        template = self.template_for(template_name)
        existing = self._kernel.task_store.find_unit(task_id, unit_name)
        template_after = self._resolve_template_unit_names(
            task_id=task_id,
            template_names=template.after_templates,
            step_index=step_index if step_index else (existing.step_index if existing else 0),
            parent_unit_name=parent_unit_name or (existing.parent_unit_name if existing else ""),
        )
        template_before_dependencies = self._resolve_before_dependencies(
            task_id=task_id,
            template_name=template_name,
            step_index=step_index if step_index else (existing.step_index if existing else 0),
            parent_unit_name=parent_unit_name or (existing.parent_unit_name if existing else ""),
        )
        merged_dependencies: list[str] = []
        for candidate in [
            *dependencies,
            *template_after,
            *template_before_dependencies,
            *(existing.dependencies if existing else []),
        ]:
            candidate = str(candidate).strip()
            if candidate and candidate not in merged_dependencies and candidate != unit_name:
                merged_dependencies.append(candidate)
        created_at = existing.created_at if existing is not None else _utcnow()
        updated_at = _utcnow()
        record = TaskUnitRecord(
            unit_id=existing.unit_id if existing is not None else uuid.uuid4().hex[:12],
            task_id=task_id,
            unit_name=unit_name,
            template_name=template_name,
            agent_type=template.agent_type,
            step_index=step_index if step_index else (existing.step_index if existing else 0),
            parent_unit_name=parent_unit_name or (existing.parent_unit_name if existing else ""),
            dependencies=merged_dependencies,
            after_units=template_after or (existing.after_units if existing else []),
            before_units=list(template.before_templates) or (existing.before_units if existing else []),
            on_failure_units=list(template.on_failure_templates) or (existing.on_failure_units if existing else []),
            on_success_units=list(template.on_success_templates) or (existing.on_success_units if existing else []),
            restart_policy=template.restart_policy,
            restart_attempts=(
                existing.restart_attempts
                if restart_attempts is None and existing is not None
                else int(restart_attempts or 0)
            ),
            max_restart_attempts=template.max_restart_attempts,
            timeout_seconds=template.timeout_seconds,
            process_id=process_id if process_id is not None else (existing.process_id if existing else ""),
            state=state or (existing.state if existing else UnitState.INACTIVE.value),
            summary=summary if summary is not None else (existing.summary if existing else ""),
            metadata={
                **(existing.metadata if existing is not None else {}),
                **(metadata or {}),
                "description": template.description,
                "timeout_seconds": template.timeout_seconds,
            },
            created_at=created_at,
            updated_at=updated_at,
        )
        self._kernel.task_store.upsert_unit(
            unit_id=record.unit_id,
            task_id=record.task_id,
            unit_name=record.unit_name,
            template_name=record.template_name,
            agent_type=record.agent_type,
            step_index=record.step_index,
            parent_unit_name=record.parent_unit_name,
            dependencies=record.dependencies,
            after_units=record.after_units,
            before_units=record.before_units,
            on_failure_units=record.on_failure_units,
            on_success_units=record.on_success_units,
            restart_policy=record.restart_policy,
            restart_attempts=record.restart_attempts,
            max_restart_attempts=record.max_restart_attempts,
            timeout_seconds=record.timeout_seconds,
            process_id=record.process_id,
            state=record.state,
            summary=record.summary,
            metadata=record.metadata,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        persisted = self._kernel.task_store.get_unit(task_id, unit_name)
        if existing is None:
            self._kernel.emit_event(
                task_id=task_id,
                kind="unit.register",
                level="info",
                message=f"registered unit {unit_name}",
                payload={
                    "template_name": template_name,
                    "dependencies": persisted.dependencies,
                    "step_index": persisted.step_index,
                },
                process_id=persisted.process_id,
            )
        elif existing.state != persisted.state or existing.process_id != persisted.process_id:
            self._kernel.emit_event(
                task_id=task_id,
                kind="unit.state",
                level="info",
                message=f"unit {unit_name} -> {persisted.state}",
                payload={
                    "previous_state": existing.state,
                    "process_id": persisted.process_id,
                    "summary": persisted.summary,
                    "restart_attempts": persisted.restart_attempts,
                },
                process_id=persisted.process_id,
            )
        return persisted

    def _ensure_dependencies_satisfied(self, task_id: str, dependencies: list[str]) -> None:
        unmet: list[str] = []
        for dependency_name in dependencies:
            dependency = self._kernel.task_store.find_unit(task_id, dependency_name)
            if dependency is None:
                unmet.append(f"{dependency_name}:missing")
                continue
            if dependency.state != UnitState.COMPLETED.value:
                unmet.append(f"{dependency_name}:{dependency.state}")
        if unmet:
            raise RuntimeError("unit dependencies not satisfied: " + ", ".join(unmet))

    def _result_for_process(self, process_id: str) -> ProcessResult:
        process = self._kernel._load_process_runtime(process_id)
        return self._kernel._result_for_runtime(process)

    def _unit_elapsed_seconds(self, unit: TaskUnitRecord) -> float:
        activated_at = str(unit.metadata.get("activated_at", "")).strip()
        if not activated_at:
            activated_at = unit.updated_at
        return _elapsed_seconds_since(activated_at)

    def _timeout_summary(self, unit: TaskUnitRecord) -> str:
        elapsed = self._unit_elapsed_seconds(unit)
        return (
            f"unit {unit.unit_name} timed out after {elapsed:.1f}s "
            f"(limit {unit.timeout_seconds}s)"
        )

    def _finalize_failed_unit(
        self,
        unit: TaskUnitRecord,
        *,
        summary: str,
        process_id: str,
        requested_by_process_id: str,
        trigger_followups: bool = False,
    ) -> TaskUnitRecord:
        failed = self.ensure_unit(
            task_id=unit.task_id,
            unit_name=unit.unit_name,
            template_name=unit.template_name,
            step_index=unit.step_index,
            parent_unit_name=unit.parent_unit_name,
            dependencies=unit.dependencies,
            metadata=unit.metadata,
            state=UnitState.FAILED.value,
            summary=summary,
            process_id=process_id,
            restart_attempts=unit.restart_attempts,
        )
        if trigger_followups:
            self._run_on_failure_followups(
                failed,
                requested_by_process_id=requested_by_process_id,
            )
        return failed

    def _latest_restart_process_id(self, unit: TaskUnitRecord) -> str:
        original_parent = ""
        try:
            original_parent = self._kernel.task_store.get_process(unit.process_id).parent_process_id
        except Exception:
            original_parent = ""
        for process in reversed(self._kernel.task_store.list_processes(unit.task_id, limit=500)):
            if process.agent_type != unit.agent_type:
                continue
            if original_parent and process.parent_process_id != original_parent:
                continue
            return process.process_id
        return unit.process_id

    def _restart_failed_unit(
        self,
        unit: TaskUnitRecord,
        *,
        priority_override: str,
        requested_by_process_id: str,
    ) -> tuple[TaskUnitRecord, AgentProcess, ProcessResult]:
        if unit.restart_policy != RestartPolicy.ON_FAILURE.value:
            self._run_on_failure_followups(
                unit,
                requested_by_process_id=requested_by_process_id,
            )
            raise RuntimeError(unit.summary or f"unit {unit.unit_name} failed")
        if unit.restart_attempts >= unit.max_restart_attempts:
            self._run_on_failure_followups(
                unit,
                requested_by_process_id=requested_by_process_id,
            )
            raise RuntimeError(
                unit.summary
                or f"unit {unit.unit_name} exhausted restart budget "
                f"({unit.restart_attempts}/{unit.max_restart_attempts})"
            )

        next_attempts = unit.restart_attempts + 1
        restarting = self.ensure_unit(
            task_id=unit.task_id,
            unit_name=unit.unit_name,
            template_name=unit.template_name,
            step_index=unit.step_index,
            parent_unit_name=unit.parent_unit_name,
            dependencies=unit.dependencies,
            metadata={**unit.metadata, "activated_at": _utcnow()},
            state=UnitState.ACTIVATING.value,
            summary=f"restarting unit after failure ({next_attempts}/{unit.max_restart_attempts})",
            process_id=unit.process_id,
            restart_attempts=next_attempts,
        )
        self._kernel.emit_event(
            task_id=unit.task_id,
            kind="unit.restart",
            level="warning",
            message=f"restarting unit {unit.unit_name}",
            payload={
                "restart_attempts": next_attempts,
                "max_restart_attempts": unit.max_restart_attempts,
            },
            process_id=unit.process_id,
            parent_process_id=requested_by_process_id,
        )
        try:
            restored_process, _checkpoint, result = self._kernel.restore_checkpoint(
                process_id=unit.process_id,
                run_immediately=True,
                priority_override=priority_override or None,
                requested_by_process_id=requested_by_process_id,
            )
        except Exception as exc:
            latest_process_id = self._latest_restart_process_id(unit)
            failed = self.ensure_unit(
                task_id=unit.task_id,
                unit_name=unit.unit_name,
                template_name=unit.template_name,
                step_index=unit.step_index,
                parent_unit_name=unit.parent_unit_name,
                dependencies=unit.dependencies,
                metadata=unit.metadata,
                state=UnitState.FAILED.value,
                summary=str(exc),
                process_id=latest_process_id,
                restart_attempts=next_attempts,
            )
            self._run_on_failure_followups(
                failed,
                requested_by_process_id=requested_by_process_id,
            )
            raise
        state = (
            UnitState.COMPLETED.value
            if restored_process.state == ProcessState.COMPLETED.value
            else UnitState.WAITING.value
            if restored_process.state == ProcessState.WAITING.value
            else UnitState.FAILED.value
        )
        summary = result.summary if result is not None else restarting.summary
        updated = self.ensure_unit(
            task_id=unit.task_id,
            unit_name=unit.unit_name,
            template_name=unit.template_name,
            step_index=unit.step_index,
            parent_unit_name=unit.parent_unit_name,
            dependencies=unit.dependencies,
            metadata=unit.metadata,
            state=state,
            summary=summary,
            process_id=restored_process.process_id,
            restart_attempts=next_attempts,
        )
        self._post_unit_transition(
            updated,
            result=result,
            requested_by_process_id=requested_by_process_id or restored_process.process_id,
        )
        return updated, restored_process, result

    def _post_unit_completion(
        self,
        unit: TaskUnitRecord,
        *,
        result: ProcessResult,
        requested_by_process_id: str,
    ) -> None:
        self._run_on_success_followups(
            unit,
            result=result,
            requested_by_process_id=requested_by_process_id,
        )
        self.activate_ready_units(
            task_id=unit.task_id,
            requested_by_process_id=requested_by_process_id,
        )
        target_manager = getattr(self._kernel, "target_manager", None)
        if target_manager is not None:
            target_manager.reconcile_task(
                task_id=unit.task_id,
                requested_by_process_id=requested_by_process_id,
            )

    def _post_unit_transition(
        self,
        unit: TaskUnitRecord,
        *,
        result: ProcessResult | None,
        requested_by_process_id: str,
    ) -> None:
        if unit.state == UnitState.COMPLETED.value and result is not None:
            self._post_unit_completion(
                unit,
                result=result,
                requested_by_process_id=requested_by_process_id,
            )
            return
        target_manager = getattr(self._kernel, "target_manager", None)
        if target_manager is not None:
            target_manager.reconcile_task(
                task_id=unit.task_id,
                requested_by_process_id=requested_by_process_id,
            )

    def run_unit(
        self,
        *,
        task_id: str,
        unit_name: str,
        template_name: str,
        payload: dict[str, Any],
        priority: str | None,
        parent_process_id: str,
        namespace: AgentNamespace | None,
        quota: ResourceQuota | None,
        capabilities: set[str] | None,
        dependencies: list[str] | None = None,
        step_index: int = 0,
        parent_unit_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[TaskUnitRecord, AgentProcess, ProcessResult]:
        template = self.template_for(template_name)
        unit_priority = priority or template.default_priority
        dependency_list = [str(item) for item in (dependencies or []) if str(item).strip()]
        base_metadata = {
            **(metadata or {}),
            **self._activation_request_metadata(
                payload=payload,
                priority=unit_priority,
                parent_process_id=parent_process_id,
                capabilities=capabilities,
                namespace=namespace,
                quota=quota,
                dependencies=dependency_list,
                step_index=step_index,
                parent_unit_name=parent_unit_name,
                auto_activate=bool((metadata or {}).get("auto_activate", True)),
            ),
        }
        unit = self.ensure_unit(
            task_id=task_id,
            unit_name=unit_name,
            template_name=template_name,
            step_index=step_index,
            parent_unit_name=parent_unit_name,
            dependencies=dependency_list,
            metadata=base_metadata,
        )
        try:
            self._ensure_dependencies_satisfied(task_id, unit.dependencies)
        except RuntimeError as exc:
            self.ensure_unit(
                task_id=task_id,
                unit_name=unit_name,
                template_name=template_name,
                step_index=unit.step_index,
                parent_unit_name=unit.parent_unit_name,
                dependencies=unit.dependencies,
                metadata=unit.metadata,
                state=UnitState.WAITING.value,
                summary=str(exc),
                process_id=unit.process_id,
                restart_attempts=unit.restart_attempts,
            )
            raise

        existing_process: AgentProcess | None = None
        if unit.process_id:
            try:
                existing_process = self._kernel._load_process_runtime(unit.process_id)
            except Exception:
                existing_process = None

        if existing_process is not None:
            if existing_process.state == ProcessState.COMPLETED.value:
                completed_result = self._result_for_process(existing_process.process_id)
                completed = self.ensure_unit(
                    task_id=task_id,
                    unit_name=unit_name,
                    template_name=template_name,
                    step_index=unit.step_index,
                    parent_unit_name=unit.parent_unit_name,
                    dependencies=unit.dependencies,
                    metadata=unit.metadata,
                    state=UnitState.COMPLETED.value,
                    summary=completed_result.summary,
                    process_id=existing_process.process_id,
                    restart_attempts=unit.restart_attempts,
                )
                self._post_unit_transition(
                    completed,
                    result=completed_result,
                    requested_by_process_id=parent_process_id or existing_process.process_id,
                )
                return completed, existing_process, completed_result
            if unit.timeout_seconds > 0 and unit.state in {
                UnitState.ACTIVATING.value,
                UnitState.WAITING.value,
            }:
                elapsed = self._unit_elapsed_seconds(unit)
                if elapsed > unit.timeout_seconds:
                    timed_out = self._finalize_failed_unit(
                        unit,
                        summary=self._timeout_summary(unit),
                        process_id=existing_process.process_id,
                        requested_by_process_id=parent_process_id or existing_process.process_id,
                    )
                    self._kernel.emit_event(
                        task_id=task_id,
                        kind="unit.timeout",
                        level="error",
                        message=f"unit {unit.unit_name} timed out",
                        payload={
                            "elapsed_seconds": round(elapsed, 2),
                            "timeout_seconds": unit.timeout_seconds,
                        },
                        process_id=existing_process.process_id,
                    )
                    return self._restart_failed_unit(
                        timed_out,
                        priority_override=unit_priority,
                        requested_by_process_id=parent_process_id or existing_process.process_id,
                    )
            if existing_process.state == ProcessState.WAITING.value:
                waiting_result = self._result_for_process(existing_process.process_id)
                waiting = self.ensure_unit(
                    task_id=task_id,
                    unit_name=unit_name,
                    template_name=template_name,
                    step_index=unit.step_index,
                    parent_unit_name=unit.parent_unit_name,
                    dependencies=unit.dependencies,
                    metadata=unit.metadata,
                    state=UnitState.WAITING.value,
                    summary=waiting_result.summary,
                    process_id=existing_process.process_id,
                    restart_attempts=unit.restart_attempts,
                )
                self._post_unit_transition(
                    waiting,
                    result=waiting_result,
                    requested_by_process_id=parent_process_id or existing_process.process_id,
                )
                return waiting, existing_process, waiting_result
            if existing_process.state == ProcessState.READY.value:
                running = self.ensure_unit(
                    task_id=task_id,
                    unit_name=unit_name,
                    template_name=template_name,
                    step_index=unit.step_index,
                    parent_unit_name=unit.parent_unit_name,
                    dependencies=unit.dependencies,
                    metadata=unit.metadata,
                    state=UnitState.ACTIVATING.value,
                    summary="resuming queued unit process",
                    process_id=existing_process.process_id,
                    restart_attempts=unit.restart_attempts,
                )
                try:
                    result = self._kernel.run_scheduled_process(existing_process.process_id)
                except Exception as exc:
                    failed = self.ensure_unit(
                        task_id=task_id,
                        unit_name=unit_name,
                        template_name=template_name,
                        step_index=running.step_index,
                        parent_unit_name=running.parent_unit_name,
                        dependencies=running.dependencies,
                        metadata=running.metadata,
                        state=UnitState.FAILED.value,
                        summary=str(exc),
                        process_id=existing_process.process_id,
                        restart_attempts=running.restart_attempts,
                    )
                    return self._restart_failed_unit(
                        failed,
                        priority_override=unit_priority,
                        requested_by_process_id=parent_process_id or existing_process.process_id,
                    )
                final_state = (
                    UnitState.COMPLETED.value
                    if existing_process.state == ProcessState.COMPLETED.value
                    else UnitState.WAITING.value
                    if existing_process.state == ProcessState.WAITING.value
                    else UnitState.FAILED.value
                )
                updated = self.ensure_unit(
                    task_id=task_id,
                    unit_name=unit_name,
                    template_name=template_name,
                    step_index=unit.step_index,
                    parent_unit_name=unit.parent_unit_name,
                    dependencies=unit.dependencies,
                    metadata=unit.metadata,
                    state=final_state,
                    summary=result.summary,
                    process_id=existing_process.process_id,
                    restart_attempts=running.restart_attempts,
                )
                self._post_unit_transition(
                    updated,
                    result=result,
                    requested_by_process_id=parent_process_id or existing_process.process_id,
                )
                return updated, existing_process, result
            if existing_process.state == ProcessState.FAILED.value:
                return self._restart_failed_unit(
                    unit,
                    priority_override=unit_priority,
                    requested_by_process_id=parent_process_id,
                )

        starting = self.ensure_unit(
            task_id=task_id,
            unit_name=unit_name,
            template_name=template_name,
            step_index=step_index,
            parent_unit_name=parent_unit_name,
            dependencies=dependency_list,
            metadata={
                **base_metadata,
                "activated_at": _utcnow(),
            },
            state=UnitState.ACTIVATING.value,
            summary=f"starting {template_name}",
            restart_attempts=unit.restart_attempts,
        )
        process = self._kernel.spawn_process(
            task_id=task_id,
            agent_type=template.agent_type,
            payload=payload,
            priority=unit_priority,
            parent_process_id=parent_process_id,
            capabilities=capabilities,
            namespace=namespace,
            quota=quota,
        )
        bound = self.ensure_unit(
            task_id=task_id,
            unit_name=unit_name,
            template_name=template_name,
            step_index=step_index,
            parent_unit_name=parent_unit_name,
            dependencies=dependency_list,
            metadata={
                **base_metadata,
                "priority": unit_priority,
                "activated_at": str(starting.metadata.get("activated_at", _utcnow())),
            },
            state=UnitState.ACTIVATING.value,
            summary=starting.summary,
            process_id=process.process_id,
            restart_attempts=starting.restart_attempts,
        )
        try:
            result = self._kernel.run_scheduled_process(process.process_id)
        except Exception as exc:
            failed = self._finalize_failed_unit(
                bound,
                summary=str(exc),
                process_id=process.process_id,
                requested_by_process_id=parent_process_id or process.process_id,
            )
            return self._restart_failed_unit(
                failed,
                priority_override=unit_priority,
                requested_by_process_id=parent_process_id or process.process_id,
            )
        elapsed_seconds = self._unit_elapsed_seconds(bound)
        exceeded_timeout = (
            bound.timeout_seconds > 0 and elapsed_seconds > bound.timeout_seconds
        )
        if exceeded_timeout and process.state != ProcessState.COMPLETED.value:
            self._kernel.emit_event(
                task_id=task_id,
                kind="unit.timeout",
                level="error",
                message=f"unit {unit_name} timed out",
                payload={
                    "elapsed_seconds": round(elapsed_seconds, 2),
                    "timeout_seconds": bound.timeout_seconds,
                },
                process_id=process.process_id,
                parent_process_id=parent_process_id,
            )
            failed = self._finalize_failed_unit(
                bound,
                summary=self._timeout_summary(bound),
                process_id=process.process_id,
                requested_by_process_id=parent_process_id or process.process_id,
            )
            return self._restart_failed_unit(
                failed,
                priority_override=unit_priority,
                requested_by_process_id=parent_process_id or process.process_id,
            )
        final_state = (
            UnitState.COMPLETED.value
            if process.state == ProcessState.COMPLETED.value
            else UnitState.WAITING.value
            if process.state == ProcessState.WAITING.value
            else UnitState.FAILED.value
        )
        updated = self.ensure_unit(
            task_id=task_id,
            unit_name=unit_name,
            template_name=template_name,
            step_index=bound.step_index,
            parent_unit_name=bound.parent_unit_name,
            dependencies=bound.dependencies,
            metadata=bound.metadata,
            state=final_state,
            summary=result.summary,
            process_id=process.process_id,
            restart_attempts=bound.restart_attempts,
        )
        if exceeded_timeout and process.state == ProcessState.COMPLETED.value:
            self._kernel.emit_event(
                task_id=task_id,
                kind="unit.slow",
                level="warning",
                message=f"unit {unit_name} exceeded timeout but completed successfully",
                payload={
                    "elapsed_seconds": round(elapsed_seconds, 2),
                    "timeout_seconds": bound.timeout_seconds,
                },
                process_id=process.process_id,
                parent_process_id=parent_process_id,
            )
        self._post_unit_transition(
            updated,
            result=result,
            requested_by_process_id=parent_process_id or process.process_id,
        )
        return updated, process, result


class TargetManager:
    def __init__(self, kernel: "AgentKernel") -> None:
        self._kernel = kernel
        self._reconciling_tasks: set[str] = set()
        self._templates: dict[str, TargetTemplate] = {
            "planning.target": TargetTemplate(
                template_name="planning.target",
                description="Orchestrate router, retriever, and planner units.",
            ),
            "step.target": TargetTemplate(
                template_name="step.target",
                default_dependencies=("planning.target",),
                description="Orchestrate a single executor/critic/verifier step attempt.",
            ),
            "completion.target": TargetTemplate(
                template_name="completion.target",
                default_dependencies=("planning.target",),
                description="Orchestrate archival and task completion flows.",
            ),
            "task.target": TargetTemplate(
                template_name="task.target",
                description="Aggregate planning, step, and completion targets into one DAG root.",
            ),
        }

    def template_for(self, template_name: str) -> TargetTemplate:
        template = self._templates.get(template_name)
        if template is None:
            raise KeyError(f"Unknown target template: {template_name}")
        return template

    def list_templates(self) -> list[str]:
        return sorted(self._templates)

    def ensure_target(
        self,
        *,
        task_id: str,
        target_name: str,
        template_name: str,
        dependencies: list[str] | None = None,
        wanted_units: list[str] | None = None,
        wanted_targets: list[str] | None = None,
        on_success_targets: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        state: str | None = None,
        summary: str | None = None,
    ) -> TaskTargetRecord:
        template = self.template_for(template_name)
        existing = self._kernel.task_store.find_target(task_id, target_name)
        merged_dependencies: list[str] = []
        for candidate in [
            *(dependencies or []),
            *template.default_dependencies,
            *(existing.dependencies if existing is not None else []),
        ]:
            name = str(candidate).strip()
            if name and name not in merged_dependencies and name != target_name:
                merged_dependencies.append(name)
        merged_units: list[str] = []
        for candidate in [
            *(wanted_units or []),
            *(existing.wanted_units if existing is not None else []),
        ]:
            name = str(candidate).strip()
            if name and name not in merged_units:
                merged_units.append(name)
        merged_targets: list[str] = []
        for candidate in [
            *(wanted_targets or []),
            *(existing.wanted_targets if existing is not None else []),
        ]:
            name = str(candidate).strip()
            if name and name not in merged_targets and name != target_name:
                merged_targets.append(name)
        merged_successors: list[str] = []
        for candidate in [
            *(on_success_targets or []),
            *template.on_success_targets,
            *(existing.on_success_targets if existing is not None else []),
        ]:
            name = str(candidate).strip()
            if name and name not in merged_successors and name != target_name:
                merged_successors.append(name)
        created_at = existing.created_at if existing is not None else _utcnow()
        updated_at = _utcnow()
        record = TaskTargetRecord(
            target_id=existing.target_id if existing is not None else uuid.uuid4().hex[:12],
            task_id=task_id,
            target_name=target_name,
            template_name=template_name,
            dependencies=merged_dependencies,
            wanted_units=merged_units,
            wanted_targets=merged_targets,
            on_success_targets=merged_successors,
            state=state or (existing.state if existing is not None else TargetState.INACTIVE.value),
            summary=summary if summary is not None else (existing.summary if existing is not None else ""),
            metadata={
                **(existing.metadata if existing is not None else {}),
                **(metadata or {}),
                "description": template.description,
            },
            created_at=created_at,
            updated_at=updated_at,
        )
        self._kernel.task_store.upsert_target(
            target_id=record.target_id,
            task_id=record.task_id,
            target_name=record.target_name,
            template_name=record.template_name,
            dependencies=record.dependencies,
            wanted_units=record.wanted_units,
            wanted_targets=record.wanted_targets,
            on_success_targets=record.on_success_targets,
            state=record.state,
            summary=record.summary,
            metadata=record.metadata,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        persisted = self._kernel.task_store.get_target(task_id, target_name)
        if existing is None:
            self._kernel.emit_event(
                task_id=task_id,
                kind="target.register",
                level="info",
                message=f"registered target {target_name}",
                payload={
                    "template_name": template_name,
                    "dependencies": persisted.dependencies,
                    "wanted_units": persisted.wanted_units,
                    "wanted_targets": persisted.wanted_targets,
                },
            )
        elif existing.state != persisted.state or existing.summary != persisted.summary:
            self._kernel.emit_event(
                task_id=task_id,
                kind="target.state",
                level="info",
                message=f"target {target_name} -> {persisted.state}",
                payload={
                    "previous_state": existing.state,
                    "summary": persisted.summary,
                },
            )
        return persisted

    def _target_dependencies_satisfied(self, target: TaskTargetRecord) -> tuple[bool, list[str]]:
        unmet: list[str] = []
        for dependency_name in target.dependencies:
            dependency = self._kernel.task_store.find_target(target.task_id, dependency_name)
            if dependency is None:
                unmet.append(f"{dependency_name}:missing")
                continue
            if dependency.state != TargetState.COMPLETED.value:
                unmet.append(f"{dependency_name}:{dependency.state}")
        return (not unmet, unmet)

    def _run_on_success_targets(
        self,
        target: TaskTargetRecord,
        *,
        requested_by_process_id: str,
    ) -> None:
        if not target.on_success_targets or target.metadata.get("on_success_targets_ran"):
            return
        target = self.ensure_target(
            task_id=target.task_id,
            target_name=target.target_name,
            template_name=target.template_name,
            dependencies=target.dependencies,
            wanted_units=target.wanted_units,
            wanted_targets=target.wanted_targets,
            on_success_targets=target.on_success_targets,
            metadata={**target.metadata, "on_success_targets_ran": True},
            state=target.state,
            summary=target.summary,
        )
        for successor_name in target.on_success_targets:
            successor = self._kernel.task_store.find_target(target.task_id, successor_name)
            if successor is None:
                continue
            self.ensure_target(
                task_id=successor.task_id,
                target_name=successor.target_name,
                template_name=successor.template_name,
                dependencies=successor.dependencies,
                wanted_units=successor.wanted_units,
                wanted_targets=successor.wanted_targets,
                on_success_targets=successor.on_success_targets,
                metadata={**successor.metadata, "auto_activate": True},
                state=TargetState.ACTIVATING.value,
                summary=f"activated by OnSuccess of {target.target_name}",
            )
            self._kernel.emit_event(
                task_id=successor.task_id,
                kind="target.on_success.queued",
                level="info",
                message=f"queued successor target {successor.target_name}",
                payload={"from_target": target.target_name},
                process_id=requested_by_process_id,
            )

    def _reconcile_single_target(
        self,
        target: TaskTargetRecord,
        *,
        requested_by_process_id: str,
    ) -> TaskTargetRecord:
        if target.state == TargetState.COMPLETED.value:
            return target
        if target.state == TargetState.FAILED.value:
            return target
        if target.state == TargetState.INACTIVE.value and not bool(
            target.metadata.get("auto_activate", False)
        ):
            return target
        deps_satisfied, unmet_dependencies = self._target_dependencies_satisfied(target)
        if not deps_satisfied:
            return self.ensure_target(
                task_id=target.task_id,
                target_name=target.target_name,
                template_name=target.template_name,
                dependencies=target.dependencies,
                wanted_units=target.wanted_units,
                wanted_targets=target.wanted_targets,
                on_success_targets=target.on_success_targets,
                metadata=target.metadata,
                state=TargetState.WAITING.value,
                summary="target dependencies not satisfied: " + ", ".join(unmet_dependencies),
            )

        # Promote this target into an activating state and wake child targets that are ready.
        target = self.ensure_target(
            task_id=target.task_id,
            target_name=target.target_name,
            template_name=target.template_name,
            dependencies=target.dependencies,
            wanted_units=target.wanted_units,
            wanted_targets=target.wanted_targets,
            on_success_targets=target.on_success_targets,
            metadata={**target.metadata, "auto_activate": True},
            state=TargetState.ACTIVATING.value,
            summary=target.summary or f"activating {target.target_name}",
        )

        for child_target_name in target.wanted_targets:
            child_target = self._kernel.task_store.find_target(target.task_id, child_target_name)
            if child_target is None:
                continue
            child_deps_satisfied, _ = self._target_dependencies_satisfied(child_target)
            if (
                child_deps_satisfied
                and child_target.state in {TargetState.INACTIVE.value, TargetState.WAITING.value}
                and bool(child_target.metadata.get("auto_activate", False))
            ):
                self.ensure_target(
                    task_id=child_target.task_id,
                    target_name=child_target.target_name,
                    template_name=child_target.template_name,
                    dependencies=child_target.dependencies,
                    wanted_units=child_target.wanted_units,
                    wanted_targets=child_target.wanted_targets,
                    on_success_targets=child_target.on_success_targets,
                    metadata=child_target.metadata,
                    state=TargetState.ACTIVATING.value,
                    summary=f"auto-activating target {child_target.target_name}",
                )

        self._kernel.unit_manager.activate_ready_units(
            task_id=target.task_id,
            requested_by_process_id=requested_by_process_id,
        )

        failed_members: list[str] = []
        pending_members: list[str] = []
        for child_target_name in target.wanted_targets:
            child_target = self._kernel.task_store.find_target(target.task_id, child_target_name)
            if child_target is None:
                pending_members.append(f"{child_target_name}:missing")
                continue
            if child_target.state == TargetState.FAILED.value:
                failed_members.append(f"{child_target_name}:failed")
            elif child_target.state != TargetState.COMPLETED.value:
                pending_members.append(f"{child_target_name}:{child_target.state}")
        for unit_name in target.wanted_units:
            unit = self._kernel.task_store.find_unit(target.task_id, unit_name)
            if unit is None:
                pending_members.append(f"{unit_name}:missing")
                continue
            if unit.state == UnitState.FAILED.value:
                failed_members.append(f"{unit_name}:failed")
            elif unit.state != UnitState.COMPLETED.value:
                pending_members.append(f"{unit_name}:{unit.state}")

        if failed_members:
            return self.ensure_target(
                task_id=target.task_id,
                target_name=target.target_name,
                template_name=target.template_name,
                dependencies=target.dependencies,
                wanted_units=target.wanted_units,
                wanted_targets=target.wanted_targets,
                on_success_targets=target.on_success_targets,
                metadata=target.metadata,
                state=TargetState.FAILED.value,
                summary="target members failed: " + ", ".join(failed_members),
            )

        if not pending_members:
            completed = self.ensure_target(
                task_id=target.task_id,
                target_name=target.target_name,
                template_name=target.template_name,
                dependencies=target.dependencies,
                wanted_units=target.wanted_units,
                wanted_targets=target.wanted_targets,
                on_success_targets=target.on_success_targets,
                metadata=target.metadata,
                state=TargetState.COMPLETED.value,
                summary=f"completed target {target.target_name}",
            )
            self._run_on_success_targets(
                completed,
                requested_by_process_id=requested_by_process_id,
            )
            return completed

        return self.ensure_target(
            task_id=target.task_id,
            target_name=target.target_name,
            template_name=target.template_name,
            dependencies=target.dependencies,
            wanted_units=target.wanted_units,
            wanted_targets=target.wanted_targets,
            on_success_targets=target.on_success_targets,
            metadata=target.metadata,
            state=TargetState.ACTIVATING.value,
            summary="pending members: " + ", ".join(pending_members),
        )

    def activate_target(
        self,
        *,
        task_id: str,
        target_name: str,
        template_name: str,
        dependencies: list[str] | None = None,
        wanted_units: list[str] | None = None,
        wanted_targets: list[str] | None = None,
        unit_specs: list[UnitRunSpec] | None = None,
        metadata: dict[str, Any] | None = None,
        on_success_targets: list[str] | None = None,
        requested_by_process_id: str = "",
    ) -> TaskTargetRecord:
        queued_unit_names = [spec.unit_name for spec in (unit_specs or [])]
        initial_dependencies = [
            str(item).strip()
            for item in [*(dependencies or []), *self.template_for(template_name).default_dependencies]
            if str(item).strip()
        ]
        deps_satisfied = all(
            (
                dependency is not None
                and dependency.state == TargetState.COMPLETED.value
            )
            for dependency in (
                self._kernel.task_store.find_target(task_id, dependency_name)
                for dependency_name in initial_dependencies
            )
        )
        target = self.ensure_target(
            task_id=task_id,
            target_name=target_name,
            template_name=template_name,
            dependencies=dependencies,
            wanted_units=[*(wanted_units or []), *queued_unit_names],
            wanted_targets=wanted_targets,
            on_success_targets=on_success_targets,
            metadata={**(metadata or {}), "auto_activate": True},
            state=TargetState.ACTIVATING.value if deps_satisfied else TargetState.WAITING.value,
            summary=(
                f"activating target {target_name}"
                if deps_satisfied
                else f"waiting on target dependencies for {target_name}"
            ),
        )
        for spec in unit_specs or []:
            self._kernel.unit_manager.queue_unit(
                task_id=task_id,
                unit_name=spec.unit_name,
                template_name=spec.template_name,
                payload=spec.payload,
                priority=spec.priority,
                parent_process_id=spec.parent_process_id or requested_by_process_id,
                namespace=spec.namespace,
                quota=spec.quota,
                capabilities=spec.capabilities,
                dependencies=spec.dependencies,
                step_index=spec.step_index,
                parent_unit_name=spec.parent_unit_name,
                metadata={
                    **(spec.metadata or {}),
                    "owner_target_name": target_name,
                    "auto_activate": spec.auto_activate,
                },
                auto_activate=spec.auto_activate,
            )
        self.reconcile_task(
            task_id=task_id,
            requested_by_process_id=requested_by_process_id,
        )
        return self._kernel.task_store.get_target(task_id, target_name)

    def reconcile_task(
        self,
        *,
        task_id: str,
        requested_by_process_id: str,
    ) -> None:
        if task_id in self._reconciling_tasks:
            return
        self._reconciling_tasks.add(task_id)
        try:
            changed = True
            safety_counter = 0
            while changed and safety_counter < 32:
                safety_counter += 1
                changed = False
                for target in self._kernel.task_store.list_targets(task_id, limit=500):
                    updated = self._reconcile_single_target(
                        target,
                        requested_by_process_id=requested_by_process_id,
                    )
                    if (
                        updated.state != target.state
                        or updated.summary != target.summary
                        or updated.wanted_units != target.wanted_units
                        or updated.wanted_targets != target.wanted_targets
                    ):
                        changed = True
        finally:
            self._reconciling_tasks.discard(task_id)


class KernelSession:
    def __init__(
        self,
        *,
        kernel: "AgentKernel",
        task_id: str,
        root_request: str,
        attachments: list[dict[str, str]],
    ) -> None:
        self._kernel = kernel
        self.task_id = task_id
        self.root_request = root_request
        self.attachments = attachments
        self._kernel.emit_event(
            task_id=task_id,
            kind="session.open",
            level="info",
            message="agentd opened task session",
            payload={
                "attachments": attachments,
                "request_preview": _truncate(root_request, 200),
            },
        )

    @property
    def mounts(self) -> dict[str, str]:
        return dict(self._kernel.config.agentos.vfs_mounts)

    def emit_event(
        self,
        *,
        kind: str,
        level: str,
        message: str,
        payload: dict[str, Any] | None = None,
        process_id: str = "",
        parent_process_id: str = "",
    ) -> None:
        self._kernel.emit_event(
            task_id=self.task_id,
            kind=kind,
            level=level,
            message=message,
            payload=payload,
            process_id=process_id,
            parent_process_id=parent_process_id,
        )

    def build_namespace(
        self,
        *,
        identity: str,
        tool_allowlist: list[str] | None = None,
        repo_namespace: list[str] | None = None,
        memory_namespace: list[str] | None = None,
        network_access: bool = False,
    ) -> AgentNamespace:
        return AgentNamespace(
            task_namespace=self.task_id,
            repo_namespace=repo_namespace or ["/workspace/repo", "/skills"],
            memory_namespace=memory_namespace or ["/memory/session", "/memory/archive"],
            tool_allowlist=tool_allowlist or [],
            identity=identity,
            network_access=network_access,
            mounts=dict(self._kernel.config.agentos.vfs_mounts),
        )

    def build_quota(
        self,
        *,
        token_budget: int | None = None,
        tool_call_budget: int | None = None,
        child_agent_budget: int | None = None,
        retry_budget: int | None = None,
    ) -> ResourceQuota:
        return ResourceQuota(
            token_budget=token_budget or self._kernel.config.agentos.default_token_budget,
            tool_call_budget=tool_call_budget
            if tool_call_budget is not None
            else self._kernel.config.agentos.default_tool_call_budget,
            child_agent_budget=child_agent_budget
            if child_agent_budget is not None
            else self._kernel.config.agentos.default_child_agent_budget,
            retry_budget=retry_budget
            if retry_budget is not None
            else self._kernel.config.agentos.default_retry_budget,
        )

    def run_unit(
        self,
        *,
        unit_name: str,
        template_name: str,
        payload: dict[str, Any],
        priority: str | None = None,
        parent_process_id: str = "",
        capabilities: set[str] | None = None,
        namespace: AgentNamespace | None = None,
        quota: ResourceQuota | None = None,
        dependencies: list[str] | None = None,
        step_index: int = 0,
        parent_unit_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[TaskUnitRecord, AgentProcess, ProcessResult]:
        return self._kernel.unit_manager.run_unit(
            task_id=self.task_id,
            unit_name=unit_name,
            template_name=template_name,
            payload=payload,
            priority=priority,
            parent_process_id=parent_process_id,
            capabilities=capabilities,
            namespace=namespace,
            quota=quota,
            dependencies=dependencies,
            step_index=step_index,
            parent_unit_name=parent_unit_name,
            metadata=metadata,
        )

    def activate_target(
        self,
        *,
        target_name: str,
        template_name: str,
        dependencies: list[str] | None = None,
        wanted_units: list[str] | None = None,
        wanted_targets: list[str] | None = None,
        unit_specs: list[UnitRunSpec] | None = None,
        metadata: dict[str, Any] | None = None,
        on_success_targets: list[str] | None = None,
        requested_by_process_id: str = "",
    ) -> TaskTargetRecord:
        return self._kernel.target_manager.activate_target(
            task_id=self.task_id,
            target_name=target_name,
            template_name=template_name,
            dependencies=dependencies,
            wanted_units=wanted_units,
            wanted_targets=wanted_targets,
            unit_specs=unit_specs,
            metadata=metadata,
            on_success_targets=on_success_targets,
            requested_by_process_id=requested_by_process_id,
        )

    def get_unit(self, unit_name: str) -> TaskUnitRecord:
        return self._kernel.task_store.get_unit(self.task_id, unit_name)

    def find_unit(self, unit_name: str) -> TaskUnitRecord | None:
        return self._kernel.task_store.find_unit(self.task_id, unit_name)

    def get_target(self, target_name: str) -> TaskTargetRecord:
        return self._kernel.task_store.get_target(self.task_id, target_name)

    def find_target(self, target_name: str) -> TaskTargetRecord | None:
        return self._kernel.task_store.find_target(self.task_id, target_name)

    def result_for_unit(self, unit_name: str) -> ProcessResult | None:
        unit = self.find_unit(unit_name)
        if unit is None or not unit.process_id:
            return None
        return self._kernel.result_for_process(unit.process_id)

    def run(
        self,
        *,
        agent_type: str,
        payload: dict[str, Any],
        priority: str = PriorityClass.NORMAL.value,
        parent_process_id: str = "",
        capabilities: set[str] | None = None,
        namespace: AgentNamespace | None = None,
        quota: ResourceQuota | None = None,
    ) -> tuple[AgentProcess, ProcessResult]:
        process = self._kernel.spawn_process(
            task_id=self.task_id,
            agent_type=agent_type,
            payload=payload,
            priority=priority,
            parent_process_id=parent_process_id,
            capabilities=capabilities,
            namespace=namespace,
            quota=quota,
        )
        result = self._kernel.run_scheduled_process(process.process_id)
        return process, result

    def dispatch_process(self, process_id: str) -> ProcessResult:
        return self._kernel.run_process(process_id)

    def pump_scheduler(self, *, limit: int = 32) -> dict[str, Any]:
        return self._kernel.pump_scheduler(
            task_id=self.task_id,
            limit=limit,
            requested_by_process_id="",
        )

    def restore_checkpoint(
        self,
        *,
        checkpoint_id: str | None = None,
        process_id: str | None = None,
        run_immediately: bool = True,
        priority_override: str | None = None,
    ) -> tuple[AgentProcess, TaskCheckpointRecord, ProcessResult | None]:
        return self._kernel.restore_checkpoint(
            checkpoint_id=checkpoint_id,
            process_id=process_id,
            run_immediately=run_immediately,
            priority_override=priority_override,
        )


class AgentKernel:
    def __init__(
        self,
        config: AppConfig,
        *,
        task_store: TaskStore,
        client: OpenAICompatibleModelClient,
        planner: TaskPlanner,
        base_tools: ToolRegistry,
        renderer: ConsoleRenderer,
    ) -> None:
        self.config = config
        self.task_store = task_store
        self.client = client
        self.planner = planner
        self.base_tools = base_tools
        self.renderer = renderer
        self.scheduler = AgentScheduler()
        self._processes: dict[str, AgentProcess] = {}
        self._scheduler_draining = False
        self.syscall_broker = SyscallBroker(
            base_registry=base_tools,
            task_store=task_store,
            renderer=renderer,
            spawn_process=self.spawn_process,
            run_process=self.run_process,
            pump_scheduler=self.pump_scheduler,
            restore_checkpoint=self.restore_checkpoint,
            list_agent_types=self.list_agent_types,
            notify_ipc_delivery=self.wake_ipc_waiters,
            persist_process=self.persist_process,
            emit_event=self.emit_event,
        )
        self.unit_manager = UnitManager(self)
        self.target_manager = TargetManager(self)
        self._agents: dict[str, HarnessAgent] = {
            "router": RouterHarnessAgent(),
            "retriever": RetrieverHarnessAgent(),
            "planner": PlannerHarnessAgent(),
            "executor": ExecutorHarnessAgent(),
            "critic": CriticHarnessAgent(),
            "verifier": VerifierHarnessAgent(),
            "compressor": CompressorHarnessAgent(),
            "archivist": ArchivistHarnessAgent(),
        }

    def create_session(
        self,
        *,
        task_id: str,
        root_request: str,
        attachments: list[dict[str, str]],
    ) -> KernelSession:
        return KernelSession(
            kernel=self,
            task_id=task_id,
            root_request=root_request,
            attachments=attachments,
        )

    def default_capabilities_for(self, agent_type: str) -> set[str]:
        defaults = {
            "router": {Capability.ROUTE_TASK.value},
            "retriever": {Capability.RETRIEVE_MEMORY.value},
            "planner": {Capability.PLAN_TASK.value},
            "executor": {
                Capability.USE_TOOLS.value,
                Capability.WEB_ACCESS.value,
                Capability.SPAWN_CHILD.value,
                Capability.JOIN_PROCESS.value,
                Capability.AWAIT_IPC.value,
                Capability.PUMP_SCHEDULER.value,
                Capability.USE_IPC.value,
                Capability.RESTORE_CHECKPOINT.value,
            },
            "critic": {Capability.CRITIQUE_OUTPUT.value},
            "verifier": {Capability.VERIFY_OUTPUT.value},
            "compressor": {Capability.COMPRESS_CONTEXT.value},
            "archivist": {Capability.WRITE_MEMORY.value},
        }
        return set(defaults.get(agent_type, set()))

    def list_agent_types(self) -> list[str]:
        return sorted(self._agents)

    def list_unit_templates(self) -> list[str]:
        return self.unit_manager.list_templates()

    def list_target_templates(self) -> list[str]:
        return self.target_manager.list_templates()

    def result_for_process(self, process_id: str) -> ProcessResult:
        process = self._load_process_runtime(process_id)
        return self._result_for_runtime(process)

    def _scheduler_weight_for_process(self, process: AgentProcess) -> int:
        base_weight = AgentScheduler._WEIGHTS.get(
            process.priority,
            AgentScheduler._WEIGHTS[PriorityClass.NORMAL.value],
        )
        unit = self.task_store.find_unit_by_process(process.task_id, process.process_id)
        if unit is None:
            return base_weight

        weight = base_weight
        if unit.restart_attempts > 0:
            weight -= 1

        if unit.timeout_seconds > 0:
            activated_at = str(unit.metadata.get("activated_at", "")).strip()
            if activated_at:
                elapsed = _elapsed_seconds_since(activated_at)
                ratio = elapsed / max(1, unit.timeout_seconds)
                if ratio >= 0.8:
                    weight -= 1

        blocked_dependents = sum(
            1
            for candidate in self.task_store.list_units(process.task_id, limit=500)
            if unit.unit_name in candidate.dependencies and candidate.state == UnitState.WAITING.value
        )
        if blocked_dependents > 0:
            weight -= 1

        return max(0, weight)

    def persist_process(self, process: AgentProcess) -> None:
        self._processes[process.process_id] = process
        self.task_store.upsert_process(
            process_id=process.process_id,
            task_id=process.task_id,
            parent_process_id=process.parent_process_id,
            agent_type=process.agent_type,
            priority=process.priority,
            state=process.state,
            wait_kind=process.wait_kind,
            wait_target=process.wait_target,
            wait_payload=_json_ready(process.wait_payload),
            capabilities=sorted(process.capabilities),
            namespace=_json_ready(process.namespace),
            quota=_json_ready(process.quota),
            input_preview=_preview_payload(process.input_payload),
            output_preview=_preview_payload(process.output_payload),
            last_error=process.last_error,
            created_at=process.created_at,
            updated_at=process.updated_at,
        )

    def wake_ipc_waiters(
        self,
        *,
        task_id: str,
        recipient_process_id: str,
        channel: str,
        message_id: str,
    ) -> int:
        return self._wake_waiters_for_ipc(
            task_id=task_id,
            recipient_process_id=recipient_process_id,
            channel=channel,
            message_id=message_id,
        )

    def emit_event(
        self,
        *,
        task_id: str,
        kind: str,
        level: str,
        message: str,
        payload: dict[str, Any] | None = None,
        process_id: str = "",
        parent_process_id: str = "",
    ) -> None:
        self.task_store.create_event(
            task_id=task_id,
            process_id=process_id,
            parent_process_id=parent_process_id,
            kind=kind,
            level=level,
            message=message,
            payload=_json_ready(payload or {}),
        )
        self.renderer.on_kernel_event(message)

    def create_checkpoint(
        self,
        *,
        process: AgentProcess,
        phase: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        enriched_payload = dict(payload or {})
        enriched_payload.setdefault(
            "process_snapshot",
            {
                "agent_type": process.agent_type,
                "priority": process.priority,
                "wait_kind": process.wait_kind,
                "wait_target": process.wait_target,
                "wait_payload": _json_ready(process.wait_payload),
                "capabilities": sorted(process.capabilities),
                "namespace": _json_ready(process.namespace),
                "quota": _json_ready(process.quota),
                "input_payload": _json_ready(process.input_payload),
                "output_payload": _json_ready(process.output_payload),
                "state": process.state,
            },
        )
        self.task_store.create_checkpoint(
            task_id=process.task_id,
            process_id=process.process_id,
            phase=phase,
            summary=summary,
            payload=_json_ready(enriched_payload),
        )
        self.renderer.on_checkpoint(process.process_id, phase, summary)

    def spawn_process(
        self,
        *,
        task_id: str,
        agent_type: str,
        payload: dict[str, Any],
        priority: str,
        parent_process_id: str,
        capabilities: set[str] | None,
        namespace: AgentNamespace | None,
        quota: ResourceQuota | None,
        count_against_child_budget: bool = True,
    ) -> AgentProcess:
        if agent_type not in self._agents:
            raise KeyError(f"Unknown harness agent type: {agent_type}")

        if parent_process_id:
            parent = self._load_process_runtime(parent_process_id)
            if count_against_child_budget:
                if parent.quota.child_agents_used >= parent.quota.child_agent_budget:
                    raise RuntimeError(
                        f"Parent process {parent_process_id} exhausted child agent quota"
                    )
                parent.quota.child_agents_used += 1
                parent.updated_at = _utcnow()
                self.persist_process(parent)

        process = AgentProcess(
            process_id=uuid.uuid4().hex[:12],
            task_id=task_id,
            parent_process_id=parent_process_id,
            agent_type=agent_type,
            priority=priority,
            state=ProcessState.READY.value,
            wait_kind="",
            wait_target="",
            wait_payload={},
            capabilities=capabilities or self.default_capabilities_for(agent_type),
            namespace=namespace
            or AgentNamespace(
                task_namespace=task_id,
                repo_namespace=["/workspace/repo", "/skills"],
                memory_namespace=["/memory/session", "/memory/archive"],
                tool_allowlist=_default_tool_allowlist(self.base_tools.tool_names),
                identity=agent_type,
                network_access=True,
                mounts=dict(self.config.agentos.vfs_mounts),
            ),
            quota=quota
            or ResourceQuota(
                token_budget=self.config.agentos.default_token_budget,
                tool_call_budget=self.config.agentos.default_tool_call_budget,
                child_agent_budget=self.config.agentos.default_child_agent_budget,
                retry_budget=self.config.agentos.default_retry_budget,
            ),
            input_payload=payload,
        )
        self.persist_process(process)
        self.create_checkpoint(
            process=process,
            phase="spawned",
            summary=f"Spawned {process.agent_type}",
            payload={"input": process.input_payload},
        )
        self.scheduler.enqueue(process, weight_override=self._scheduler_weight_for_process(process))
        self.emit_event(
            task_id=task_id,
            process_id=process.process_id,
            parent_process_id=process.parent_process_id,
            kind="process.spawn",
            level="info",
            message=f"spawned {agent_type} process {process.process_id}",
            payload={
                "priority": priority,
                "count_against_child_budget": count_against_child_budget,
            },
        )
        self.renderer.on_process_spawn(process.process_id, agent_type, priority)
        return process

    def _namespace_from_record(self, namespace: dict[str, Any], task_id: str) -> AgentNamespace:
        mounts = namespace.get("mounts")
        if not isinstance(mounts, dict):
            mounts = dict(self.config.agentos.vfs_mounts)
        return AgentNamespace(
            task_namespace=str(namespace.get("task_namespace", task_id) or task_id),
            repo_namespace=[
                str(item)
                for item in namespace.get("repo_namespace", ["/workspace/repo"])
            ],
            memory_namespace=[
                str(item)
                for item in namespace.get(
                    "memory_namespace",
                    ["/memory/session", "/memory/archive"],
                )
            ],
            tool_allowlist=[
                str(item) for item in namespace.get("tool_allowlist", [])
            ],
            identity=str(namespace.get("identity", "agent")),
            network_access=bool(namespace.get("network_access", False)),
            mounts={str(key): str(value) for key, value in mounts.items()},
        )

    def _quota_from_record(self, quota: dict[str, Any]) -> ResourceQuota:
        return ResourceQuota(
            token_budget=int(
                quota.get("token_budget", self.config.agentos.default_token_budget)
            ),
            tool_call_budget=int(
                quota.get(
                    "tool_call_budget",
                    self.config.agentos.default_tool_call_budget,
                )
            ),
            child_agent_budget=int(
                quota.get(
                    "child_agent_budget",
                    self.config.agentos.default_child_agent_budget,
                )
            ),
            retry_budget=int(
                quota.get("retry_budget", self.config.agentos.default_retry_budget)
            ),
            tool_calls_used=int(quota.get("tool_calls_used", 0)),
            child_agents_used=int(quota.get("child_agents_used", 0)),
        )

    def _input_payload_from_checkpoint(
        self,
        checkpoint: TaskCheckpointRecord | None,
    ) -> dict[str, Any]:
        if checkpoint is None:
            return {}
        payload = checkpoint.payload or {}
        if isinstance(payload.get("input"), dict):
            return dict(payload["input"])
        snapshot = payload.get("process_snapshot", {})
        if isinstance(snapshot, dict) and isinstance(snapshot.get("input_payload"), dict):
            return dict(snapshot["input_payload"])
        return {}

    def _output_payload_from_checkpoint(
        self,
        checkpoint: TaskCheckpointRecord | None,
    ) -> dict[str, Any]:
        if checkpoint is None:
            return {}
        payload = checkpoint.payload or {}
        if isinstance(payload.get("output"), dict):
            return dict(payload["output"])
        snapshot = payload.get("process_snapshot", {})
        if isinstance(snapshot, dict) and isinstance(snapshot.get("output_payload"), dict):
            return dict(snapshot["output_payload"])
        return {}

    def _process_snapshot_from_checkpoint(
        self,
        checkpoint: TaskCheckpointRecord | None,
    ) -> dict[str, Any]:
        if checkpoint is None:
            return {}
        payload = checkpoint.payload or {}
        snapshot = payload.get("process_snapshot", {})
        if isinstance(snapshot, dict):
            return dict(snapshot)
        return {}

    def _process_from_record(
        self,
        record: TaskProcessRecord,
        *,
        checkpoint: TaskCheckpointRecord | None = None,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
    ) -> AgentProcess:
        snapshot = self._process_snapshot_from_checkpoint(checkpoint)
        capabilities = set(record.capabilities)
        namespace = self._namespace_from_record(record.namespace, record.task_id)
        quota = self._quota_from_record(record.quota)
        if isinstance(snapshot.get("capabilities"), list):
            capabilities = {str(item) for item in snapshot.get("capabilities", [])}
        if snapshot.get("namespace") is not None:
            namespace = self._namespace_from_record(
                snapshot.get("namespace", record.namespace),
                record.task_id,
            )
        if snapshot.get("quota") is not None:
            quota = self._quota_from_record(snapshot.get("quota", record.quota))
        runtime = AgentProcess(
            process_id=record.process_id,
            task_id=record.task_id,
            parent_process_id=record.parent_process_id,
            agent_type=record.agent_type,
            priority=record.priority,
            state=record.state,
            wait_kind=record.wait_kind,
            wait_target=record.wait_target,
            wait_payload=dict(record.wait_payload),
            capabilities=capabilities,
            namespace=namespace,
            quota=quota,
            input_payload=input_payload if input_payload is not None else {},
            output_payload=output_payload if output_payload is not None else {},
            last_error=record.last_error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        self._processes[runtime.process_id] = runtime
        return runtime

    def _restorable_checkpoint_for_process(
        self,
        process_id: str,
    ) -> TaskCheckpointRecord | None:
        for phase in ("waiting", "before_execute", "spawned"):
            checkpoint = self.task_store.get_latest_checkpoint_for_process(
                process_id,
                phase=phase,
            )
            if checkpoint is not None:
                return checkpoint
        return None

    def _load_process_runtime(self, process_id: str) -> AgentProcess:
        process = self._processes.get(process_id)
        if process is not None:
            return process

        record = self.task_store.get_process(process_id)
        checkpoint = self.task_store.get_latest_checkpoint_for_process(process_id)
        return self._process_from_record(
            record,
            checkpoint=checkpoint,
            input_payload=self._input_payload_from_checkpoint(checkpoint),
            output_payload=self._output_payload_from_checkpoint(checkpoint),
        )

    def _set_process_waiting(
        self,
        process: AgentProcess,
        *,
        wait_kind: str,
        wait_target: str,
        wait_payload: dict[str, Any],
        detail: str,
    ) -> None:
        process.state = ProcessState.WAITING.value
        process.wait_kind = wait_kind
        process.wait_target = wait_target
        process.wait_payload = dict(wait_payload)
        process.last_error = ""
        process.updated_at = _utcnow()
        self.persist_process(process)
        self.create_checkpoint(
            process=process,
            phase="waiting",
            summary=detail,
            payload={
                "wait_kind": wait_kind,
                "wait_target": wait_target,
                "wait_payload": _json_ready(wait_payload),
            },
        )
        self.emit_event(
            task_id=process.task_id,
            process_id=process.process_id,
            parent_process_id=process.parent_process_id,
            kind="process.wait",
            level="info",
            message=f"waiting {process.agent_type} process {process.process_id}",
            payload={
                "wait_kind": wait_kind,
                "wait_target": wait_target,
                "wait_payload": _json_ready(wait_payload),
            },
        )
        self.renderer.on_process_state(process.process_id, process.state, detail=detail)

    def _wake_process(self, process: AgentProcess, *, detail: str = "") -> bool:
        if process.state != ProcessState.WAITING.value:
            return False
        process.state = ProcessState.READY.value
        process.wait_kind = ""
        process.wait_target = ""
        process.wait_payload = {}
        process.updated_at = _utcnow()
        self.persist_process(process)
        self.scheduler.enqueue(process, weight_override=self._scheduler_weight_for_process(process))
        self.emit_event(
            task_id=process.task_id,
            process_id=process.process_id,
            parent_process_id=process.parent_process_id,
            kind="process.wake",
            level="info",
            message=f"woke {process.agent_type} process {process.process_id}",
            payload={"detail": detail},
        )
        self.renderer.on_process_state(process.process_id, process.state, detail=detail)
        return True

    def _wake_waiters_for_process(self, process: AgentProcess) -> int:
        woke = 0
        for record in self.task_store.list_processes(process.task_id, limit=500):
            if (
                record.state == ProcessState.WAITING.value
                and record.wait_kind == "process"
                and record.wait_target == process.process_id
            ):
                waiter = self._load_process_runtime(record.process_id)
                if self._wake_process(
                    waiter,
                    detail=f"dependency {process.process_id} resolved",
                ):
                    woke += 1
        return woke

    def _wake_waiters_for_ipc(
        self,
        *,
        task_id: str,
        recipient_process_id: str,
        channel: str,
        message_id: str,
    ) -> int:
        woke = 0
        for record in self.task_store.list_processes(task_id, limit=500):
            if record.state != ProcessState.WAITING.value:
                continue
            if record.wait_kind != "ipc":
                continue
            if record.wait_target != recipient_process_id:
                continue
            wait_channel = str(record.wait_payload.get("channel", "")).strip()
            if wait_channel and wait_channel != channel:
                continue
            waiter = self._load_process_runtime(record.process_id)
            if self._wake_process(
                waiter,
                detail=f"ipc {message_id} delivered on {channel or 'default'}",
            ):
                woke += 1
        return woke

    def _result_from_checkpoint(
        self,
        process_id: str,
        *,
        phase: str | None = None,
    ) -> ProcessResult | None:
        checkpoint = self.task_store.get_latest_checkpoint_for_process(
            process_id,
            phase=phase,
        )
        if checkpoint is None:
            return None
        payload = checkpoint.payload.get("output", {})
        if not isinstance(payload, dict):
            payload = {}
        return ProcessResult(payload=dict(payload), summary=checkpoint.summary)

    def _result_for_runtime(self, process: AgentProcess) -> ProcessResult:
        if process.state == ProcessState.COMPLETED.value:
            checkpoint = self._result_from_checkpoint(process.process_id, phase="after_execute")
            if checkpoint is not None:
                return checkpoint
        if process.state == ProcessState.FAILED.value:
            checkpoint = self._result_from_checkpoint(process.process_id, phase="failed")
            if checkpoint is not None:
                return checkpoint
        if process.state == ProcessState.WAITING.value:
            checkpoint = self._result_from_checkpoint(process.process_id, phase="waiting")
            if checkpoint is not None:
                return checkpoint
        return ProcessResult(
            payload={
                "process_id": process.process_id,
                "state": process.state,
                "wait_kind": process.wait_kind,
                "wait_target": process.wait_target,
                "wait_payload": _json_ready(process.wait_payload),
                "last_error": process.last_error,
            },
            summary=process.last_error or process.state,
        )

    def pump_scheduler(
        self,
        *,
        task_id: str | None = None,
        limit: int = 32,
        requested_by_process_id: str = "",
    ) -> dict[str, Any]:
        if self._scheduler_draining:
            return {
                "task_id": task_id,
                "status": "deferred",
                "reason": "scheduler already draining",
                "requested_by_process_id": requested_by_process_id,
                "processed": [],
            }

        self._scheduler_draining = True
        processed: list[dict[str, Any]] = []
        try:
            remaining = max(1, limit)
            while remaining > 0:
                scheduled = self.scheduler.pop(self._processes, task_id=task_id)
                if scheduled is None:
                    break
                result = self._run_process(scheduled)
                processed.append(
                    {
                        "process_id": scheduled.process_id,
                        "agent_type": scheduled.agent_type,
                        "state": scheduled.state,
                        "summary": result.summary,
                    }
                )
                remaining -= 1
            return {
                "task_id": task_id,
                "status": "drained",
                "requested_by_process_id": requested_by_process_id,
                "processed": processed,
                "remaining_ready": sum(
                    1
                    for process in self._processes.values()
                    if process.state == ProcessState.READY.value
                    and (task_id is None or process.task_id == task_id)
                ),
            }
        finally:
            self._scheduler_draining = False

    def _maybe_pump_scheduler(
        self,
        *,
        task_id: str,
        requested_by_process_id: str,
        limit: int = 32,
    ) -> dict[str, Any]:
        if self._scheduler_draining:
            return {
                "task_id": task_id,
                "status": "deferred",
                "reason": "scheduler already draining",
                "requested_by_process_id": requested_by_process_id,
                "processed": [],
            }
        return self.pump_scheduler(
            task_id=task_id,
            limit=limit,
            requested_by_process_id=requested_by_process_id,
        )

    def run_process(self, process_id: str) -> ProcessResult:
        process = self._load_process_runtime(process_id)
        if process.state not in {
            ProcessState.READY.value,
            ProcessState.WAITING.value,
            ProcessState.FAILED.value,
        }:
            raise RuntimeError(
                f"Process {process_id} cannot be run from state {process.state}"
            )
        return self._run_process(process)

    def run_scheduled_process(self, process_id: str) -> ProcessResult:
        scheduled = self._load_process_runtime(process_id)
        if scheduled.state != ProcessState.READY.value:
            raise RuntimeError(f"Process {process_id} is not ready to run")
        return self._run_process(scheduled)

    def restore_checkpoint(
        self,
        *,
        checkpoint_id: str | None = None,
        process_id: str | None = None,
        run_immediately: bool = True,
        priority_override: str | None = None,
        requested_by_process_id: str = "",
    ) -> tuple[AgentProcess, TaskCheckpointRecord, ProcessResult | None]:
        if checkpoint_id:
            checkpoint = self.task_store.get_checkpoint(checkpoint_id)
        elif process_id:
            checkpoint = self._restorable_checkpoint_for_process(process_id)
            if checkpoint is None:
                raise KeyError(f"No executable checkpoint found for process_id: {process_id}")
        else:
            raise ValueError("checkpoint_id or process_id is required")

        record = self.task_store.get_process(checkpoint.process_id)
        input_payload = self._input_payload_from_checkpoint(checkpoint)
        snapshot = checkpoint.payload.get("process_snapshot", {})
        capabilities = set(record.capabilities)
        namespace = self._namespace_from_record(record.namespace, record.task_id)
        quota = self._quota_from_record(record.quota)
        if isinstance(snapshot, dict):
            if isinstance(snapshot.get("capabilities"), list):
                capabilities = {str(item) for item in snapshot.get("capabilities", [])}
            namespace = self._namespace_from_record(
                snapshot.get("namespace", record.namespace),
                record.task_id,
            )
            quota = self._quota_from_record(snapshot.get("quota", record.quota))
        quota.tool_calls_used = 0

        restored_process = self.spawn_process(
            task_id=record.task_id,
            agent_type=record.agent_type,
            payload=input_payload,
            priority=priority_override or record.priority,
            parent_process_id=record.parent_process_id,
            capabilities=capabilities,
            namespace=namespace,
            quota=quota,
            count_against_child_budget=False,
        )
        self.emit_event(
            task_id=record.task_id,
            process_id=restored_process.process_id,
            parent_process_id=record.parent_process_id,
            kind="checkpoint.restore",
            level="warning",
            message=f"restored {record.agent_type} from checkpoint {checkpoint.checkpoint_id}",
            payload={
                "source_process_id": checkpoint.process_id,
                "requested_by_process_id": requested_by_process_id,
            },
        )
        if not run_immediately:
            return restored_process, checkpoint, None
        result = self.run_process(restored_process.process_id)
        return restored_process, checkpoint, result

    def _run_process(self, process: AgentProcess) -> ProcessResult:
        agent = self._agents[process.agent_type]
        process.state = ProcessState.RUNNING.value
        process.wait_kind = ""
        process.wait_target = ""
        process.wait_payload = {}
        process.last_error = ""
        process.updated_at = _utcnow()
        self.persist_process(process)
        self.renderer.on_process_state(process.process_id, process.state)
        self.create_checkpoint(
            process=process,
            phase="before_execute",
            summary=f"Starting {process.agent_type}",
            payload={"input": process.input_payload},
        )
        self.emit_event(
            task_id=process.task_id,
            process_id=process.process_id,
            parent_process_id=process.parent_process_id,
            kind="process.run",
            level="info",
            message=f"running {process.agent_type} process {process.process_id}",
            payload={"priority": process.priority},
        )

        try:
            result = agent.run(kernel=self, process=process, payload=process.input_payload)
        except ProcessBlocked as blocked:
            self._set_process_waiting(
                process,
                wait_kind=blocked.wait_kind,
                wait_target=blocked.wait_target,
                wait_payload=blocked.payload,
                detail=blocked.summary,
            )
            self._maybe_pump_scheduler(task_id=process.task_id, requested_by_process_id=process.process_id)
            if process.state in {
                ProcessState.COMPLETED.value,
                ProcessState.FAILED.value,
            }:
                return self._result_for_runtime(process)
            return ProcessResult(
                payload={
                    "process_id": process.process_id,
                    "state": process.state,
                    "wait_kind": blocked.wait_kind,
                    "wait_target": blocked.wait_target,
                    "wait_payload": _json_ready(blocked.payload),
                    "requeued": process.state == ProcessState.READY.value,
                },
                summary=blocked.summary,
            )
        except Exception as exc:
            process.last_error = str(exc)
            process.state = ProcessState.FAILED.value
            process.wait_kind = ""
            process.wait_target = ""
            process.wait_payload = {}
            process.updated_at = _utcnow()
            self.persist_process(process)
            self.create_checkpoint(
                process=process,
                phase="failed",
                summary=str(exc),
                payload={"error": str(exc)},
            )
            self.emit_event(
                task_id=process.task_id,
                process_id=process.process_id,
                parent_process_id=process.parent_process_id,
                kind="process.failed",
                level="error",
                message=f"failed {process.agent_type} process {process.process_id}",
                payload={"error": str(exc)},
            )
            self.renderer.on_process_state(
                process.process_id,
                process.state,
                detail=str(exc),
            )
            if process.agent_type in {"critic", "verifier"}:
                self.task_store.record_eval_result(
                    task_id=process.task_id,
                    process_id=process.process_id,
                    agent_type=process.agent_type,
                    summary=str(exc),
                    payload={"state": ProcessState.FAILED.value, "error": str(exc)},
                )
            self._wake_waiters_for_process(process)
            self._maybe_pump_scheduler(task_id=process.task_id, requested_by_process_id=process.process_id)
            raise
        else:
            process.output_payload = result.payload
            if result.usage is not None:
                process.quota.token_budget = max(
                    0,
                    process.quota.token_budget - result.usage.total_tokens,
                )
            process.last_error = ""
            process.state = ProcessState.COMPLETED.value
            process.wait_kind = ""
            process.wait_target = ""
            process.wait_payload = {}
            process.updated_at = _utcnow()
            self.persist_process(process)
            self.create_checkpoint(
                process=process,
                phase="after_execute",
                summary=result.summary,
                payload={"output": result.payload},
            )
            self.emit_event(
                task_id=process.task_id,
                process_id=process.process_id,
                parent_process_id=process.parent_process_id,
                kind="process.complete",
                level="info",
                message=f"completed {process.agent_type} process {process.process_id}",
                payload={"summary": result.summary},
            )
            self.renderer.on_process_state(
                process.process_id,
                process.state,
                detail=result.summary,
            )
            if process.agent_type in {"critic", "verifier"}:
                self.task_store.record_eval_result(
                    task_id=process.task_id,
                    process_id=process.process_id,
                    agent_type=process.agent_type,
                    summary=result.summary,
                    payload=_json_ready(result.payload),
                )
            self._wake_waiters_for_process(process)
            self._maybe_pump_scheduler(task_id=process.task_id, requested_by_process_id=process.process_id)
            return result
