"""ES-DE 标准 XML 构建模块：读取、增量更新、写入 gamelist.xml"""

import xml.etree.ElementTree as ET
from pathlib import Path


def load_existing_gamelist(gamelist_path: Path) -> tuple[ET.Element, dict[str, ET.Element]]:
    """读取已有 gamelist.xml。返回 (tree_root, {rom_relative_path: game_element})。"""
    index: dict[str, ET.Element] = {}

    if not gamelist_path.exists():
        root = ET.Element("gameList")
        return root, index

    try:
        tree = ET.parse(gamelist_path)
        root = tree.getroot()
    except ET.ParseError:
        print(f"  [警告] gamelist.xml 解析失败，将创建新文件")
        root = ET.Element("gameList")
        return root, index

    for game_elem in root.findall("game"):
        path_elem = game_elem.find("path")
        if path_elem is not None and path_elem.text:
            index[path_elem.text.strip()] = game_elem

    return root, index


def build_game_element(rom_rel_path: str, metadata: dict) -> ET.Element:
    """根据元数据字典构建 <game> 元素。

    metadata 应包含:
        name, desc, image, marquee, developer, publisher,
        genre, players, release_date, rating
    所有值均为字符串，缺失值为空字符串。
    """
    game = ET.Element("game")

    _add_text(game, "path", rom_rel_path)
    _add_text(game, "name", metadata.get("name", ""))
    _add_text(game, "desc", metadata.get("desc", ""))
    _add_text(game, "image", metadata.get("image", ""))
    _add_text(game, "marquee", metadata.get("marquee", ""))
    _add_text(game, "developer", metadata.get("developer", ""))
    _add_text(game, "publisher", metadata.get("publisher", ""))
    _add_text(game, "genre", metadata.get("genre", ""))
    _add_text(game, "players", metadata.get("players", ""))
    _add_text(game, "rating", metadata.get("rating", ""))

    # 日期格式化
    raw_date = metadata.get("release_date", "")
    formatted = _format_es_date(raw_date)
    _add_text(game, "releasedate", formatted)

    return game


def _add_text(parent: ET.Element, tag: str, text: str) -> None:
    """仅在 text 非空时添加子元素。"""
    if text:
        elem = ET.SubElement(parent, tag)
        elem.text = text


def _format_es_date(raw: str) -> str:
    """将 SS 返回的日期字符串转为 ES 标准格式 YYYYMMDDTHHMMSS。

    SS 常见格式: "1995-03-11", "1995", "19950311T000000"
    """
    if not raw:
        return ""
    # 已经是标准格式
    if "T" in raw and len(raw) >= 8:
        return raw
    # YYYY-MM-DD
    parts = raw.strip().split("-")
    if len(parts) == 3:
        return f"{parts[0]}{parts[1].zfill(2)}{parts[2].zfill(2)}T000000"
    if len(parts) == 1 and len(parts[0]) == 4:
        return f"{parts[0]}0101T000000"
    return raw


def write_gamelist(gamelist_path: Path, root: ET.Element) -> None:
    """将 XML 树写入 gamelist.xml，带缩进格式化。"""
    _indent_xml(root)
    tree = ET.ElementTree(root)
    tree.write(
        gamelist_path,
        encoding="utf-8",
        xml_declaration=True,
    )
    # ET 默认用单引号写 xml_declaration，手动修正
    _fix_declaration(gamelist_path)


def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    """递归缩进 XML 元素。"""
    indent = "\n" + " " * (level + 4)
    child_count = len(elem)
    if child_count:
        if not elem.text or not elem.text.strip():
            elem.text = indent
        for i, child in enumerate(elem):
            _indent_xml(child, level + 4)
            if i == child_count - 1:
                child.tail = "\n" + " " * level
            else:
                child.tail = indent
        elem.tail = "\n" + " " * level if level > 0 else "\n"


def _fix_declaration(path: Path) -> None:
    """将 xml_declaration 中的单引号改为双引号。"""
    content = path.read_text(encoding="utf-8")
    if content.startswith("<?xml version='1.0' encoding='utf-8'?>"):
        content = content.replace(
            "<?xml version='1.0' encoding='utf-8'?>",
            '<?xml version="1.0" encoding="UTF-8"?>',
            1,
        )
        path.write_text(content, encoding="utf-8")
