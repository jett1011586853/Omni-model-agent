from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


@dataclass(frozen=True)
class ModelRuntimeConfig:
    temperature: float
    top_p: float
    max_output_tokens: int
    context_window_tokens: int
    request_timeout_seconds: int
    history_safety_margin_tokens: int
    chars_per_token_estimate: float


@dataclass(frozen=True)
class PlannerRuntimeConfig:
    max_steps: int
    max_output_tokens: int
    temperature: float


@dataclass(frozen=True)
class AgentRuntimeConfig:
    system_prompt: str
    max_tool_rounds: int
    max_history_messages: int
    max_execution_steps: int


@dataclass(frozen=True)
class StorageRuntimeConfig:
    state_dir: str
    recent_task_limit: int
    memory_search_limit: int


@dataclass(frozen=True)
class WebSearchRuntimeConfig:
    max_results: int
    region: str
    safesearch: str


@dataclass(frozen=True)
class StreamingConfig:
    show_reasoning: bool
    show_answer: bool
    show_tool_events: bool
    show_usage: bool


@dataclass(frozen=True)
class SshRuntimeConfig:
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_password: str
    remote_host: str
    remote_port: int
    local_host: str
    local_port: int


@dataclass(frozen=True)
class AgentOSRuntimeConfig:
    enabled: bool
    router_enabled: bool
    critic_enabled: bool
    verifier_enabled: bool
    compressor_enabled: bool
    supervisor_enabled: bool
    supervisor_max_cycles: int
    supervisor_pump_limit: int
    default_retry_budget: int
    default_tool_call_budget: int
    default_child_agent_budget: int
    default_token_budget: int
    compressor_trigger_chars: int
    vfs_mounts: dict[str, str]


@dataclass(frozen=True)
class AppConfig:
    workspace_root: Path
    model_name: str
    model_api_key: str
    model_base_url: str
    model: ModelRuntimeConfig
    planner: PlannerRuntimeConfig
    agent: AgentRuntimeConfig
    storage: StorageRuntimeConfig
    web_search: WebSearchRuntimeConfig
    streaming: StreamingConfig
    agentos: AgentOSRuntimeConfig
    ssh: SshRuntimeConfig | None

    @property
    def state_dir(self) -> Path:
        return self.workspace_root / self.storage.state_dir


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_runtime_path(root: Path, value: Any) -> str:
    path = Path(str(value))
    if not path.is_absolute():
        path = root / path
    return str(path.resolve())


def _build_default_mounts(root: Path, state_dir: str) -> dict[str, str]:
    state_root = root / state_dir
    return {
        "/workspace/repo": str(root),
        "/skills": str(root / "skills"),
        "/memory/session": str(state_root / "session"),
        "/memory/archive": str(state_root / "archive"),
        "/checkpoints": str(state_root / "checkpoints"),
        "/tools/output": str(state_root / "tools"),
        "/evals": str(state_root / "evals"),
    }


