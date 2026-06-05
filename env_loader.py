"""Small local .env loader for project secrets.

This keeps API keys out of source files while still allowing PyCharm, scripts,
and the realtime app to share the same local environment file.
"""

import os


def load_project_env():
    """Load KEY=VALUE lines from .env next to this file.

    Existing OS/PyCharm environment variables are not overwritten.
    """
    env_path = os.path.join(os.path.dirname(__file__), ".env")

    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8-sig") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()

                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip().lstrip("\ufeff")
                value = value.strip().strip('"').strip("'")

                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        return
