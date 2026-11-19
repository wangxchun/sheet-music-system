"""Local settings and secrets.

Secrets never live in the code or in git:
  .env                              API keys (copy .env.example and fill it in)
  secrets/google_oauth_client.json  Google OAuth client, downloaded from Google Cloud
  secrets/google_token.json         created on first Google sign-in

Both .env and secrets/ are listed in .gitignore.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
SECRETS_DIR = ROOT / "secrets"


def parse_env(text: str) -> Dict[str, str]:
    """Parse KEY=VALUE lines; blank lines and # comments are ignored."""
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_env(path: Path = ENV_FILE) -> None:
    """Copy .env values into os.environ without overriding variables already set."""
    if not path.exists():
        return
    for key, value in parse_env(path.read_text(encoding="utf-8")).items():
        if value:
            os.environ.setdefault(key, value)


def secret_path(env_var: str, default_name: str) -> Path:
    """A secret file's path: from the environment if set, else under secrets/."""
    custom = os.environ.get(env_var)
    return Path(custom).expanduser() if custom else SECRETS_DIR / default_name
