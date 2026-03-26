from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig


@dataclass(frozen=True)
class TaskStepRecord:
    step_index: int
    title: str
    description: str
    status: str
    result: str


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    title: str
    goal: str
    user_request: str
    attachments: list[dict[str, str]]
    status: str
    created_at: str
    updated_at: str
    final_summary: str
    steps: list[TaskStepRecord]


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    kind: str
    summary: str
    content: str
    tags: list[str]
    source_task_id: str
    created_at: str


@dataclass(frozen=True)
class TaskProcessRecord:
    process_id: str
    task_id: str
    parent_process_id: str
    agent_type: str
    priority: str
    state: str
    wait_kind: str
    wait_target: str
    wait_payload: dict[str, Any]
    capabilities: list[str]
    namespace: dict[str, Any]
    quota: dict[str, Any]
    input_preview: str
    output_preview: str
    last_error: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TaskEventRecord:
    event_id: str
    task_id: str
    process_id: str
    parent_process_id: str
    kind: str
    level: str
    message: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class TaskCheckpointRecord:
    checkpoint_id: str
    task_id: str
    process_id: str
    phase: str
    summary: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class TaskIpcMessageRecord:
    message_id: str
    task_id: str
    sender_process_id: str
    recipient_process_id: str
    channel: str
    message: str
    payload: dict[str, Any]
    status: str
    created_at: str
    read_at: str


@dataclass(frozen=True)
class TaskUnitRecord:
    unit_id: str
    task_id: str
    unit_name: str
    template_name: str
    agent_type: str
    step_index: int
    parent_unit_name: str
    dependencies: list[str]
    after_units: list[str]
    before_units: list[str]
    on_failure_units: list[str]
    on_success_units: list[str]
    restart_policy: str
    restart_attempts: int
    max_restart_attempts: int
    timeout_seconds: int
    process_id: str
    state: str
    summary: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TaskTargetRecord:
    target_id: str
    task_id: str
    target_name: str
    template_name: str
    dependencies: list[str]
    wanted_units: list[str]
    wanted_targets: list[str]
    on_success_targets: list[str]
    state: str
    summary: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))


