import os

from .settings import Settings

_env = os.getenv("ENV", "dev")
_env_files = {"dev": ".env", "test": ".env.test", "pro": ".env.prod"}

settings = Settings(_env_file=_env_files.get(_env, ".env"))

__all__ = ["settings"]
