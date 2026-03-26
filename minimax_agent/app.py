from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .agentos import AgentKernel
from .config import AppConfig
from .graph_agent import GraphAgent
from .model_client import OpenAICompatibleModelClient
from .planner import TaskPlanner
from .rendering import ConsoleRenderer
from .task_agent import TaskAgent
from .task_store import TaskStore
from .tools import build_tool_registry

if TYPE_CHECKING:
    from tunnel import SshTunnel


class AgentApplication:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._tunnel: Any | None = None
        self._client = OpenAICompatibleModelClient(config)
        self._client.set_connection_guard(self._ensure_tunnel)
        self._renderer = ConsoleRenderer(config.streaming)
        self._tools = build_tool_registry(config)
        self._executor = GraphAgent(config, self._client, self._tools, self._renderer)
        self._task_store = TaskStore(config)
        self._planner = TaskPlanner(config, self._client)
        self._kernel = AgentKernel(
            config,
            task_store=self._task_store,
            client=self._client,
            planner=self._planner,
            base_tools=self._tools,
            renderer=self._renderer,
        )
        self._agent = TaskAgent(
            config,
            self._executor,
            self._planner,
            self._task_store,
            self._renderer,
            self._kernel,
        )

    def _ensure_tunnel(self, *, force_reconnect: bool = False) -> None:
        if self._config.ssh is None:
            return
        if self._tunnel is None:
            try:
                from tunnel import SshTunnel, TunnelConfig
            except ModuleNotFoundError as exc:
                missing = str(getattr(exc, "name", "") or "").strip() or "unknown dependency"
                raise RuntimeError(
                    "SSH 隧道依赖缺失，无法启用远程模型转发。"
                    f" 缺少模块: {missing}。"
                    " 如果当前不需要 SSH，请清空 SSH 配置；"
                    " 如果需要 SSH，请安装 requirements.txt 中的依赖。"
                ) from exc
            self._tunnel = SshTunnel(
                TunnelConfig(
                    ssh_host=self._config.ssh.ssh_host,
                    ssh_port=self._config.ssh.ssh_port,
                    ssh_user=self._config.ssh.ssh_user,
                    ssh_password=self._config.ssh.ssh_password,
                    remote_host=self._config.ssh.remote_host,
                    remote_port=self._config.ssh.remote_port,
                    local_host=self._config.ssh.local_host,
                    local_port=self._config.ssh.local_port,
                )
            )
        self._tunnel.ensure_started(force_reconnect=force_reconnect)

    def start(self) -> None:
        self._ensure_tunnel()

    def close(self) -> None:
        if self._tunnel is not None:
            self._tunnel.close()
            self._tunnel = None
        self._client.close()

    def invoke(
        self,
        user_input: str,
        *,
        image_paths: list[str] | None = None,
        image_urls: list[str] | None = None,
    ) -> str:
        return self._agent.handle_input(
            user_input,
            image_paths=image_paths,
            image_urls=image_urls,
        )

    def __enter__(self) -> "AgentApplication":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
