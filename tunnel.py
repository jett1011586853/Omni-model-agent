from __future__ import annotations

import logging
import select
import socket
import socketserver
import sys
import threading
from dataclasses import dataclass

import paramiko


_LOGGER = logging.getLogger(__name__)
logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)


@dataclass
class TunnelConfig:
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_password: str
    remote_host: str
    remote_port: int
    local_host: str
    local_port: int


class _ForwardHandler(socketserver.BaseRequestHandler):
    transport: paramiko.Transport
    remote_host: str
    remote_port: int

    def handle(self) -> None:
        try:
            channel = self.transport.open_channel(
                "direct-tcpip",
                (self.remote_host, self.remote_port),
                self.request.getpeername(),
            )
        except (OSError, EOFError, paramiko.SSHException):
            return
        try:
            while True:
                read_ready, _, _ = select.select([self.request, channel], [], [])
                if self.request in read_ready:
                    data = self.request.recv(1024)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in read_ready:
                    data = channel.recv(1024)
                    if not data:
                        break
                    self.request.sendall(data)
        except (OSError, EOFError, paramiko.SSHException):
            return
        finally:
            try:
                channel.close()
            except (OSError, EOFError, paramiko.SSHException):
                pass
            try:
                self.request.close()
            except OSError:
                pass


class _ForwardServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        exc_type, exc, _tb = sys.exc_info()
        if isinstance(exc, (OSError, EOFError, paramiko.SSHException)):
            return
        if exc_type is not None:
            _LOGGER.debug(
                "Unhandled tunnel forwarding error from %s",
                client_address,
                exc_info=True,
            )


class SshTunnel:
    def __init__(self, config: TunnelConfig) -> None:
        self.config = config
        self._client: paramiko.SSHClient | None = None
        self._server: _ForwardServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def _transport_is_active(self) -> bool:
        if self._client is None:
            return False
        transport = self._client.get_transport()
        return bool(transport is not None and transport.is_active())

    def is_active(self) -> bool:
        return bool(
            self._server is not None
            and self._thread is not None
            and self._thread.is_alive()
            and self._transport_is_active()
        )

    def _start_unlocked(self) -> None:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.config.ssh_host,
            port=self.config.ssh_port,
            username=self.config.ssh_user,
            password=self.config.ssh_password,
            timeout=20,
        )
        transport = client.get_transport()
        if transport is None:
            client.close()
            raise RuntimeError("SSH transport was not initialized")

        handler = type(
            "ForwardHandler",
            (_ForwardHandler,),
            {
                "transport": transport,
                "remote_host": self.config.remote_host,
                "remote_port": self.config.remote_port,
            },
        )

        server = _ForwardServer(
            (self.config.local_host, self.config.local_port),
            handler,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        self._client = client
        self._server = server
        self._thread = thread

    def _close_unlocked(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._client is not None:
            self._client.close()
            self._client = None
        self._thread = None

    def ensure_started(self, *, force_reconnect: bool = False) -> None:
        with self._lock:
            if not force_reconnect and self.is_active():
                return
            self._close_unlocked()
            self._start_unlocked()

    def start(self) -> None:
        self.ensure_started()

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def __enter__(self) -> "SshTunnel":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