class TaskStore:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._db_path = config.state_dir / "agent_state.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_root = self._resolve_mount_root(
            "/memory/session",
            config.state_dir / "session",
        )
        self._archive_root = self._resolve_mount_root(
            "/memory/archive",
            config.state_dir / "archive",
        )
        self._checkpoints_root = self._resolve_mount_root(
            "/checkpoints",
            config.state_dir / "checkpoints",
        )
        self._tools_root = self._resolve_mount_root(
            "/tools/output",
            config.state_dir / "tools",
        )
        self._evals_root = self._resolve_mount_root(
            "/evals",
            config.state_dir / "evals",
        )
        self._units_root = self._session_root
        self._targets_root = self._session_root
        self._init_db()
        self._init_artifact_tree()

    def _resolve_mount_root(self, mount_point: str, fallback: Path) -> Path:
        configured = self._config.agentos.vfs_mounts.get(mount_point)
        if configured:
            return Path(configured).resolve()
        return fallback.resolve()

    def _init_artifact_tree(self) -> None:
        for root in (
            self._session_root,
            self._archive_root,
            self._checkpoints_root,
            self._tools_root,
            self._evals_root,
            self._units_root,
            self._targets_root,
        ):
            root.mkdir(parents=True, exist_ok=True)

    def _safe_component(self, value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
        return normalized.strip("._-") or "item"

    def _task_session_dir(self, task_id: str) -> Path:
        return self._session_root / "tasks" / self._safe_component(task_id)

    def _task_checkpoints_dir(self, task_id: str) -> Path:
        return self._checkpoints_root / "tasks" / self._safe_component(task_id)

    def _task_tools_dir(self, task_id: str) -> Path:
        return self._tools_root / "tasks" / self._safe_component(task_id)

    def _task_evals_dir(self, task_id: str) -> Path:
        return self._evals_root / "tasks" / self._safe_component(task_id)

    def _task_units_dir(self, task_id: str) -> Path:
        return self._units_root / "tasks" / self._safe_component(task_id) / "units"

    def _task_targets_dir(self, task_id: str) -> Path:
        return self._targets_root / "tasks" / self._safe_component(task_id) / "targets"

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _append_jsonl(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")

    def _task_artifact_paths(self, task_id: str) -> dict[str, str]:
        task_dir = self._task_session_dir(task_id)
        return {
            "session_dir": str(task_dir),
            "task_json": str(task_dir / "task.json"),
            "events_jsonl": str(task_dir / "events.jsonl"),
            "ipc_dir": str(task_dir / "ipc"),
            "ipc_jsonl": str(task_dir / "ipc.jsonl"),
            "processes_dir": str(task_dir / "processes"),
            "units_dir": str(self._task_units_dir(task_id)),
            "targets_dir": str(self._task_targets_dir(task_id)),
            "unit_graph_json": str(task_dir / "unit_graph.json"),
            "unit_graph_mermaid": str(task_dir / "unit_graph.mmd"),
            "target_graph_json": str(task_dir / "target_graph.json"),
            "target_graph_mermaid": str(task_dir / "target_graph.mmd"),
            "checkpoints_dir": str(self._task_checkpoints_dir(task_id)),
            "tools_dir": str(self._task_tools_dir(task_id)),
            "evals_dir": str(self._task_evals_dir(task_id)),
            "archive_root": str(self._archive_root),
        }

    def _refresh_task_manifest(self, task_id: str) -> None:
        task_dir = self._task_session_dir(task_id)
        self._write_json(
            task_dir / "manifest.json",
            {
                "task_id": task_id,
                "paths": self._task_artifact_paths(task_id),
                "counts": self.count_task_artifacts(task_id),
            },
        )

    def describe_task_artifacts(self, task_id: str) -> dict[str, str]:
        return dict(self._task_artifact_paths(task_id))

    def count_task_artifacts(self, task_id: str) -> dict[str, int]:
        task_dir = self._task_session_dir(task_id)
        checkpoints_dir = self._task_checkpoints_dir(task_id)
        tools_dir = self._task_tools_dir(task_id)
        evals_dir = self._task_evals_dir(task_id)
        units_dir = self._task_units_dir(task_id)
        targets_dir = self._task_targets_dir(task_id)
        event_log = task_dir / "events.jsonl"
        ipc_log = task_dir / "ipc.jsonl"
        return {
            "task_snapshot": int((task_dir / "task.json").exists()),
            "event_records": self._count_jsonl_lines(event_log),
            "ipc_records": self._count_jsonl_lines(ipc_log),
            "process_files": len(list((task_dir / "processes").glob("*.json")))
            if (task_dir / "processes").exists()
            else 0,
            "unit_files": len(list(units_dir.glob("*.json"))) if units_dir.exists() else 0,
            "unit_graph_files": int((task_dir / "unit_graph.json").exists())
            + int((task_dir / "unit_graph.mmd").exists()),
            "target_files": len(list(targets_dir.glob("*.json"))) if targets_dir.exists() else 0,
            "target_graph_files": int((task_dir / "target_graph.json").exists())
            + int((task_dir / "target_graph.mmd").exists()),
            "checkpoint_files": len(list(checkpoints_dir.glob("*.json")))
            if checkpoints_dir.exists()
            else 0,
            "tool_trace_files": len(list(tools_dir.glob("*.jsonl")))
            if tools_dir.exists()
            else 0,
            "eval_files": len(list(evals_dir.glob("*.json")))
            if evals_dir.exists()
            else 0,
        }

    def _count_jsonl_lines(self, path: Path) -> int:
        if not path.exists():
            return 0
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for _ in handle)

    def _mirror_task_snapshot(self, task_id: str) -> None:
        task = self.get_task(task_id)
        task_dir = self._task_session_dir(task_id)
        payload = {
            "task_id": task.task_id,
            "title": task.title,
            "goal": task.goal,
            "user_request": task.user_request,
            "attachments": task.attachments,
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "final_summary": task.final_summary,
            "steps": [asdict(step) for step in task.steps],
        }
        self._write_json(task_dir / "task.json", payload)
        self._refresh_task_manifest(task_id)

    def _mirror_process_snapshot(
        self,
        *,
        process_id: str,
        task_id: str,
        parent_process_id: str,
        agent_type: str,
        priority: str,
        state: str,
        wait_kind: str,
        wait_target: str,
        wait_payload: dict[str, Any],
        capabilities: list[str],
        namespace: dict[str, Any],
        quota: dict[str, Any],
        input_preview: str,
        output_preview: str,
        last_error: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        payload = {
            "process_id": process_id,
            "task_id": task_id,
            "parent_process_id": parent_process_id,
            "agent_type": agent_type,
            "priority": priority,
            "state": state,
            "wait_kind": wait_kind,
            "wait_target": wait_target,
            "wait_payload": wait_payload,
            "capabilities": capabilities,
            "namespace": namespace,
            "quota": quota,
            "input_preview": input_preview,
            "output_preview": output_preview,
            "last_error": last_error,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        process_path = (
            self._task_session_dir(task_id)
            / "processes"
            / f"{self._safe_component(process_id)}.json"
        )
        self._write_json(process_path, payload)
        self._refresh_task_manifest(task_id)

    def _mirror_unit_snapshot(self, unit: TaskUnitRecord) -> None:
        self._write_json(
            self._task_units_dir(unit.task_id)
            / f"{self._safe_component(unit.unit_name)}.json",
            asdict(unit),
        )
        self._write_unit_graph(unit.task_id)
        self._write_target_graph(unit.task_id)
        self._refresh_task_manifest(unit.task_id)

    def _mirror_target_snapshot(self, target: TaskTargetRecord) -> None:
        self._write_json(
            self._task_targets_dir(target.task_id)
            / f"{self._safe_component(target.target_name)}.json",
            asdict(target),
        )
        self._write_target_graph(target.task_id)
        self._refresh_task_manifest(target.task_id)

    def _write_unit_graph(self, task_id: str) -> None:
        units = self.list_units(task_id, limit=500)
        nodes = [
            {
                "unit_name": unit.unit_name,
                "template_name": unit.template_name,
                "agent_type": unit.agent_type,
                "state": unit.state,
                "step_index": unit.step_index,
                "process_id": unit.process_id,
                "restart_attempts": unit.restart_attempts,
                "max_restart_attempts": unit.max_restart_attempts,
                "timeout_seconds": unit.timeout_seconds,
            }
            for unit in units
        ]
        edges: list[dict[str, str]] = []
        for unit in units:
            for dependency in unit.dependencies:
                edges.append(
                    {
                        "kind": "depends_on",
                        "from": unit.unit_name,
                        "to": dependency,
                    }
                )
            for other in unit.before_units:
                edges.append(
                    {
                        "kind": "before",
                        "from": unit.unit_name,
                        "to": other,
                    }
                )
            for target in unit.on_failure_units:
                edges.append(
                    {
                        "kind": "on_failure",
                        "from": unit.unit_name,
                        "to": target,
                    }
                )
            for target in unit.on_success_units:
                edges.append(
                    {
                        "kind": "on_success",
                        "from": unit.unit_name,
                        "to": target,
                    }
                )
        task_dir = self._task_session_dir(task_id)
        self._write_json(
            task_dir / "unit_graph.json",
            {
                "task_id": task_id,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "nodes": nodes,
                "edges": edges,
            },
        )
        lines = ["graph TD"]
        for unit in units:
            label = (
                f"{unit.unit_name}\\n{unit.state}\\n"
                f"{unit.agent_type}"
            )
            lines.append(f'    "{unit.unit_name}"["{label}"]')
        for edge in edges:
            connector = "-->"
            annotation = edge["kind"]
            if edge["kind"] in {"on_failure", "on_success"}:
                connector = "-.->"
            lines.append(
                f'    "{edge["from"]}" {connector}|{annotation}| "{edge["to"]}"'
            )
        (task_dir / "unit_graph.mmd").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_target_graph(self, task_id: str) -> None:
        task_dir = self._task_session_dir(task_id)
        targets = self.list_targets(task_id, limit=500)
        units = self.list_units(task_id, limit=500)
        unit_nodes = [
            {
                "kind": "unit",
                "name": unit.unit_name,
                "template_name": unit.template_name,
                "agent_type": unit.agent_type,
                "state": unit.state,
                "step_index": unit.step_index,
            }
            for unit in units
        ]
        target_nodes = [
            {
                "kind": "target",
                "name": target.target_name,
                "template_name": target.template_name,
                "state": target.state,
                "wanted_units": list(target.wanted_units),
                "wanted_targets": list(target.wanted_targets),
            }
            for target in targets
        ]
        edges: list[dict[str, str]] = []
        for target in targets:
            for dependency in target.dependencies:
                edges.append(
                    {
                        "kind": "target_depends_on",
                        "from": target.target_name,
                        "to": dependency,
                    }
                )
            for unit_name in target.wanted_units:
                edges.append(
                    {
                        "kind": "wants_unit",
                        "from": target.target_name,
                        "to": unit_name,
                    }
                )
            for child_target in target.wanted_targets:
                edges.append(
                    {
                        "kind": "wants_target",
                        "from": target.target_name,
                        "to": child_target,
                    }
                )
            for successor in target.on_success_targets:
                edges.append(
                    {
                        "kind": "target_on_success",
                        "from": target.target_name,
                        "to": successor,
                    }
                )
        self._write_json(
            task_dir / "target_graph.json",
            {
                "task_id": task_id,
                "node_count": len(target_nodes) + len(unit_nodes),
                "edge_count": len(edges),
                "targets": target_nodes,
                "units": unit_nodes,
                "edges": edges,
            },
        )
        lines = ["graph TD"]
        for target in targets:
            label = f"{target.target_name}\\n{target.state}\\ntarget"
            lines.append(f'    "{target.target_name}"(("{label}"))')
        for unit in units:
            label = f"{unit.unit_name}\\n{unit.state}\\n{unit.agent_type}"
            lines.append(f'    "{unit.unit_name}"["{label}"]')
        for edge in edges:
            connector = "-->"
            if edge["kind"] == "target_on_success":
                connector = "-.->"
            lines.append(
                f'    "{edge["from"]}" {connector}|{edge["kind"]}| "{edge["to"]}"'
            )
        (task_dir / "target_graph.mmd").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _mirror_event(self, event: TaskEventRecord) -> None:
        task_dir = self._task_session_dir(event.task_id)
        self._append_jsonl(task_dir / "events.jsonl", asdict(event))
        self._refresh_task_manifest(event.task_id)

    def _mirror_checkpoint(self, checkpoint: TaskCheckpointRecord) -> None:
        filename = (
            f"{checkpoint.created_at.replace(':', '-').replace('.', '-')}"
            f"_{self._safe_component(checkpoint.process_id)}"
            f"_{self._safe_component(checkpoint.phase)}"
            f"_{self._safe_component(checkpoint.checkpoint_id)}.json"
        )
        self._write_json(
            self._task_checkpoints_dir(checkpoint.task_id) / filename,
            asdict(checkpoint),
        )
        self._refresh_task_manifest(checkpoint.task_id)

    def _mirror_ipc_message(self, message: TaskIpcMessageRecord) -> None:
        task_dir = self._task_session_dir(message.task_id)
        payload = asdict(message)
        self._write_json(
            task_dir / "ipc" / f"{self._safe_component(message.message_id)}.json",
            payload,
        )
        self._append_jsonl(task_dir / "ipc.jsonl", payload)
        self._refresh_task_manifest(message.task_id)

    def _mirror_archive_memory(self, memory: MemoryRecord) -> None:
        self._write_json(
            self._archive_root / "memories" / f"{self._safe_component(memory.memory_id)}.json",
            asdict(memory),
        )
        if memory.source_task_id:
            self._refresh_task_manifest(memory.source_task_id)

    def record_tool_trace(
        self,
        *,
        task_id: str,
        process_id: str,
        kind: str,
        name: str,
        arguments: dict[str, Any],
        result: Any,
        success: bool,
    ) -> None:
        record = {
            "trace_id": uuid.uuid4().hex,
            "task_id": task_id,
            "process_id": process_id,
            "kind": kind,
            "name": name,
            "arguments": arguments,
            "result": result,
            "success": success,
            "created_at": _utcnow(),
        }
        task_dir = self._task_tools_dir(task_id)
        self._append_jsonl(task_dir / "_all.jsonl", record)
        self._append_jsonl(
            task_dir / f"{self._safe_component(process_id)}.jsonl",
            record,
        )
        self._refresh_task_manifest(task_id)

    def record_eval_result(
        self,
        *,
        task_id: str,
        process_id: str,
        agent_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> None:
        record = {
            "task_id": task_id,
            "process_id": process_id,
            "agent_type": agent_type,
            "summary": summary,
            "payload": payload,
            "created_at": _utcnow(),
        }
        self._write_json(
            self._task_evals_dir(task_id)
            / f"{self._safe_component(agent_type)}_{self._safe_component(process_id)}.json",
            record,
        )
        self._refresh_task_manifest(task_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    user_request TEXT NOT NULL,
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    final_summary TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS task_steps (
                    task_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (task_id, step_index)
                );

                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    source_task_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_processes (
                    process_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    parent_process_id TEXT NOT NULL DEFAULT '',
                    agent_type TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    state TEXT NOT NULL,
                    wait_kind TEXT NOT NULL DEFAULT '',
                    wait_target TEXT NOT NULL DEFAULT '',
                    wait_payload_json TEXT NOT NULL DEFAULT '{}',
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    namespace_json TEXT NOT NULL DEFAULT '{}',
                    quota_json TEXT NOT NULL DEFAULT '{}',
                    input_preview TEXT NOT NULL DEFAULT '',
                    output_preview TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_task_processes_task
                ON task_processes(task_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS task_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    process_id TEXT NOT NULL DEFAULT '',
                    parent_process_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_task_events_task
                ON task_events(task_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    process_id TEXT NOT NULL DEFAULT '',
                    phase TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_task_checkpoints_task
                ON task_checkpoints(task_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS task_ipc_messages (
                    message_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    sender_process_id TEXT NOT NULL DEFAULT '',
                    recipient_process_id TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL DEFAULT 'default',
                    message_text TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    read_at TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_task_ipc_recipient
                ON task_ipc_messages(task_id, recipient_process_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS task_units (
                    unit_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    unit_name TEXT NOT NULL,
                    template_name TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    step_index INTEGER NOT NULL DEFAULT 0,
                    parent_unit_name TEXT NOT NULL DEFAULT '',
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    after_units_json TEXT NOT NULL DEFAULT '[]',
                    before_units_json TEXT NOT NULL DEFAULT '[]',
                    on_failure_units_json TEXT NOT NULL DEFAULT '[]',
                    on_success_units_json TEXT NOT NULL DEFAULT '[]',
                    restart_policy TEXT NOT NULL DEFAULT 'never',
                    restart_attempts INTEGER NOT NULL DEFAULT 0,
                    max_restart_attempts INTEGER NOT NULL DEFAULT 0,
                    timeout_seconds INTEGER NOT NULL DEFAULT 0,
                    process_id TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'inactive',
                    summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, unit_name)
                );

                CREATE INDEX IF NOT EXISTS idx_task_units_task
                ON task_units(task_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS task_targets (
                    target_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    template_name TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    wanted_units_json TEXT NOT NULL DEFAULT '[]',
                    wanted_targets_json TEXT NOT NULL DEFAULT '[]',
                    on_success_targets_json TEXT NOT NULL DEFAULT '[]',
                    state TEXT NOT NULL DEFAULT 'inactive',
                    summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, target_name)
                );

                CREATE INDEX IF NOT EXISTS idx_task_targets_task
                ON task_targets(task_id, updated_at DESC);
                """
            )
            task_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "attachments_json" not in task_columns:
                connection.execute(
                    "ALTER TABLE tasks ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'"
                )
            process_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(task_processes)").fetchall()
            }
            if "wait_kind" not in process_columns:
                connection.execute(
                    "ALTER TABLE task_processes ADD COLUMN wait_kind TEXT NOT NULL DEFAULT ''"
                )
            if "wait_target" not in process_columns:
                connection.execute(
                    "ALTER TABLE task_processes ADD COLUMN wait_target TEXT NOT NULL DEFAULT ''"
                )
            if "wait_payload_json" not in process_columns:
                connection.execute(
                    "ALTER TABLE task_processes ADD COLUMN wait_payload_json TEXT NOT NULL DEFAULT '{}'"
                )
            unit_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(task_units)").fetchall()
            }
            if "step_index" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN step_index INTEGER NOT NULL DEFAULT 0"
                )
            if "parent_unit_name" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN parent_unit_name TEXT NOT NULL DEFAULT ''"
                )
            if "dependencies_json" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN dependencies_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "after_units_json" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN after_units_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "before_units_json" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN before_units_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "on_failure_units_json" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN on_failure_units_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "on_success_units_json" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN on_success_units_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "restart_policy" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN restart_policy TEXT NOT NULL DEFAULT 'never'"
                )
            if "restart_attempts" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN restart_attempts INTEGER NOT NULL DEFAULT 0"
                )
            if "max_restart_attempts" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN max_restart_attempts INTEGER NOT NULL DEFAULT 0"
                )
            if "timeout_seconds" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN timeout_seconds INTEGER NOT NULL DEFAULT 0"
                )
            if "process_id" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN process_id TEXT NOT NULL DEFAULT ''"
                )
            if "summary" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN summary TEXT NOT NULL DEFAULT ''"
                )
            if "metadata_json" not in unit_columns:
                connection.execute(
                    "ALTER TABLE task_units ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                )
            target_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(task_targets)").fetchall()
            }
            if "dependencies_json" not in target_columns and target_columns:
                connection.execute(
                    "ALTER TABLE task_targets ADD COLUMN dependencies_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "wanted_units_json" not in target_columns and target_columns:
                connection.execute(
                    "ALTER TABLE task_targets ADD COLUMN wanted_units_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "wanted_targets_json" not in target_columns and target_columns:
                connection.execute(
                    "ALTER TABLE task_targets ADD COLUMN wanted_targets_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "on_success_targets_json" not in target_columns and target_columns:
                connection.execute(
                    "ALTER TABLE task_targets ADD COLUMN on_success_targets_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "summary" not in target_columns and target_columns:
                connection.execute(
                    "ALTER TABLE task_targets ADD COLUMN summary TEXT NOT NULL DEFAULT ''"
                )
            if "metadata_json" not in target_columns and target_columns:
                connection.execute(
                    "ALTER TABLE task_targets ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                )

    def new_task_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def create_task(
        self,
        *,
        title: str,
        goal: str,
        user_request: str,
        attachments: list[dict[str, str]],
        steps: list[dict[str, str]],
        task_id: str | None = None,
    ) -> TaskRecord:
        task_id = task_id or self.new_task_id()
        timestamp = _utcnow()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks(task_id, title, goal, user_request, attachments_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'in_progress', ?, ?)
                """,
                (
                    task_id,
                    title,
                    goal,
                    user_request,
                    json.dumps(attachments, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
            connection.executemany(
                """
                INSERT INTO task_steps(task_id, step_index, title, description, status, result)
                VALUES (?, ?, ?, ?, 'pending', '')
                """,
                [
                    (
                        task_id,
                        index,
                        step["title"],
                        step["description"],
                    )
                    for index, step in enumerate(steps, start=1)
                ],
            )
        task = self.get_task(task_id)
        self._mirror_task_snapshot(task.task_id)
        return task

    def get_task(self, task_id: str) -> TaskRecord:
        with self._connect() as connection:
            task_row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task_row is None:
                raise KeyError(f"Unknown task_id: {task_id}")
            step_rows = connection.execute(
                """
                SELECT step_index, title, description, status, result
                FROM task_steps
                WHERE task_id = ?
                ORDER BY step_index
                """,
                (task_id,),
            ).fetchall()

        return TaskRecord(
            task_id=task_row["task_id"],
            title=task_row["title"],
            goal=task_row["goal"],
            user_request=task_row["user_request"],
            attachments=json.loads(task_row["attachments_json"] or "[]"),
            status=task_row["status"],
            created_at=task_row["created_at"],
            updated_at=task_row["updated_at"],
            final_summary=task_row["final_summary"],
            steps=[
                TaskStepRecord(
                    step_index=row["step_index"],
                    title=row["title"],
                    description=row["description"],
                    status=row["status"],
                    result=row["result"],
                )
                for row in step_rows
            ],
        )

    def update_step_status(
        self,
        *,
        task_id: str,
        step_index: int,
        status: str,
        result: str,
    ) -> None:
        timestamp = _utcnow()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_steps
                SET status = ?, result = ?
                WHERE task_id = ? AND step_index = ?
                """,
                (status, result, task_id, step_index),
            )
            connection.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                (timestamp, task_id),
            )
        self._mirror_task_snapshot(task_id)

    def set_task_status(
        self,
        *,
        task_id: str,
        status: str,
        final_summary: str = "",
    ) -> None:
        timestamp = _utcnow()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, final_summary = ?
                WHERE task_id = ?
                """,
                (status, timestamp, final_summary, task_id),
            )
        self._mirror_task_snapshot(task_id)

    def list_recent_tasks(self, limit: int) -> list[TaskRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id
                FROM tasks
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self.get_task(row["task_id"]) for row in rows]

    def create_memory(
        self,
        *,
        kind: str,
        summary: str,
        content: str,
        tags: list[str],
        source_task_id: str = "",
    ) -> None:
        memory = MemoryRecord(
            memory_id=uuid.uuid4().hex,
            kind=kind,
            summary=summary,
            content=content,
            tags=list(tags),
            source_task_id=source_task_id,
            created_at=_utcnow(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memories(memory_id, kind, summary, content, tags, source_task_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.memory_id,
                    memory.kind,
                    memory.summary,
                    memory.content,
                    json.dumps(memory.tags, ensure_ascii=False),
                    memory.source_task_id,
                    memory.created_at,
                ),
            )
        self._mirror_archive_memory(memory)

    def search_memories(self, query: str, limit: int) -> list[MemoryRecord]:
        query_terms = _tokenize(query)
        if not query_terms:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT memory_id, kind, summary, content, tags, source_task_id, created_at
                FROM memories
                ORDER BY created_at DESC
                LIMIT 200
                """
            ).fetchall()

        scored: list[tuple[float, MemoryRecord]] = []
        for row in rows:
            summary = row["summary"]
            content = row["content"]
            tags = json.loads(row["tags"])
            haystack_terms = _tokenize(summary + " " + content + " " + " ".join(tags))
            overlap = len(query_terms & haystack_terms)
            if overlap == 0:
                continue
            score = overlap * 3
            if any(term in summary.lower() for term in query_terms):
                score += 2
            scored.append(
                (
                    score,
                    MemoryRecord(
                        memory_id=row["memory_id"],
                        kind=row["kind"],
                        summary=summary,
                        content=content,
                        tags=tags,
                        source_task_id=row["source_task_id"],
                        created_at=row["created_at"],
                    ),
                )
            )

        scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return [record for _, record in scored[:limit]]

    def upsert_process(
        self,
        *,
        process_id: str,
        task_id: str,
        parent_process_id: str,
        agent_type: str,
        priority: str,
        state: str,
        wait_kind: str,
        wait_target: str,
        wait_payload: dict[str, Any],
        capabilities: list[str],
        namespace: dict[str, Any],
        quota: dict[str, Any],
        input_preview: str,
        output_preview: str,
        last_error: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_processes(
                    process_id, task_id, parent_process_id, agent_type, priority, state,
                    wait_kind, wait_target, wait_payload_json, capabilities_json,
                    namespace_json, quota_json, input_preview, output_preview, last_error,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(process_id) DO UPDATE SET
                    task_id=excluded.task_id,
                    parent_process_id=excluded.parent_process_id,
                    agent_type=excluded.agent_type,
                    priority=excluded.priority,
                    state=excluded.state,
                    wait_kind=excluded.wait_kind,
                    wait_target=excluded.wait_target,
                    wait_payload_json=excluded.wait_payload_json,
                    capabilities_json=excluded.capabilities_json,
                    namespace_json=excluded.namespace_json,
                    quota_json=excluded.quota_json,
                    input_preview=excluded.input_preview,
                    output_preview=excluded.output_preview,
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at
                """,
                (
                    process_id,
                    task_id,
                    parent_process_id,
                    agent_type,
                    priority,
                    state,
                    wait_kind,
                    wait_target,
                    json.dumps(wait_payload, ensure_ascii=False),
                    json.dumps(capabilities, ensure_ascii=False),
                    json.dumps(namespace, ensure_ascii=False),
                    json.dumps(quota, ensure_ascii=False),
                    input_preview,
                    output_preview,
                    last_error,
                    created_at,
                    updated_at,
                ),
            )
        self._mirror_process_snapshot(
            process_id=process_id,
            task_id=task_id,
            parent_process_id=parent_process_id,
            agent_type=agent_type,
            priority=priority,
            state=state,
            wait_kind=wait_kind,
            wait_target=wait_target,
            wait_payload=wait_payload,
            capabilities=capabilities,
            namespace=namespace,
            quota=quota,
            input_preview=input_preview,
            output_preview=output_preview,
            last_error=last_error,
            created_at=created_at,
            updated_at=updated_at,
        )

    def list_processes(self, task_id: str, limit: int = 50) -> list[TaskProcessRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM task_processes
                WHERE task_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [
            TaskProcessRecord(
                process_id=row["process_id"],
                task_id=row["task_id"],
                parent_process_id=row["parent_process_id"],
                agent_type=row["agent_type"],
                priority=row["priority"],
                state=row["state"],
                wait_kind=row["wait_kind"],
                wait_target=row["wait_target"],
                wait_payload=json.loads(row["wait_payload_json"] or "{}"),
                capabilities=json.loads(row["capabilities_json"] or "[]"),
                namespace=json.loads(row["namespace_json"] or "{}"),
                quota=json.loads(row["quota_json"] or "{}"),
                input_preview=row["input_preview"],
                output_preview=row["output_preview"],
                last_error=row["last_error"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def get_process(self, process_id: str) -> TaskProcessRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM task_processes
                WHERE process_id = ?
                """,
                (process_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown process_id: {process_id}")
        return TaskProcessRecord(
            process_id=row["process_id"],
            task_id=row["task_id"],
            parent_process_id=row["parent_process_id"],
            agent_type=row["agent_type"],
            priority=row["priority"],
            state=row["state"],
            wait_kind=row["wait_kind"],
            wait_target=row["wait_target"],
            wait_payload=json.loads(row["wait_payload_json"] or "{}"),
            capabilities=json.loads(row["capabilities_json"] or "[]"),
            namespace=json.loads(row["namespace_json"] or "{}"),
            quota=json.loads(row["quota_json"] or "{}"),
            input_preview=row["input_preview"],
            output_preview=row["output_preview"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_unit(
        self,
        *,
        unit_id: str,
        task_id: str,
        unit_name: str,
        template_name: str,
        agent_type: str,
        step_index: int,
        parent_unit_name: str,
        dependencies: list[str],
        after_units: list[str],
        before_units: list[str],
        on_failure_units: list[str],
        on_success_units: list[str],
        restart_policy: str,
        restart_attempts: int,
        max_restart_attempts: int,
        timeout_seconds: int,
        process_id: str,
        state: str,
        summary: str,
        metadata: dict[str, Any],
        created_at: str,
        updated_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_units(
                    unit_id, task_id, unit_name, template_name, agent_type, step_index,
                    parent_unit_name, dependencies_json, after_units_json, before_units_json,
                    on_failure_units_json, on_success_units_json, restart_policy, restart_attempts,
                    max_restart_attempts, timeout_seconds, process_id, state, summary, metadata_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, unit_name) DO UPDATE SET
                    template_name=excluded.template_name,
                    agent_type=excluded.agent_type,
                    step_index=excluded.step_index,
                    parent_unit_name=excluded.parent_unit_name,
                    dependencies_json=excluded.dependencies_json,
                    after_units_json=excluded.after_units_json,
                    before_units_json=excluded.before_units_json,
                    on_failure_units_json=excluded.on_failure_units_json,
                    on_success_units_json=excluded.on_success_units_json,
                    restart_policy=excluded.restart_policy,
                    restart_attempts=excluded.restart_attempts,
                    max_restart_attempts=excluded.max_restart_attempts,
                    timeout_seconds=excluded.timeout_seconds,
                    process_id=excluded.process_id,
                    state=excluded.state,
                    summary=excluded.summary,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    unit_id,
                    task_id,
                    unit_name,
                    template_name,
                    agent_type,
                    step_index,
                    parent_unit_name,
                    json.dumps(dependencies, ensure_ascii=False),
                    json.dumps(after_units, ensure_ascii=False),
                    json.dumps(before_units, ensure_ascii=False),
                    json.dumps(on_failure_units, ensure_ascii=False),
                    json.dumps(on_success_units, ensure_ascii=False),
                    restart_policy,
                    restart_attempts,
                    max_restart_attempts,
                    timeout_seconds,
                    process_id,
                    state,
                    summary,
                    json.dumps(metadata, ensure_ascii=False),
                    created_at,
                    updated_at,
                ),
            )
        unit = self.get_unit(task_id, unit_name)
        self._mirror_unit_snapshot(unit)

    def list_units(self, task_id: str, limit: int = 100) -> list[TaskUnitRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM task_units
                WHERE task_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [
            TaskUnitRecord(
                unit_id=row["unit_id"],
                task_id=row["task_id"],
                unit_name=row["unit_name"],
                template_name=row["template_name"],
                agent_type=row["agent_type"],
                step_index=int(row["step_index"] or 0),
                parent_unit_name=row["parent_unit_name"],
                dependencies=json.loads(row["dependencies_json"] or "[]"),
                after_units=json.loads(row["after_units_json"] or "[]"),
                before_units=json.loads(row["before_units_json"] or "[]"),
                on_failure_units=json.loads(row["on_failure_units_json"] or "[]"),
                on_success_units=json.loads(row["on_success_units_json"] or "[]"),
                restart_policy=row["restart_policy"],
                restart_attempts=int(row["restart_attempts"] or 0),
                max_restart_attempts=int(row["max_restart_attempts"] or 0),
                timeout_seconds=int(row["timeout_seconds"] or 0),
                process_id=row["process_id"],
                state=row["state"],
                summary=row["summary"],
                metadata=json.loads(row["metadata_json"] or "{}"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def get_unit(self, task_id: str, unit_name: str) -> TaskUnitRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM task_units
                WHERE task_id = ? AND unit_name = ?
                """,
                (task_id, unit_name),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown unit {unit_name!r} for task {task_id}")
        return TaskUnitRecord(
            unit_id=row["unit_id"],
            task_id=row["task_id"],
            unit_name=row["unit_name"],
            template_name=row["template_name"],
            agent_type=row["agent_type"],
            step_index=int(row["step_index"] or 0),
            parent_unit_name=row["parent_unit_name"],
            dependencies=json.loads(row["dependencies_json"] or "[]"),
            after_units=json.loads(row["after_units_json"] or "[]"),
            before_units=json.loads(row["before_units_json"] or "[]"),
            on_failure_units=json.loads(row["on_failure_units_json"] or "[]"),
            on_success_units=json.loads(row["on_success_units_json"] or "[]"),
            restart_policy=row["restart_policy"],
            restart_attempts=int(row["restart_attempts"] or 0),
            max_restart_attempts=int(row["max_restart_attempts"] or 0),
            timeout_seconds=int(row["timeout_seconds"] or 0),
            process_id=row["process_id"],
            state=row["state"],
            summary=row["summary"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def find_unit(self, task_id: str, unit_name: str) -> TaskUnitRecord | None:
        try:
            return self.get_unit(task_id, unit_name)
        except KeyError:
            return None

    def find_unit_by_process(self, task_id: str, process_id: str) -> TaskUnitRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM task_units
                WHERE task_id = ? AND process_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (task_id, process_id),
            ).fetchone()
        if row is None:
            return None
        return TaskUnitRecord(
            unit_id=row["unit_id"],
            task_id=row["task_id"],
            unit_name=row["unit_name"],
            template_name=row["template_name"],
            agent_type=row["agent_type"],
            step_index=int(row["step_index"] or 0),
            parent_unit_name=row["parent_unit_name"],
            dependencies=json.loads(row["dependencies_json"] or "[]"),
            after_units=json.loads(row["after_units_json"] or "[]"),
            before_units=json.loads(row["before_units_json"] or "[]"),
            on_failure_units=json.loads(row["on_failure_units_json"] or "[]"),
            on_success_units=json.loads(row["on_success_units_json"] or "[]"),
            restart_policy=row["restart_policy"],
            restart_attempts=int(row["restart_attempts"] or 0),
            max_restart_attempts=int(row["max_restart_attempts"] or 0),
            timeout_seconds=int(row["timeout_seconds"] or 0),
            process_id=row["process_id"],
            state=row["state"],
            summary=row["summary"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_target(
        self,
        *,
        target_id: str,
        task_id: str,
        target_name: str,
        template_name: str,
        dependencies: list[str],
        wanted_units: list[str],
        wanted_targets: list[str],
        on_success_targets: list[str],
        state: str,
        summary: str,
        metadata: dict[str, Any],
        created_at: str,
        updated_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_targets(
                    target_id, task_id, target_name, template_name,
                    dependencies_json, wanted_units_json, wanted_targets_json,
                    on_success_targets_json, state, summary, metadata_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, target_name) DO UPDATE SET
                    template_name=excluded.template_name,
                    dependencies_json=excluded.dependencies_json,
                    wanted_units_json=excluded.wanted_units_json,
                    wanted_targets_json=excluded.wanted_targets_json,
                    on_success_targets_json=excluded.on_success_targets_json,
                    state=excluded.state,
                    summary=excluded.summary,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    target_id,
                    task_id,
                    target_name,
                    template_name,
                    json.dumps(dependencies, ensure_ascii=False),
                    json.dumps(wanted_units, ensure_ascii=False),
                    json.dumps(wanted_targets, ensure_ascii=False),
                    json.dumps(on_success_targets, ensure_ascii=False),
                    state,
                    summary,
                    json.dumps(metadata, ensure_ascii=False),
                    created_at,
                    updated_at,
                ),
            )
        target = self.get_target(task_id, target_name)
        self._mirror_target_snapshot(target)

    def list_targets(self, task_id: str, limit: int = 100) -> list[TaskTargetRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM task_targets
                WHERE task_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [
            TaskTargetRecord(
                target_id=row["target_id"],
                task_id=row["task_id"],
                target_name=row["target_name"],
                template_name=row["template_name"],
                dependencies=json.loads(row["dependencies_json"] or "[]"),
                wanted_units=json.loads(row["wanted_units_json"] or "[]"),
                wanted_targets=json.loads(row["wanted_targets_json"] or "[]"),
                on_success_targets=json.loads(row["on_success_targets_json"] or "[]"),
                state=row["state"],
                summary=row["summary"],
                metadata=json.loads(row["metadata_json"] or "{}"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def get_target(self, task_id: str, target_name: str) -> TaskTargetRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM task_targets
                WHERE task_id = ? AND target_name = ?
                """,
                (task_id, target_name),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown target {target_name!r} for task {task_id}")
        return TaskTargetRecord(
            target_id=row["target_id"],
            task_id=row["task_id"],
            target_name=row["target_name"],
            template_name=row["template_name"],
            dependencies=json.loads(row["dependencies_json"] or "[]"),
            wanted_units=json.loads(row["wanted_units_json"] or "[]"),
            wanted_targets=json.loads(row["wanted_targets_json"] or "[]"),
            on_success_targets=json.loads(row["on_success_targets_json"] or "[]"),
            state=row["state"],
            summary=row["summary"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def find_target(self, task_id: str, target_name: str) -> TaskTargetRecord | None:
        try:
            return self.get_target(task_id, target_name)
        except KeyError:
            return None

    def create_event(
        self,
        *,
        task_id: str,
        process_id: str = "",
        parent_process_id: str = "",
        kind: str,
        level: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> TaskEventRecord:
        event = TaskEventRecord(
            event_id=uuid.uuid4().hex,
            task_id=task_id,
            process_id=process_id,
            parent_process_id=parent_process_id,
            kind=kind,
            level=level,
            message=message,
            payload=payload or {},
            created_at=_utcnow(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_events(
                    event_id, task_id, process_id, parent_process_id,
                    kind, level, message, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    event.process_id,
                    event.parent_process_id,
                    event.kind,
                    event.level,
                    event.message,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.created_at,
                ),
            )
        self._mirror_event(event)
        return event

    def list_events(self, task_id: str, limit: int = 50) -> list[TaskEventRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM task_events
                WHERE task_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [
            TaskEventRecord(
                event_id=row["event_id"],
                task_id=row["task_id"],
                process_id=row["process_id"],
                parent_process_id=row["parent_process_id"],
                kind=row["kind"],
                level=row["level"],
                message=row["message"],
                payload=json.loads(row["payload_json"] or "{}"),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_checkpoint(
        self,
        *,
        task_id: str,
        process_id: str,
        phase: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> TaskCheckpointRecord:
        checkpoint = TaskCheckpointRecord(
            checkpoint_id=uuid.uuid4().hex,
            task_id=task_id,
            process_id=process_id,
            phase=phase,
            summary=summary,
            payload=payload or {},
            created_at=_utcnow(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_checkpoints(
                    checkpoint_id, task_id, process_id, phase, summary, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.task_id,
                    checkpoint.process_id,
                    checkpoint.phase,
                    checkpoint.summary,
                    json.dumps(checkpoint.payload, ensure_ascii=False),
                    checkpoint.created_at,
                ),
            )
        self._mirror_checkpoint(checkpoint)
        return checkpoint

    def list_checkpoints(
        self,
        task_id: str,
        limit: int = 20,
    ) -> list[TaskCheckpointRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM task_checkpoints
                WHERE task_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [
            TaskCheckpointRecord(
                checkpoint_id=row["checkpoint_id"],
                task_id=row["task_id"],
                process_id=row["process_id"],
                phase=row["phase"],
                summary=row["summary"],
                payload=json.loads(row["payload_json"] or "{}"),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_checkpoint(self, checkpoint_id: str) -> TaskCheckpointRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM task_checkpoints
                WHERE checkpoint_id = ?
                """,
                (checkpoint_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown checkpoint_id: {checkpoint_id}")
        return TaskCheckpointRecord(
            checkpoint_id=row["checkpoint_id"],
            task_id=row["task_id"],
            process_id=row["process_id"],
            phase=row["phase"],
            summary=row["summary"],
            payload=json.loads(row["payload_json"] or "{}"),
            created_at=row["created_at"],
        )

    def get_latest_checkpoint_for_process(
        self,
        process_id: str,
        *,
        phase: str | None = None,
    ) -> TaskCheckpointRecord | None:
        query = """
            SELECT *
            FROM task_checkpoints
            WHERE process_id = ?
        """
        parameters: list[Any] = [process_id]
        if phase:
            query += " AND phase = ?"
            parameters.append(phase)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        if row is None:
            return None
        return TaskCheckpointRecord(
            checkpoint_id=row["checkpoint_id"],
            task_id=row["task_id"],
            process_id=row["process_id"],
            phase=row["phase"],
            summary=row["summary"],
            payload=json.loads(row["payload_json"] or "{}"),
            created_at=row["created_at"],
        )

    def create_ipc_message(
        self,
        *,
        task_id: str,
        sender_process_id: str,
        recipient_process_id: str,
        channel: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> TaskIpcMessageRecord:
        record = TaskIpcMessageRecord(
            message_id=uuid.uuid4().hex,
            task_id=task_id,
            sender_process_id=sender_process_id,
            recipient_process_id=recipient_process_id,
            channel=channel,
            message=message,
            payload=payload or {},
            status="pending",
            created_at=_utcnow(),
            read_at="",
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_ipc_messages(
                    message_id, task_id, sender_process_id, recipient_process_id,
                    channel, message_text, payload_json, status, created_at, read_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.message_id,
                    record.task_id,
                    record.sender_process_id,
                    record.recipient_process_id,
                    record.channel,
                    record.message,
                    json.dumps(record.payload, ensure_ascii=False),
                    record.status,
                    record.created_at,
                    record.read_at,
                ),
            )
        self._mirror_ipc_message(record)
        return record

    def list_ipc_messages(
        self,
        task_id: str,
        *,
        recipient_process_id: str = "",
        channel: str = "",
        limit: int = 50,
        include_delivered: bool = True,
    ) -> list[TaskIpcMessageRecord]:
        query = """
            SELECT *
            FROM task_ipc_messages
            WHERE task_id = ?
        """
        parameters: list[Any] = [task_id]
        if recipient_process_id:
            query += " AND recipient_process_id = ?"
            parameters.append(recipient_process_id)
        if channel:
            query += " AND channel = ?"
            parameters.append(channel)
        if not include_delivered:
            query += " AND status = 'pending'"
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            TaskIpcMessageRecord(
                message_id=row["message_id"],
                task_id=row["task_id"],
                sender_process_id=row["sender_process_id"],
                recipient_process_id=row["recipient_process_id"],
                channel=row["channel"],
                message=row["message_text"],
                payload=json.loads(row["payload_json"] or "{}"),
                status=row["status"],
                created_at=row["created_at"],
                read_at=row["read_at"],
            )
            for row in rows
        ]

    def consume_ipc_messages(
        self,
        *,
        task_id: str,
        recipient_process_id: str,
        channel: str = "",
        limit: int = 20,
    ) -> list[TaskIpcMessageRecord]:
        messages = self.list_ipc_messages(
            task_id,
            recipient_process_id=recipient_process_id,
            channel=channel,
            limit=limit,
            include_delivered=False,
        )
        if not messages:
            return []
        message_ids = [message.message_id for message in messages]
        read_at = _utcnow()
        placeholders = ", ".join("?" for _ in message_ids)
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE task_ipc_messages
                SET status = 'delivered', read_at = ?
                WHERE message_id IN ({placeholders})
                """,
                [read_at, *message_ids],
            )
        delivered: list[TaskIpcMessageRecord] = []
        for message in messages:
            delivered_message = TaskIpcMessageRecord(
                message_id=message.message_id,
                task_id=message.task_id,
                sender_process_id=message.sender_process_id,
                recipient_process_id=message.recipient_process_id,
                channel=message.channel,
                message=message.message,
                payload=message.payload,
                status="delivered",
                created_at=message.created_at,
                read_at=read_at,
            )
            delivered.append(delivered_message)
            self._mirror_ipc_message(delivered_message)
        return delivered
