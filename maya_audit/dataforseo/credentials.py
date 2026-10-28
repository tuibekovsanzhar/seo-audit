"""DataForSEO credentials: read from the environment, never from the command line, never printed."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

LOGIN_VAR = "MAYA_AUDIT_DATAFORSEO_LOGIN"
PASSWORD_VAR = "MAYA_AUDIT_DATAFORSEO_PASSWORD"
ENV_FILE_VAR = "MAYA_AUDIT_ENV_FILE"  # where the .env file is, when it is not ./.env
REDACTED = "[redacted]"


@dataclass(frozen=True, repr=False)
class Credentials:
    login: str
    password: str

    def __repr__(self) -> str:  # a stray print() or traceback must not show the values
        return "Credentials(login=[redacted], password=[redacted])"

    def authorization(self) -> str:
        return "Basic " + base64.b64encode(f"{self.login}:{self.password}".encode()).decode()

    def _secrets(self) -> list[str]:
        forms = [self.authorization().removeprefix("Basic "), self.password, self.login]
        forms += [base64.b64encode(value.encode()).decode() for value in (self.password, self.login)]
        # Longest first, so a secret that contains another is replaced whole.
        return sorted({s for s in forms if len(s) >= 3}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        """`text` with the login, the password and their base64 forms replaced."""
        for secret in self._secrets():
            text = text.replace(secret, REDACTED)
        return text

    def redact_json(self, value: Any) -> Any:
        return json.loads(self.redact(json.dumps(value, ensure_ascii=False)))


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines from a .env file. Only MAYA_AUDIT_* names are read; nothing is exported."""
    values: dict[str, str] = {}
    try:
        # utf-8-sig: Notepad saves a byte-order mark, which would glue onto the first key and drop it silently.
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return values
    except UnicodeDecodeError as exc:
        # PowerShell 5's Out-File writes UTF-16; say so instead of failing somewhere a key is first needed.
        raise ValueError(f"{path.name} is not UTF-8 text (saved as UTF-16?); save it as UTF-8 and try again") from exc
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key.startswith("MAYA_AUDIT_"):
            values[key] = value
    return values


def load_credentials(environ: Mapping[str, str] | None = None) -> Credentials | None:
    """Credentials from environment variables, falling back to the .env file. None when either is missing.

    A real environment variable wins over the file. The file is ./.env unless MAYA_AUDIT_ENV_FILE
    names another one.
    """
    environ = os.environ if environ is None else environ
    from_file = read_env_file(Path(environ.get(ENV_FILE_VAR) or ".env"))
    login = environ.get(LOGIN_VAR) or from_file.get(LOGIN_VAR)
    password = environ.get(PASSWORD_VAR) or from_file.get(PASSWORD_VAR)
    return Credentials(login, password) if login and password else None


def data_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Where the ledger and the cache live: outside the repository, private to the user."""
    environ = os.environ if environ is None else environ
    path = Path(environ.get("MAYA_AUDIT_HOME") or Path.home() / ".maya-audit")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path
