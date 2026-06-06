"""动态配置模块：加载和验证 config.json"""

import json
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

REQUIRED_LLM_FIELDS = ["base_url", "api_key", "model_name"]
REQUIRED_SS_FIELDS = ["devid", "devpassword", "softname"]
REQUIRED_PATH_FIELDS = ["roms_directory"]


def load_config(config_path: str | None = None) -> dict:
    """加载配置文件，失败时抛出明确异常。"""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {path}\n"
            f"请复制 config.json 并填入你的 API 密钥和路径。"
        )

    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)

    _validate(config)
    _expand_paths(config, path.parent)
    return config


def _validate(config: dict) -> None:
    """校验必填字段。"""
    llm = config.get("llm_config", {})
    ss = config.get("ss_config", {})
    paths = config.get("path_config", {})

    for field in REQUIRED_LLM_FIELDS:
        if not llm.get(field):
            raise ValueError(f"llm_config.{field} 为必填项")

    for field in REQUIRED_SS_FIELDS:
        if not ss.get(field):
            raise ValueError(f"ss_config.{field} 为必填项")

    for field in REQUIRED_PATH_FIELDS:
        if not paths.get(field):
            raise ValueError(f"path_config.{field} 为必填项")

    roms_dir = Path(paths["roms_directory"])
    if not roms_dir.is_absolute():
        raise ValueError(
            "path_config.roms_directory 必须为绝对路径，例如 /sdcard/ROMs/GBA"
        )
    if not roms_dir.exists():
        raise FileNotFoundError(f"ROM 目录不存在: {roms_dir}")


def _expand_paths(config: dict, config_dir: Path) -> None:
    """将 roms_directory 转为 Path 对象，方便后续使用。"""
    config["path_config"]["roms_path"] = Path(config["path_config"]["roms_directory"])
    config["path_config"]["media_path"] = (
        config["path_config"]["roms_path"]
        / config["path_config"].get("media_dir", "downloaded_media")
    )
    config["path_config"]["covers_path"] = (
        config["path_config"]["media_path"]
        / config["path_config"].get("covers_dir", "covers")
    )
    config["path_config"]["marquees_path"] = (
        config["path_config"]["media_path"]
        / config["path_config"].get("marquees_dir", "marquees")
    )
