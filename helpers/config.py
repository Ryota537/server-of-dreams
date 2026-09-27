from pathlib import Path

import yaml
from pydantic import BaseModel

_loaded = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "config.yml").read_text(encoding="utf-8")
)
config: dict = _loaded if isinstance(_loaded, dict) else {}

# every key the app reads from config -- there are no defaults, so all must be present.
_REQUIRED = {
    "host",
    "port",
    "api_endpoint",
    "server_version",
    "asset_version",
    "master_data_publish_timestamp",
    "feature_maintenance_flags",
    "maintenance",
    "maintenance_message",
    "local_assets",
    "stamina_recovery_seconds",
    "master_data_url",
    "static_content_url",
    "asset_url",
    "photo_content_url",
    "multi_real_time_server_url",
    "external_payment_url",
    "database",
    "jwt_secret",
}
_missing = _REQUIRED - set(config)
if _missing:
    raise RuntimeError(f"config.yml is missing required keys: {sorted(_missing)}")


class DatabaseSettings(BaseModel):
    min_size: int = 3
    max_size: int = 20


class Database(BaseModel):
    host: str
    port: int
    database: str
    username: str
    password: str
    settings: DatabaseSettings = DatabaseSettings()


class RealtimeSettings(BaseModel):
    """The realtime StreamingHub listener (see ``realtime/``).

    Optional as a whole: absent means the channel runs only when started
    explicitly by ``realtime_main.py``. TLS needs both certfile and keyfile.
    """

    host: str = "0.0.0.0"
    port: int = 8443
    certfile: str = ""
    keyfile: str = ""
    auto_start: bool = False


database: Database = Database(**config["database"])
realtime: RealtimeSettings = RealtimeSettings(**(config.get("realtime") or {}))
