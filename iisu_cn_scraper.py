#!/usr/bin/env python3
"""iiSU-CN-Scraper — 中文 ROM 刮削旁路补丁

读取乱码 ROM 文件名 → LLM 语义清洗 → ScreenScraper 获取中文资料 → 生成 gamelist.xml

用法:
    python iisu_cn_scraper.py                     # 使用默认 config.json
    python iisu_cn_scraper.py --config my.json    # 指定配置文件
    python iisu_cn_scraper.py --dry-run           # 仅分析不写入
"""

import argparse
import os
import sys
from pathlib import Path

# 确保项目根目录在 Python path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI

from modules.config_loader import load_config
from modules.llm_normalizer import normalize_batch
from modules.ss_fetcher import ScreenScraperFetcher
from modules.xml_builder import (
    load_existing_gamelist,
    build_game_element,
    write_gamelist,
)

# ROM 扩展名（大小写不敏感）
ROM_EXTENSIONS = {
    ".gba", ".gbc", ".gb", ".nds", ".3ds", ".n64", ".z64", ".v64",
    ".nes", ".fds", ".sfc", ".smc", ".smd", ".md", ".gen", ".32x",
    ".gg", ".sms", ".pce", ".cue", ".bin", ".iso", ".cso", ".chd",
    ".pbp", ".wbfs", ".wad", ".dol", ".nsp", ".xci", ".nsz",
    ".prg", ".d64", ".t64", ".tap", ".atr", ".xex",
    ".ps1", ".ps2", ".psp", ".dc", ".ngc", ".wii", ".wiiu",
    ".zip", ".7z",
}


def find_roms(roms_dir: Path) -> list[Path]:
    """遍历 ROM 目录，返回 ROM 文件列表。"""
    roms = []
    for entry in roms_dir.iterdir():
        if entry.is_file() and entry.suffix.lower() in ROM_EXTENSIONS:
            roms.append(entry)
    return sorted(roms, key=lambda p: p.name.lower())


def make_rom_relative(rom_path: Path, roms_dir: Path) -> str:
    """生成相对于 ROM 根目录的路径字符串，如 './game.gba'。"""
    return "./" + str(rom_path.relative_to(roms_dir)).replace("\\", "/")


def make_media_relative(media_path: Path, roms_dir: Path) -> str:
    """生成相对于 ROM 根目录的媒体路径，如 './downloaded_media/covers/game.png'。"""
    try:
        rel = media_path.relative_to(roms_dir)
    except ValueError:
        return str(media_path)
    return "./" + str(rel).replace("\\", "/")


def slugify(name: str) -> str:
    """将名称转为安全文件名。"""
    keepchars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-"
    safe = "".join(c if c in keepchars else "_" for c in name)
    return safe.strip()[:80]


