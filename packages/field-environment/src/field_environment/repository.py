from __future__ import annotations

from pathlib import Path


def find_repository_root(start: str | Path | None = None) -> Path:
    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "AGENTS.md").is_file() and (candidate / "cases").is_dir():
            return candidate
    raise FileNotFoundError("repository root containing AGENTS.md and cases/ was not found")


def resolve_repository_path(path: str | Path, *, start: str | Path | None = None) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (find_repository_root(start) / candidate).resolve()
