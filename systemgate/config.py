from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    admin_key: str
    backup_root: Path


def _value(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class ConfigError(ValueError):
    pass


def _port(name: str, default: str) -> int:
    raw = _value(name, default)
    try:
        port = int(raw)
    except ValueError:
        raise ConfigError(f"invalid {name}: {raw!r} (expected integer 1-65535)") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"{name} out of range: {port} (expected 1-65535)")
    return port


def get_settings() -> Settings:
    root = Path(__file__).resolve().parents[1]
    data_dir = Path(_value("SYSTEMGATE_DATA_DIR", str(root / "data"))).expanduser().resolve()
    backup_root = Path(_value("SYSTEMGATE_BACKUP_ROOT", "/backups")).expanduser().resolve()
    return Settings(
        host=_value("SYSTEMGATE_HOST", "127.0.0.1"),
        port=_port("SYSTEMGATE_PORT", "8040"),
        data_dir=data_dir,
        admin_key=_value("SYSTEMGATE_ADMIN_KEY"),
        backup_root=backup_root,
    )
