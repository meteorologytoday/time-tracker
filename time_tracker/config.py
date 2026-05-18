import json
from pathlib import Path

_CONFIG_DIR = Path.home() / ".time_tracker"
_CONFIG_PATH = _CONFIG_DIR / "config.json"
_DEFAULT_DB_PATH = _CONFIG_DIR / "time_tracker.db"


def _load() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


def _save(cfg: dict):
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def get_db_path() -> Path:
    return Path(_load().get("db_path", str(_DEFAULT_DB_PATH)))


def set_db_path(path: Path):
    cfg = _load()
    cfg["db_path"] = str(path)
    _save(cfg)