def load_app_config(workspace_root: Path | None = None) -> AppConfig:
    root = (workspace_root or Path.cwd()).resolve()
    load_dotenv(root / ".env")

    config_path = root / "config.json"
    if not config_path.exists():
        raise RuntimeError(f"Missing config file: {config_path}")

    raw = _read_json(config_path)
    model_raw = raw.get("model", {})
    planner_raw = raw.get("planner", {})
    agent_raw = raw.get("agent", {})
    storage_raw = raw.get("storage", {})
    web_search_raw = raw.get("web_search", {})
    streaming_raw = raw.get("streaming", {})
    agentos_raw = raw.get("agentos", {})

    storage_state_dir = str(storage_raw.get("state_dir", ".agent_state"))
    default_mounts = _build_default_mounts(root, storage_state_dir)
    env_system_prompt = os.getenv("AGENT_SYSTEM_PROMPT", "").strip()

    ssh: SshRuntimeConfig | None = None
    ssh_password = os.getenv("SSH_PASSWORD", "")
    if ssh_password:
        ssh = SshRuntimeConfig(
            ssh_host=_require_env("SSH_HOST"),
            ssh_port=int(_require_env("SSH_PORT")),
            ssh_user=_require_env("SSH_USER"),
            ssh_password=ssh_password,
            remote_host=_require_env("REMOTE_MODEL_HOST"),
            remote_port=int(_require_env("REMOTE_MODEL_PORT")),
            local_host=_require_env("LOCAL_FORWARD_HOST"),
            local_port=int(_require_env("LOCAL_FORWARD_PORT")),
        )

    return AppConfig(
        workspace_root=root,
        model_name=_require_env("MODEL_NAME"),
        model_api_key=_require_env("MODEL_API_KEY"),
        model_base_url=_require_env("MODEL_BASE_URL").rstrip("/"),
        model=ModelRuntimeConfig(
            temperature=float(model_raw.get("temperature", 0.7)),
            top_p=float(model_raw.get("top_p", 0.95)),
            max_output_tokens=int(model_raw.get("max_output_tokens", 250000)),
            context_window_tokens=int(model_raw.get("context_window_tokens", 260000)),
            request_timeout_seconds=int(model_raw.get("request_timeout_seconds", 7200)),
            history_safety_margin_tokens=int(
                model_raw.get("history_safety_margin_tokens", 4096)
            ),
            chars_per_token_estimate=float(
                model_raw.get("chars_per_token_estimate", 4.0)
            ),
        ),
        planner=PlannerRuntimeConfig(
            max_steps=int(planner_raw.get("max_steps", 12)),
            max_output_tokens=int(planner_raw.get("max_output_tokens", 2048)),
            temperature=float(planner_raw.get("temperature", 0.2)),
        ),
        agent=AgentRuntimeConfig(
            system_prompt=env_system_prompt
            or str(
                agent_raw.get(
                    "system_prompt",
                    "You are a practical engineering task agent. Make plans, execute them "
                    "with tools, keep task state consistent, and produce grounded results. "
                    "请用中文回答。涉及数学公式时使用 Unicode 或普通文本，不要使用 LaTeX。",
                )
            ),
            max_tool_rounds=int(agent_raw.get("max_tool_rounds", 24)),
            max_history_messages=int(agent_raw.get("max_history_messages", 24)),
            max_execution_steps=int(agent_raw.get("max_execution_steps", 12)),
        ),
        storage=StorageRuntimeConfig(
            state_dir=storage_state_dir,
            recent_task_limit=int(storage_raw.get("recent_task_limit", 5)),
            memory_search_limit=int(storage_raw.get("memory_search_limit", 6)),
        ),
        web_search=WebSearchRuntimeConfig(
            max_results=int(web_search_raw.get("max_results", 5)),
            region=str(web_search_raw.get("region", "cn-zh")),
            safesearch=str(web_search_raw.get("safesearch", "moderate")),
        ),
        streaming=StreamingConfig(
            show_reasoning=bool(streaming_raw.get("show_reasoning", True)),
            show_answer=bool(streaming_raw.get("show_answer", True)),
            show_tool_events=bool(streaming_raw.get("show_tool_events", True)),
            show_usage=bool(streaming_raw.get("show_usage", True)),
        ),
        agentos=AgentOSRuntimeConfig(
            enabled=bool(agentos_raw.get("enabled", True)),
            router_enabled=bool(agentos_raw.get("router_enabled", True)),
            critic_enabled=bool(agentos_raw.get("critic_enabled", True)),
            verifier_enabled=bool(agentos_raw.get("verifier_enabled", True)),
            compressor_enabled=bool(agentos_raw.get("compressor_enabled", True)),
            supervisor_enabled=bool(agentos_raw.get("supervisor_enabled", True)),
            supervisor_max_cycles=int(
                agentos_raw.get("supervisor_max_cycles", 8)
            ),
            supervisor_pump_limit=int(
                agentos_raw.get("supervisor_pump_limit", 64)
            ),
            default_retry_budget=int(agentos_raw.get("default_retry_budget", 1)),
            default_tool_call_budget=int(
                agentos_raw.get("default_tool_call_budget", 48)
            ),
            default_child_agent_budget=int(
                agentos_raw.get("default_child_agent_budget", 24)
            ),
            default_token_budget=int(
                agentos_raw.get(
                    "default_token_budget",
                    int(model_raw.get("context_window_tokens", 260000))
                    + int(model_raw.get("max_output_tokens", 250000)),
                )
            ),
            compressor_trigger_chars=int(
                agentos_raw.get("compressor_trigger_chars", 2500)
            ),
            vfs_mounts={
                str(key): _resolve_runtime_path(root, value)
                for key, value in agentos_raw.get("vfs_mounts", default_mounts).items()
            },
        ),
        ssh=ssh,
    )
