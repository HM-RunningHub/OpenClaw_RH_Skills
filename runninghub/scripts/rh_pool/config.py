"""Configuration loading for the RunningHub workflow task pool.

Resolution order:
  1. RH_POOL_CONFIG env var -> explicit config JSON path
  2. <skill_dir>/config/skill-config.json
  3. Built-in defaults

The API key is NOT handled here; it is resolved by the existing runninghub
script helpers (env / secret / agent profile).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


# scripts/rh_pool/config.py -> scripts -> runninghub (skill dir)
SKILL_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = SKILL_DIR / "config"


@dataclass
class PoolConfig:
    concurrency: int = 3
    dataDir: Path = field(default_factory=lambda: SKILL_DIR / "data" / "pool")
    outputDir: Path | None = None              # defaults to <dataDir>/output
    defaultInstanceType: str = "default"
    pollIntervalSeconds: int = 30              # polling automation cadence
    sessionKey: str = "agent:main:main"        # default wake-back target

    @property
    def db_path(self) -> Path:
        return self.dataDir / "pool.sqlite"

    @property
    def output_root(self) -> Path:
        return self.outputDir or (self.dataDir / "output")


def _config_path() -> Path | None:
    env_path = os.environ.get("RH_POOL_CONFIG")
    if env_path:
        p = Path(env_path)
        return p if p.exists() else None
    p = CONFIG_DIR / "skill-config.json"
    return p if p.exists() else None


def load_config() -> PoolConfig:
    cfg = PoolConfig()
    path = _config_path()
    raw: dict = {}
    if path:
        raw = json.loads(path.read_text(encoding="utf-8"))

    if "concurrency" in raw:
        cfg.concurrency = max(1, int(raw["concurrency"]))
    if "defaultInstanceType" in raw:
        cfg.defaultInstanceType = str(raw["defaultInstanceType"])
    if "pollIntervalSeconds" in raw:
        cfg.pollIntervalSeconds = max(5, int(raw["pollIntervalSeconds"]))
    if "sessionKey" in raw:
        cfg.sessionKey = str(raw["sessionKey"])
    # Explicit env override for data dir is handy in dev / tests.
    data_dir = os.environ.get("RH_POOL_DATA_DIR") or raw.get("dataDir")
    if data_dir:
        p = Path(str(data_dir)).expanduser()
        # Relative paths resolve inside the skill folder (self-contained skill).
        cfg.dataDir = p if p.is_absolute() else SKILL_DIR / p
    out_dir = raw.get("outputDir")
    if out_dir:
        p = Path(str(out_dir)).expanduser()
        cfg.outputDir = p if p.is_absolute() else SKILL_DIR / p
    return cfg
