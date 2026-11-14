from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import EnvironmentConfig, load_environment_config


@dataclass(frozen=True)
class AuthoredEnvironmentConfig:
    directory: Path
    config_path: Path
    config: EnvironmentConfig


def author_environment_config(
    output_root: str | Path,
    config: EnvironmentConfig,
    *,
    version: str = "v1",
    overwrite: bool = True,
) -> AuthoredEnvironmentConfig:
    """Pythonで確定したCase生成条件を再現用YAMLとして保存する。"""
    normalized_version = version.strip()
    if not normalized_version:
        raise ValueError("version must not be empty")
    if Path(normalized_version).name != normalized_version:
        raise ValueError("version must be a single path component")

    directory = Path(output_root) / "environments" / config.case_id / normalized_version
    config_path = directory / "environment.yaml"
    if config_path.exists() and not overwrite:
        raise FileExistsError(f"generated environment config already exists: {config_path}")

    payload = config.model_dump(mode="json", exclude_none=True)
    generated_yaml = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    directory.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "# 00_environment_python.ipynbから自動生成した再現用設定である。\n"
        "# 通常は直接編集せず，NotebookのPython設定を変更して再生成する。\n"
        + generated_yaml,
        encoding="utf-8",
    )

    loaded_config, _ = load_environment_config(config_path, start=directory)
    if loaded_config != config:
        raise ValueError("generated environment config did not round-trip")
    return AuthoredEnvironmentConfig(
        directory=directory,
        config_path=config_path,
        config=loaded_config,
    )
