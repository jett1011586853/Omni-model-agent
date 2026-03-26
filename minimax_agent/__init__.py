from .config import AppConfig, load_app_config

__all__ = ["AgentApplication", "AppConfig", "load_app_config"]


def __getattr__(name: str):
    if name == "AgentApplication":
        from .app import AgentApplication

        return AgentApplication
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
