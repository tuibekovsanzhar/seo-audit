"""A finished audit's own result, kept so a later step can use it without asking the website for anything again.

Reading a blocked site through Firecrawl after the audit has finished (the person switched it on afterwards,
accepted storage, or approved a stronger proxy) needs what Maya's crawl found: its pages, robots.txt rules and
check results. Those live in memory while an audit runs. This file keeps them, so the continuation sends requests
to Firecrawl only and none to the site.

The file is Python's pickle format, read back through an allow-list: only the engine's own data classes and
enumerations and a few plain standard types can be rebuilt from it. A function, a module or any other class named
in the file is refused, so a file planted in the folder cannot run anything. A file that does not load is treated
as absent, and the audit falls back to repeating its last steps.
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
import io
import os
import pickle
from pathlib import Path
from typing import Any

NAME = "outcome.snapshot"
VERSION = 1
MAX_BYTES = 400 * 1024 * 1024

_PLAIN = {("builtins", "set"), ("builtins", "frozenset"), ("builtins", "bytearray"), ("builtins", "complex"),
          ("collections", "OrderedDict"), ("collections", "Counter"), ("collections", "defaultdict"), ("collections", "deque"),
          ("datetime", "datetime"), ("datetime", "date"), ("datetime", "timedelta"), ("datetime", "timezone"),
          ("pathlib", "PosixPath"), ("pathlib", "PurePosixPath"), ("pathlib", "Path"),
          ("pathlib", "WindowsPath"), ("pathlib", "PureWindowsPath"),  # a snapshot saved on Windows (D-24)
          ("builtins", "list"), ("builtins", "dict"), ("builtins", "tuple"), ("builtins", "str"), ("builtins", "int"),
          ("builtins", "float"), ("builtins", "bool"), ("builtins", "bytes")}


class Refused(pickle.UnpicklingError):
    pass


def _enum_member(cls: Any, name: str) -> Any:
    """What Python 3.11 pickles an enum member as: getattr(EnumClass, "MEMBER"). Only a member of an enum class the
    allowlist already let through is returned; getattr itself is never handed to the unpickler."""
    if isinstance(cls, type) and issubclass(cls, enum.Enum) and name in cls.__members__:
        return cls.__members__[name]
    raise Refused(f"getattr({cls!r}, {name!r}) is not an enum member")


class _OnlyData(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        # Python 3.13 pickles pathlib classes under its private implementation
        # module; resolve only the same public data types already allowlisted.
        if module == "pathlib._local" and ("pathlib", name) in _PLAIN:
            return getattr(importlib.import_module("pathlib"), name)
        if (module, name) == ("builtins", "getattr"):
            return _enum_member
        if (module, name) in _PLAIN:
            return getattr(importlib.import_module(module), name)
        if module == "maya_audit" or module.startswith("maya_audit."):
            found: Any = importlib.import_module(module)
            for part in name.split("."):
                found = getattr(found, part)
            # Data only: a class that holds fields, or a set of named values. Never a function.
            if isinstance(found, type) and (dataclasses.is_dataclass(found) or issubclass(found, enum.Enum)):
                return found
        raise Refused(f"{module}.{name} is not data")


def save(folder: Path, outcome: Any, config: Any) -> bool:
    """Keep the audit's result. False when it cannot be kept; the audit itself is never failed for this."""
    path = folder / NAME
    try:
        data = pickle.dumps({"version": VERSION, "outcome": outcome, "config": config}, protocol=4)
        if len(data) > MAX_BYTES:
            raise ValueError("too large")
        _OnlyData(io.BytesIO(data)).load()  # only keep what can be read back
        temporary = path.with_suffix(".tmp")
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temporary, path)
        return True
    except Exception:  # noqa: BLE001  anything unpicklable in a result means "no snapshot", nothing more
        remove(folder)
        return False


def load(folder: Path) -> tuple[Any, Any] | None:
    """The saved result and its settings, or None when there is none that can be trusted and read."""
    path = folder / NAME
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        with open(path, "rb") as source:
            kept = _OnlyData(source).load()
        if not isinstance(kept, dict) or kept.get("version") != VERSION:
            return None
        return kept["outcome"], kept["config"]
    except Exception:  # noqa: BLE001
        return None


def exists(folder: Path) -> bool:
    path = folder / NAME
    return path.is_file() and not path.is_symlink()


def remove(folder: Path) -> None:
    for name in (NAME, Path(NAME).with_suffix(".tmp").name):
        try:
            (folder / name).unlink()
        except OSError:
            pass