def main():
    parser = argparse.ArgumentParser(
        description="iiSU-CN-Scraper — 中文 ROM 刮削旁路补丁"
    )
    parser.add_argument(
        "--config", "-c", default=None,
        help="配置文件路径 (默认: ./config.json)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅分析不写入 (不调用 SS 下载，不写 gamelist.xml)"
    )
    args = parser.parse_args()

    # 1. 加载配置
    print("=" * 60)
    print("iiSU-CN-Scraper v1.0")
    print("=" * 60)

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"\n[配置错误] {e}")
        sys.exit(1)

    llm_cfg = config["llm_config"]
    ss_cfg = config["ss_config"]
    path_cfg = config["path_config"]
    options = config.get("scrape_options", {})

    roms_dir = path_cfg["roms_path"]
    covers_dir = path_cfg["covers_path"]
    marquees_dir = path_cfg["marquees_path"]
    gamelist_path = roms_dir / "gamelist.xml"

    print(f"\nROM 目录: {roms_dir}")
    print(f"媒体目录: {path_cfg['media_path']}")
    print(f"LLM 模型: {llm_cfg['model_name']}")

    # 2. 扫描 ROM 文件
    roms = find_roms(roms_dir)
    print(f"\n扫描到 {len(roms)} 个 ROM 文件")

    if not roms:
        print("未找到 ROM 文件，请检查 path_config.roms_directory 和扩展名列表")
        sys.exit(0)

    # 3. 加载已有 gamelist.xml，跳过已刮削的 ROM
    root, existing_index = load_existing_gamelist(gamelist_path)
    skip_existing = options.get("skip_existing", True)

    pending_roms = []
    skipped = 0
    for rom in roms:
        rel = make_rom_relative(rom, roms_dir)
        if skip_existing and rel in existing_index:
            skipped += 1
        else:
            pending_roms.append(rom)

    if skipped:
        print(f"  [跳过] {skipped} 个已刮削 (gamelist.xml 中已有记录)")
    if not pending_roms:
        print("所有 ROM 均已刮削，无需操作")
        sys.exit(0)
    print(f"  [待处理] {len(pending_roms)} 个 ROM\n")

    # 4. LLM 语义清洗
    print("-" * 60)
    print("阶段 1/3: AI 语义清洗")
    print("-" * 60)

    client = OpenAI(
        base_url=llm_cfg["base_url"],
        api_key=llm_cfg["api_key"],
    )

    pending_filenames = [r.name for r in pending_roms]
    llm_results = normalize_batch(
        client,
        llm_cfg["model_name"],
        pending_filenames,
        llm_cfg.get("temperature", 0.1),
        llm_cfg.get("max_tokens", 200),
    )

    # 5. ScreenScraper 刮削
    print(f"\n" + "-" * 60)
    print("阶段 2/3: ScreenScraper 刮削")
    print("-" * 60)

    fetcher = ScreenScraperFetcher(
        devid=ss_cfg["devid"],
        devpassword=ss_cfg["devpassword"],
        softname=ss_cfg["softname"],
        base_url=ss_cfg.get("base_url", "https://api.screenscraper.fr/api2"),
        request_delay=ss_cfg.get("request_delay", 1.5),
    )

    for i, rom in enumerate(pending_roms, 1):
        fname = rom.name
        llm = llm_results.get(fname, {"standard_zh": "", "standard_en": ""})
        name_zh = llm["standard_zh"]
        name_en = llm["standard_en"]

        print(f"\n{'─' * 50}")
        print(f"[{i}/{len(pending_roms)}] {fname[:70]}")
        print(f"  标准中文名: {name_zh or '(无)'}")
        print(f"  标准英文名: {name_en or '(无)'}")

        if args.dry_run:
            print("  [DRY-RUN] 跳过 SS 刮削")
            continue

        # 搜索 SS
        if not name_zh and not name_en:
            print("  [跳过] LLM 未能提取任何有效名称")
            continue

        metadata = fetcher.search_game(name_zh, name_en)
        if not metadata:
            print("  [未找到] ScreenScraper 无匹配结果")
            continue

        print(f"  SS 匹配: {metadata.get('name_en') or metadata.get('name_zh', '未知')}")

        # 构建媒体文件名（基于 ROM 文件名，不含扩展名）
        rom_stem = rom.stem
        safe_stem = slugify(rom_stem)

        # 下载封面
        cover_path = covers_dir / f"{safe_stem}-image.png"
        if options.get("download_covers", True):
            if fetcher.download_cover(metadata["media_urls"], cover_path):
                print(f"  [封面] 已下载")
            else:
                print(f"  [封面] 无可用资源")
                cover_path = Path("")  # 置空

        # 下载 Logo
        marquee_path = marquees_dir / f"{safe_stem}-marquee.png"
        if options.get("download_marquees", True):
            if fetcher.download_marquee(metadata["media_urls"], marquee_path):
                print(f"  [Logo] 已下载")
            else:
                print(f"  [Logo] 无可用资源")
                marquee_path = Path("")  # 置空

        # 组装 gamelist 条目
        rel_path = make_rom_relative(rom, roms_dir)
        entry = {
            "name": metadata.get("name_zh") or metadata.get("name_en", rom_stem),
            "desc": metadata.get("desc", ""),
            "image": make_media_relative(cover_path, roms_dir) if str(cover_path) else "",
            "marquee": make_media_relative(marquee_path, roms_dir) if str(marquee_path) else "",
            "developer": metadata.get("developer", ""),
            "publisher": metadata.get("publisher", ""),
            "genre": metadata.get("genre", ""),
            "players": metadata.get("players", ""),
            "release_date": metadata.get("release_date", ""),
            "rating": "",
        }

        # 增量写入 gamelist.xml
        game_elem = build_game_element(rel_path, entry)
        if rel_path in existing_index:
            old = existing_index[rel_path]
            root.remove(old)
        root.append(game_elem)
        existing_index[rel_path] = game_elem

        # 每次刮削成功就写入，防止中断丢数据
        write_gamelist(gamelist_path, root)
        print(f"  [XML] 已写入 gamelist.xml")

    # 6. 最后写入
    write_gamelist(gamelist_path, root)
    print(f"\n{'=' * 60}")
    print(f"完成! gamelist.xml → {gamelist_path}")
    print(f"媒体文件 → {path_cfg['media_path']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
