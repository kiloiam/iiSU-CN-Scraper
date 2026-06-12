#!/usr/bin/env python3
"""iiSU-CN-Scraper — Android APK (Flet / Flutter)

Material Design 3 暗色主题，圆形扫描按钮，设置页，刮削页。
"""

import json, os, subprocess, sys, threading, time
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flet as ft

from openai import OpenAI
from modules.llm_normalizer import normalize_rom_name
from modules.bangumi_fetcher import BangumiFetcher
from modules.tgdb_fetcher import TGDBFetcher
from modules.llm_normalizer import translate_desc
from modules.xml_builder import (
    load_existing_gamelist, build_game_element, write_gamelist,
)

# ======================================================================
# iiSU 配色 — 暗底蓝紫
# ======================================================================
BG         = "#0b0b16"
SURFACE    = "#151527"
CARD_BG    = "#1c1c32"
ACCENT     = "#8b5cf6"
ACCENT2    = "#6366f1"
TEXT       = "#e4e4ee"
TEXT_DIM   = "#9292a8"

# ======================================================================
# ROM 检测
# ======================================================================
ROM_ROOTS = [
    # 通用 ROM 目录
    "/storage/emulated/0/ROMs", "/storage/emulated/0/roms",
    "/sdcard/ROMs", "/sdcard/roms",
    "/storage/emulated/0/Emulation/roms",
    "/storage/emulated/0/Games",
    # 下载目录 (有人直接放这里)
    "/storage/emulated/0/Download",
    # 外置 SD 卡
    "/storage/0000-0000/ROMs", "/storage/0000-0000/roms",
    # AYN 设备
    "/storage/emulated/0/RetroArch/roms",
]
ROM_EXTS = {
    ".gba", ".gbc", ".gb", ".nds", ".3ds", ".n64", ".z64", ".v64",
    ".nes", ".fds", ".sfc", ".smc", ".smd", ".md", ".gen", ".32x",
    ".gg", ".sms", ".pce", ".cue", ".bin", ".iso", ".cso", ".chd",
    ".pbp", ".wbfs", ".wad", ".nsp", ".xci", ".nsz", ".zip", ".7z",
}
SYSTEMS = {
    "gba":"GBA","gbc":"GBC","gb":"GB","nds":"NDS","3ds":"3DS",
    "n64":"N64","nes":"NES","fds":"FC","sfc":"SFC","smc":"SFC",
    "md":"MD","gen":"MD","smd":"MD","32x":"32X","gg":"GG","sms":"SMS",
    "pce":"PCE","psp":"PSP","ps1":"PS1","ps2":"PS2","dc":"DC",
    "ngc":"NGC","wii":"Wii","wiiu":"WiiU","nsp":"Switch","xci":"Switch",
}

def _sys(dirname):
    low = dirname.lower().replace(" ","").replace("-","").replace("_","")
    for k,v in SYSTEMS.items():
        if k in low: return v
    return dirname[:12]

# 通用扫描时跳过的目录名（系统/应用/媒体目录）
SKIP_DIRS = {"Android", "DCIM", "Pictures", "Music", "Movies", "Download",
             "Documents", "Alarms", "Audiobooks", "Notifications", "Podcasts",
             "Ringtones", "LOST.DIR", "data", "obb", "cache", "temp",
             ".thumbnails", ".Trash", "Pendownload", "Tencent", "backups"}

ROM_SEARCH_ROOTS = [
    "/storage/emulated/0",
    "/sdcard",
]

def _open_all_files_access_settings():
    if sys.platform in ("win32", "darwin"):
        return False
    try:
        subprocess.run(
            ["am", "start", "-a", "android.settings.MANAGE_ALL_FILES_ACCESS_PERMISSION"],
            timeout=2,
            check=False,
        )
        return True
    except Exception:
        return False


def _normalize_android_path(path: str) -> str:
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        return ""
    if raw.startswith("file://"):
        raw = unquote(raw[7:])
    if raw.startswith("/tree/"):
        raw = raw[6:]
    if raw.startswith("primary:"):
        raw = "/storage/emulated/0/" + raw.split(":", 1)[1].lstrip("/")
    if ":" in raw and not raw.startswith("/"):
        volume, rest = raw.split(":", 1)
        raw = f"/storage/{volume}/{rest.lstrip('/')}"
    return os.path.normpath(raw)


def _iter_storage_roots() -> list:
    roots = ["/storage/emulated/0", "/sdcard"]
    storage = "/storage"
    try:
        for entry in sorted(os.listdir(storage)):
            if entry in {"self", "emulated"} or entry.startswith("."):
                continue
            full = os.path.join(storage, entry)
            if os.path.isdir(full):
                roots.append(full)
    except Exception:
        pass
    seen = set()
    unique = []
    for root in roots:
        real = os.path.realpath(root)
        if real not in seen and os.path.isdir(root):
            seen.add(real)
            unique.append(root)
    return unique


def _count_roms(path: str) -> int:
    """统计目录下 ROM 文件数量（仅一级，不递归）"""
    try:
        return sum(1 for f in os.listdir(path)
                   if os.path.isfile(os.path.join(path, f))
                   and f.lower().endswith(tuple(ROM_EXTS)))
    except: return 0

def _scan_parent(parent: str, depth: int = 2) -> list:
    """递归扫描目录树，寻找含 ROM 的目录，最大深度 depth"""
    results = []
    parent = _normalize_android_path(parent)
    if depth <= 0 or not os.path.isdir(parent):
        return results
    try:
        for entry in sorted(os.listdir(parent)):
            if entry in SKIP_DIRS or entry.startswith("."):
                continue
            full = os.path.join(parent, entry)
            if not os.path.isdir(full):
                continue
            n = _count_roms(full)
            if n >= 1:
                results.append((f"{_sys(entry)}  ({n} ROM)", full))
            elif depth > 1:
                # 深入一层（如 /sdcard/Games/GBA/）
                results.extend(_scan_parent(full, depth - 1))
    except PermissionError:
        pass
    return results

def detect_dirs():
    found = []

    # 1) 预设路径快速扫描
    for root in ROM_ROOTS:
        root = _normalize_android_path(root)
        if not os.path.isdir(root): continue
        try:
            n = _count_roms(root)
            if n >= 1:
                found.append((f"{_sys(os.path.basename(root))}  ({n} ROM)", root))
            for entry in sorted(os.listdir(root)):
                full = os.path.join(root, entry)
                if not os.path.isdir(full) or entry in SKIP_DIRS: continue
                n = _count_roms(full)
                if n:
                    found.append((f"{_sys(entry)}  ({n} ROM)", full))
        except: pass

    # 2) 全盘扫描 — 发现玩家自建目录
    for search_root in ROM_SEARCH_ROOTS + _iter_storage_roots():
        search_root = _normalize_android_path(search_root)
        if not os.path.isdir(search_root): continue
        found.extend(_scan_parent(search_root, depth=2))

    # 3) PC 测试 — 扫描项目同级的 test_roms
    for test_root in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "test_roms"),
        "D:\\Agent\\Open-ClaudeCode\\test_roms",
    ]:
        test_root = os.path.normpath(test_root)
        if not os.path.isdir(test_root): continue
        try:
            # 检查根目录本身
            n = _count_roms(test_root)
            if n:
                found.append((f"{os.path.basename(test_root)}  ({n} ROM)", test_root))
            # 检查子目录
            for entry in sorted(os.listdir(test_root)):
                full = os.path.join(test_root, entry)
                if os.path.isdir(full):
                    n = _count_roms(full)
                    if n:
                        found.append((f"{_sys(entry)}  ({n} ROM)", full))
        except: pass

    # 去重
    seen = set()
    unique = []
    for label, path in found:
        if path not in seen:
            seen.add(path)
            unique.append((label, path))
    return unique

def scan_roms(path):
    path = _normalize_android_path(path)
    if not path:
        return []
    try:
        return sorted(
            e for e in os.listdir(path)
            if os.path.isfile(os.path.join(path, e)) and e.lower().endswith(tuple(ROM_EXTS))
        )
    except:
        return []

def _slug(s):
    k = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-"
    return "".join(c if c in k else "_" for c in s)[:80]

# ======================================================================
# Flet App
# ======================================================================

def _writable_dir():
    # Flet Android 提供的可写数据目录
    d = os.environ.get("FLET_APP_STORAGE_DATA", "")
    if d and os.path.isdir(d):
        return d
    home = str(Path.home())
    if home and home not in ("/", ""):
        return home
    return os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_writable_dir(), "iisusc_config.json")

class AppState:
    """全局状态 + 配置持久化"""
    def __init__(self):
        self.rom_dir = ""
        self.rom_dirs = []    # 批量刮削
        self.llm_base_url = "https://api.deepseek.com/v1"
        self.llm_api_key = ""
        self.llm_model = "deepseek-chat"
        self.tgdb_api_key = ""   # TGDB API Key (可选备用)
        self.load()

    def save(self):
        data = {
            "llm_base_url": self.llm_base_url,
            "llm_api_key": self.llm_api_key,
            "llm_model": self.llm_model,
            "tgdb_api_key": self.tgdb_api_key,
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self):
        if not os.path.exists(CONFIG_FILE): return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            if not content.strip():
                return
            data = json.loads(content)
            self.llm_base_url = data.get("llm_base_url", self.llm_base_url)
            self.llm_api_key = data.get("llm_api_key", "")
            self.llm_model = data.get("llm_model", self.llm_model)
            self.tgdb_api_key = data.get("tgdb_api_key", "")
        except (json.JSONDecodeError, Exception):
            bak = CONFIG_FILE + ".bak"
            try: os.rename(CONFIG_FILE, bak)
            except: pass

state = AppState()


def main(page: ft.Page):
    page.title = "iiSU CN Scraper"
    page.theme_mode = ft.ThemeMode.DARK
    page.dark_theme = ft.Theme(
        color_scheme_seed=ACCENT,
        scaffold_bgcolor=BG,
    )
    page.padding = 0
    # 自适应：不设置固定窗口尺寸

    # ---- 导航 (防止重复页面) ----
    def navigate(view):
        """推入新页面，如果当前已是同类型则跳过"""
        route = view.route
        if page.views and page.views[-1].route == route:
            return  # 已在目标页，不重复
        page.views.append(view)
        page.update()

    def go_home(e=None):
        page.views.clear()
        page.views.append(build_home())
        page.update()

    def go_settings(e=None):
        navigate(build_settings())

    def go_scrape(e=None):
        navigate(build_scrape())

    def pop_view(e=None):
        if len(page.views) > 1:
            page.views.pop()
            page.update()

    # ================================================================
    # 首页
    # ================================================================
    def build_home():
        scanning = {"busy": False}

        # 目录列表区 + 多选
        dir_picker = ft.Column(spacing=8, visible=False)
        dir_checks = {}  # {path: Checkbox} 多选状态
        batch_btn = ft.Button("开始批量刮削",
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT, shape=ft.RoundedRectangleBorder(radius=12)),
            visible=False)

        def _update_batch_btn():
            batch_btn.visible = len(dir_checks) > 0
            page.update()

        status_text = ft.Text(
            size=14, color=TEXT_DIM, text_align=ft.TextAlign.CENTER,
            spans=[ft.TextSpan("点击中心按钮", ft.TextStyle(color=TEXT_DIM)),
                   ft.TextSpan("\n自动检测 ROM 目录", ft.TextStyle(color=TEXT_DIM))],
        )

        def _build_dir_card(label, path, icon_name):
            parts = label.split("  (")
            sys_name = parts[0] if parts else label
            rom_count = parts[1].replace(")", "") if len(parts) > 1 else ""
            short_path = path if len(path) <= 60 else "..." + path[-57:]
            cb = ft.Checkbox(value=False, fill_color=ACCENT,
                             on_change=lambda _: _update_batch_btn())
            dir_checks[path] = cb
            return ft.Container(
                content=ft.Row([
                    ft.Icon(icon_name, color=ACCENT, size=20),
                    ft.Column([
                        ft.Text(sys_name, size=14, color=TEXT, weight=ft.FontWeight.BOLD),
                        ft.Text(short_path, size=10, color=TEXT_DIM),
                    ], spacing=1, expand=True),
                    ft.Container(
                        content=ft.Text(rom_count, size=11, color=TEXT, weight=ft.FontWeight.BOLD),
                        bgcolor=ACCENT, border_radius=8,
                        padding=ft.Padding(left=8, top=3, right=8, bottom=3),
                    ) if rom_count else ft.Text(""),
                    cb,
                ], spacing=8, alignment=ft.MainAxisAlignment.START),
                bgcolor=SURFACE, border_radius=12, padding=ft.Padding(left=14, top=10, right=8, bottom=10),
            )

        def _guess_icon(path: str) -> str:
            low = path.lower()
            if any(x in low for x in ("gba","gbc","gb","nds","3ds","n64","nes","sfc","sn")):
                return ft.Icons.VIDEOGAME_ASSET
            if any(x in low for x in ("psp","ps1","ps2","psx","playstation")):
                return ft.Icons.SPORTS_ESPORTS
            return ft.Icons.FOLDER

        def on_scan(e):
            if scanning["busy"]: return
            scanning["busy"] = True
            dir_picker.visible = False
            dir_picker.controls.clear()
            dir_checks.clear()
            batch_btn.visible = False
            page.update()

            def _detect():
                # 在后台线程内切换为扫描中 — 按钮文本由实际扫描状态驱动
                show_scanning()
                dirs = detect_dirs()
                if dirs:
                    show_found(len(dirs))
                    internal = [(l, p) for l, p in dirs if "/storage/emulated/" in p or "/sdcard" in p]
                    external = [(l, p) for l, p in dirs if "/storage/0000-" in p]
                    def _add_section(title, items):
                        if not items: return
                        dir_picker.controls.append(
                            ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color=TEXT_DIM)
                        )
                        for label, path in items:
                            dir_picker.controls.append(_build_dir_card(label, path, _guess_icon(path)))
                    _add_section("内部存储" if internal else "", internal)
                    if external: _add_section("SD 卡", external)
                    other = [(l, p) for l, p in dirs if (l, p) not in internal and (l, p) not in external]
                    _add_section("其他", other) if other else None
                    dir_picker.visible = True
                    status_text.visible = False
                    scanning["busy"] = False
                else:
                    show_not_found()
                    page.update()
                    time.sleep(0.6)
                    scanning["busy"] = False
                    go_settings()
                page.update()

            threading.Thread(target=_detect, daemon=True).start()

        def _pick_one(path):
            """单击卡片 → 只刮削这一个目录"""
            state.rom_dir = path
            state.rom_dirs = [path]
            btn_icon.name = ft.Icons.CHECK_CIRCLE
            btn_icon.color = ACCENT
            btn_title.value = "已选择"
            btn_sub.value = os.path.basename(path)[:20]
            dir_picker.visible = False
            status_text.visible = True
            page.update()
            threading.Timer(0.3, go_scrape).start()

        def _pick_batch(e):
            """批量刮削所有勾选的目录"""
            selected = [p for p, cb in dir_checks.items() if cb.value]
            if not selected:
                _pick_one(list(dir_checks.keys())[0])  # fallback
                return
            state.rom_dir = selected[0]
            state.rom_dirs = selected
            btn_icon.name = ft.Icons.CHECK_CIRCLE
            btn_icon.color = ACCENT
            btn_title.value = f"{len(selected)} 个目录"
            btn_sub.value = "批量刮削"
            dir_picker.visible = False
            status_text.visible = True
            page.update()
            threading.Timer(0.3, go_scrape).start()
        batch_btn.on_click = _pick_batch

        # 按钮内容（动态更新）
        btn_icon = ft.Icon(ft.Icons.SEARCH, color=ACCENT, size=32)
        btn_title = ft.Text("检测 ROM", size=16, weight=ft.FontWeight.BOLD, color=TEXT)
        btn_sub = ft.Text("点击扫描目录", size=11, color=TEXT_DIM)

        def reset_button():
            btn_icon.name = ft.Icons.SEARCH
            btn_icon.color = ACCENT
            btn_title.value = "检测 ROM"
            btn_sub.value = "点击扫描目录"
            circle_body.bgcolor = CARD_BG
            page.update()

        def show_found(count):
            btn_icon.name = ft.Icons.CHECK_CIRCLE
            btn_icon.color = ACCENT
            btn_title.value = f"发现 {count} 个目录"
            btn_sub.value = "点击选择目标"
            circle_body.bgcolor = CARD_BG
            page.update()

        def show_scanning():
            btn_title.value = "检测中..."
            btn_sub.value = ""
            page.update()

        def show_not_found():
            btn_title.value = "未发现"
            btn_sub.value = "前往设置"
            btn_icon.name = ft.Icons.SETTINGS
            btn_icon.color = ACCENT
            circle_body.bgcolor = CARD_BG
            page.update()

        # 鼠标悬浮放大 + 点击缩小
        def on_hover_enter(e):
            if scanning["busy"]: return
            circle_body.scale = 1.08
            page.update()

        def on_hover_exit(e):
            circle_body.scale = 1.0
            page.update()

        def scan_with_anim(e):
            if scanning["busy"]: return
            circle_body.scale = 0.93
            page.update()
            def _anim():
                time.sleep(0.10)
                circle_body.scale = 1.0
                page.update()
                on_scan(e)
            threading.Thread(target=_anim, daemon=True).start()

        circle_body = ft.Container(
            width=180, height=180, border_radius=90,
            bgcolor=CARD_BG,
            border=ft.Border(
                left=ft.BorderSide(2, ACCENT),
                top=ft.BorderSide(2, ACCENT),
                right=ft.BorderSide(2, ACCENT),
                bottom=ft.BorderSide(2, ACCENT),
            ),
            alignment=ft.alignment.Alignment(0, 0),
            animate_scale=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
                controls=[btn_icon, btn_title, btn_sub],
            ),
        )

        circle = ft.GestureDetector(
            on_enter=on_hover_enter,
            on_exit=on_hover_exit,
            on_tap=scan_with_anim,
            content=circle_body,
        )

        return ft.View(
            route="/",
            bgcolor=BG,
            appbar=ft.AppBar(
                title=ft.Text("iiSU CN Scraper", size=18, weight=ft.FontWeight.BOLD, color=TEXT),
                bgcolor=BG,
                actions=[
                    ft.IconButton(ft.Icons.SETTINGS, icon_color=ACCENT,
                                  on_click=lambda _: go_settings()),
                ],
            ),
            controls=[
                ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=0,
                    controls=[
                        ft.Container(height=30),
                        circle,
                        ft.Container(height=20),
                        status_text,
                        ft.Container(height=16),
                        dir_picker,
                        batch_btn,
                        ft.Container(height=40),
                    ],
                ),
            ],
        )

    # ================================================================
    # 设置页
    # ================================================================
    def build_settings():
        field_style = dict(
            bgcolor=SURFACE, border_color="#2a2a3a", color=TEXT,
            label_style=ft.TextStyle(color=TEXT_DIM, size=13),
            content_padding=12, border_radius=8,
        )
        llm_url = ft.TextField(label="API 地址", value=state.llm_base_url, **field_style)
        llm_key = ft.TextField(label="API Key", value=state.llm_api_key, password=True, **field_style)
        llm_model = ft.TextField(label="模型名称", value=state.llm_model, **field_style)
        tgdb_key = ft.TextField(label="API Key", value=state.tgdb_api_key, **field_style)
        dir_list = ft.Column(spacing=3)
        picked_path = ft.Text("", size=13, color=TEXT)
        manual_path = ft.TextField(
            label="手动输入 ROM 路径",
            hint_text="例如 /storage/emulated/0/ROMs/GBA 或 primary:ROMs/GBA",
            **field_style,
        )
        scrape_from_settings_btn = ft.Button("开始刮削此目录",
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT, shape=ft.RoundedRectangleBorder(radius=10)),
            visible=False)
        selected_box = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ACCENT, size=16),
                    ft.Text("已选择目录", size=11, color=TEXT_DIM),
                ], spacing=4),
                ft.Container(content=picked_path, bgcolor=CARD_BG, border_radius=6, padding=8),
                scrape_from_settings_btn,
            ], spacing=8),
            bgcolor=SURFACE, border_radius=10, padding=12,
            visible=False,
        )

        # 文件夹选择 (桌面: tkinter / 安卓: 聚焦手动输入)
        if sys.platform == "win32" or sys.platform == "darwin":
            # 桌面端：tkinter 系统对话框
            def pick_folder(e):
                try:
                    from tkinter import Tk, filedialog
                    root = Tk()
                    root.withdraw()
                    root.attributes("-topmost", True)
                    path = filedialog.askdirectory(title="选择 ROM 文件夹")
                    root.destroy()
                    if path:
                        _set(path)
                except Exception:
                    picked_path.value = "请使用自动检测功能"
                page.update()
        else:
            # 安卓端：Flet FilePicker 不可用，聚焦手动输入框
            def pick_folder(e):
                manual_path.focus()
                picked_path.value = '请在下方输入 ROM 路径后点击"使用手动路径"'
                page.update()

        def open_storage_settings(e):
            if _open_all_files_access_settings():
                picked_path.value = "请在系统设置中允许管理所有文件后返回"
            else:
                picked_path.value = "无法打开系统权限页，请手动授予存储权限"
            page.update()

        def apply_manual_path(e):
            path = _normalize_android_path(manual_path.value)
            if not path:
                picked_path.value = "请输入路径"
                page.update()
                return
            try:
                os.listdir(path)
                _set(path)
            except PermissionError:
                picked_path.value = "无读取权限，请点击「授予存储权限」"
                page.update()
            except (FileNotFoundError, NotADirectoryError):
                picked_path.value = "路径不存在，请检查拼写"
                page.update()
            except Exception as ex:
                picked_path.value = f"无法访问: {ex}"
                page.update()

        def do_detect(e):
            dir_list.controls.clear()
            try:
                dirs = detect_dirs()
            except Exception as ex:
                dirs = []
                picked_path.value = f"检测出错: {ex}"
            if not dirs:
                dir_list.controls.append(
                    ft.Text("未检测到 ROM 目录", size=12, color=TEXT_DIM))
            else:
                for label, path in dirs:
                    dir_list.controls.append(
                        ft.Container(
                            content=ft.Column([
                                ft.Text(label, size=13, color=TEXT, weight=ft.FontWeight.BOLD),
                                ft.Text(path, size=10, color=TEXT_DIM),
                            ], spacing=1),
                            bgcolor=SURFACE, border_radius=8, padding=10,
                            on_click=lambda _, p=path: _set(p),
                        )
                    )
            page.update()

        def _set(path):
            path = _normalize_android_path(path)
            state.rom_dir = path
            manual_path.value = path
            picked_path.value = path
            scrape_from_settings_btn.visible = True
            selected_box.visible = True
            page.update()

        def go_scrape_from_settings(e):
            if state.rom_dir:
                state.rom_dirs = [state.rom_dir]
                save_all()
                pop_view()
                go_scrape()

        scrape_from_settings_btn.on_click = go_scrape_from_settings

        def save_all():
            state.llm_base_url = llm_url.value.strip()
            state.llm_api_key = llm_key.value.strip()
            state.llm_model = llm_model.value.strip()
            state.tgdb_api_key = tgdb_key.value.strip()
            state.save()

        # 带左紫条装饰的卡片
        def _card(icon, title, controls):
            return ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(icon, color=ACCENT, size=18),
                        ft.Text(title, size=15, weight=ft.FontWeight.BOLD, color=TEXT),
                    ], spacing=8),
                    ft.Container(height=2, bgcolor="#2a2a3a"),
                    ft.Container(height=4),
                    *controls,
                ], spacing=8),
                bgcolor=CARD_BG, border_radius=14, padding=18,
                border=ft.Border(
                    left=ft.BorderSide(3, ACCENT),
                    top=ft.BorderSide(0, "#00000000"),
                    right=ft.BorderSide(0, "#00000000"),
                    bottom=ft.BorderSide(0, "#00000000"),
                ),
            )

        return ft.View(
            route="/settings",
            bgcolor=BG,
            appbar=ft.AppBar(
                leading=ft.IconButton(
                    ft.Icons.ARROW_BACK_IOS_NEW, icon_color=ACCENT,
                    icon_size=20,
                    on_click=lambda _: (save_all(), pop_view()),
                ),
                title=ft.Text("设置", size=18, weight=ft.FontWeight.BOLD, color=TEXT),
                bgcolor=BG,
            ),
            controls=[
                ft.ListView(
                    expand=True,
                    spacing=20,
                    padding=ft.Padding(left=16, top=12, right=16, bottom=32),
                    controls=[
                        # ROM 目录 — 重新设计布局
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.Icons.FOLDER_OPEN, color=ACCENT, size=18),
                                    ft.Text("ROM 目录", size=15, weight=ft.FontWeight.BOLD, color=TEXT),
                                ], spacing=8),
                                ft.Container(height=2, bgcolor="#2a2a3a"),
                                ft.Container(height=8),
                                ft.Row([
                                    ft.Container(
                                        content=ft.Button("自动检测", on_click=do_detect,
                                            style=ft.ButtonStyle(bgcolor=SURFACE, color=ACCENT,
                                                                 shape=ft.RoundedRectangleBorder(radius=8))),
                                        expand=True,
                                    ),
                                    ft.Container(width=10),
                                    ft.Container(
                                        content=ft.Button("浏览文件夹", on_click=pick_folder,
                                            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT,
                                                                 shape=ft.RoundedRectangleBorder(radius=8))),
                                        expand=True,
                                    ),
                                ]),
                                manual_path,
                                ft.Row([
                                    ft.Container(
                                        content=ft.Button("使用手动路径", on_click=apply_manual_path,
                                            style=ft.ButtonStyle(bgcolor=SURFACE, color=ACCENT,
                                                                 shape=ft.RoundedRectangleBorder(radius=8))),
                                        expand=True,
                                    ),
                                    ft.Container(width=10),
                                    ft.Container(
                                        content=ft.Button("授予存储权限", on_click=open_storage_settings,
                                            style=ft.ButtonStyle(bgcolor=SURFACE, color=ACCENT,
                                                                 shape=ft.RoundedRectangleBorder(radius=8))),
                                        expand=True,
                                    ),
                                ]),
                                # 检测结果列表
                                dir_list,
                                # 选中路径展示 + 刮削按钮
                                selected_box,
                            ], spacing=6),
                            bgcolor=CARD_BG, border_radius=14, padding=18,
                            border=ft.Border(
                                left=ft.BorderSide(3, ACCENT),
                                top=ft.BorderSide(0, "#00000000"),
                                right=ft.BorderSide(0, "#00000000"),
                                bottom=ft.BorderSide(0, "#00000000"),
                            ),
                        ),
                        # LLM
                        _card(ft.Icons.PSYCHOLOGY, "AI 语义清洗", [
                            llm_url, llm_key, llm_model,
                        ]),
                        # TheGamesDB (可选备用)
                        _card(ft.Icons.CLOUD_DOWNLOAD, "TheGamesDB (可选备用)", [
                            tgdb_key,
                            ft.Text("Bangumi 已免费覆盖大部分中文游戏，TGDB 作为英文补充",
                                    size=11, color=TEXT_DIM),
                        ]),
                    ],
                ),
            ],
        )

    # ================================================================
    # 刮削页
    # ================================================================
    def build_scrape():
        # 支持批量目录
        rom_dirs = state.rom_dirs if state.rom_dirs else [state.rom_dir]
        all_roms = []
        for d in rom_dirs:
            for fname in scan_roms(d):
                all_roms.append((fname, os.path.join(d, fname)))
        total = len(all_roms)
        rom_count = ft.Text(f"{total} ROM ({len(rom_dirs)} 目录)", size=14, color=TEXT)
        status = ft.Text("就绪", size=13, color=TEXT_DIM)
        progress = ft.ProgressBar(value=0, color=ACCENT, bgcolor=SURFACE, expand=True)
        log_lines = ft.Column(spacing=1)  # 每条日志一行，可滚动

        def add_log(msg):
            log_lines.controls.append(ft.Text(msg, size=11, color=TEXT_DIM))
            page.update()
        start_btn = ft.Button(
            "开始刮削",
            style=ft.ButtonStyle(
                bgcolor=ACCENT, color=TEXT,
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=ft.Padding(left=24, top=14, right=24, bottom=14),
            ),
        )

        # ROM 勾选列表 —— 卡片式
        checks = {}
        rom_cards = ft.Column(spacing=6)
        for fname, fpath in all_roms:
            cb = ft.Checkbox(value=True, fill_color=ACCENT)
            checks[fpath] = cb
            card = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.VIDEOGAME_ASSET, color=TEXT_DIM, size=18),
                    ft.Text(fname[:55], size=13, color=TEXT),
                    ft.Container(expand=True),
                    cb,
                ], spacing=10, alignment=ft.MainAxisAlignment.START),
                bgcolor=SURFACE, border_radius=10, padding=ft.Padding(left=14, top=10, right=8, bottom=10),
            )
            rom_cards.controls.append(card)

        # 全选/取消
        def toggle_all(e):
            all_on = all(cb.value for cb in checks.values())
            for cb in checks.values():
                cb.value = not all_on
            toggle_btn.text = "取消全选" if not all_on else "全选"
            page.update()

        toggle_btn = ft.TextButton("全选", on_click=toggle_all,
                                   style=ft.ButtonStyle(color=ACCENT))

        def do_scrape(e):
            # 从 all_roms 中取完整路径
            selected = [fp for fp, cb in checks.items() if cb.value]
            if not selected:
                status.value = "未选中 ROM"
                page.update(); return

            # 检查 API 配置
            missing = []
            if not state.llm_api_key: missing.append("LLM API Key")
            if missing:
                status.value = f"请在设置中填入: {', '.join(missing)}"
                add_log("API 密钥未配置，无法刮削")
                page.update()
                return

            start_btn.disabled = True
            start_btn.text = "刮削中..."
            start_btn.style = ft.ButtonStyle(
                bgcolor=TEXT_DIM, color=TEXT,
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=ft.Padding(left=24, top=14, right=24, bottom=14),
            )
            progress.value = 0
            log_lines.controls.clear()
            status.value = "正在连接..."
            page.update()

            def _update_ui():
                try: page.update()
                except RuntimeError: pass

            def _run():
                nonlocal start_btn
                try:
                    add_log("--- LLM 语义清洗 ---")
                    cl = OpenAI(base_url=state.llm_base_url, api_key=state.llm_api_key)
                    lm = {}
                    for i, p in enumerate(selected):
                        fn = os.path.basename(p)
                        progress.value = 0.05 + 0.15 * (i+1)/len(selected)
                        status.value = f"AI 清洗 {i+1}/{len(selected)}"
                        _update_ui()
                        try:
                            lm[fn] = normalize_rom_name(cl, state.llm_model, fn)
                            zh = lm[fn].get("standard_zh","")
                            en = lm[fn].get("standard_en","")
                            add_log(f"{fn[:35]} → {zh or en or '(空)'}")
                        except Exception as e:
                            lm[fn] = {"standard_zh": "", "standard_en": ""}
                            add_log(f"{fn[:35]} → LLM错误: {e}")
                        _update_ui()

                    add_log("--- Bangumi 中文刮削 ---")
                    _update_ui()
                    bgm = BangumiFetcher()
                    tgdb = TGDBFetcher(state.tgdb_api_key) if state.tgdb_api_key else None
                    # 批量: 按 ROM 所在目录分组写入 gamelist
                    gamelists = {}  # {parent_dir: (root, existing_index)}
                    ok = 0

                    for i, rp in enumerate(selected):
                        fn = os.path.basename(rp); rel = "./" + fn
                        parent = str(Path(rp).parent)
                        # 懒加载各目录的 gamelist
                        if parent not in gamelists:
                            gp = Path(parent) / "gamelist.xml"
                            rt, ex = load_existing_gamelist(gp)
                            gamelists[parent] = (gp, rt, ex)
                        else:
                            gp, rt, ex = gamelists[parent]
                        cd = Path(parent) / "downloaded_media" / "covers"

                        progress.value = 0.30 + 0.65 * (i+1)/len(selected)
                        status.value = fn[:50]; _update_ui()

                        if rel in ex:
                            add_log(f"跳过: {fn[:35]}"); continue
                        ll = lm.get(fn, {"standard_zh": "", "standard_en": "", "desc_zh": ""})
                        zh, en = ll.get("standard_zh",""), ll.get("standard_en","")
                        if not zh and not en:
                            add_log(f"无名称: {fn[:35]}"); continue

                        # 1) Bangumi (中文优先)
                        status.value = f"Bangumi: {zh or en}"
                        _update_ui()
                        meta = bgm.search_game(zh, en)
                        source = "Bangumi"

                        # 2) TGDB 备用
                        if not meta or "_error" in meta:
                            if tgdb:
                                status.value = f"TGDB: {zh or en}"
                                _update_ui()
                                meta = tgdb.search_game(zh, en)
                                source = "TGDB"

                        if not meta:
                            add_log(f"未匹配: {zh or en}"); continue
                        if "_error" in meta:
                            add_log(f"{source}错误: {meta['_error'][:60]}")
                            continue

                        sf = _slug(Path(fn).stem)
                        cr = ""
                        cover_url = meta.get("cover_url", "")
                        if cover_url:
                            if bgm.download_cover(meta, cd / f"{sf}-image.png"):
                                cr = f"./downloaded_media/covers/{sf}-image.png"
                            elif tgdb and tgdb.download_cover(meta, cd / f"{sf}-image.png"):
                                cr = f"./downloaded_media/covers/{sf}-image.png"
                        if cr:
                            add_log(f"封面: OK")
                        else:
                            add_log(f"封面: 无")

                        # 描述: Bangumi 中文 > LLM 生成 > TGDB 翻译
                        desc = meta.get("desc", "") or ll.get("desc_zh", "")
                        if source == "TGDB" and desc:
                            desc = translate_desc(cl, state.llm_model, desc) or desc
                        if not desc:
                            desc = ll.get("desc_zh", "")

                        # 名称: Bangumi 中文 > LLM 中文 > 原名
                        display_name = (meta.get("name_zh", "")
                                        or ll.get("standard_zh", "")
                                        or meta.get("name_en", "")
                                        or Path(fn).stem)
                        add_log(f"完成: {display_name}")

                        entry = {
                            "name": display_name,
                            "desc": desc, "image": cr, "marquee": "",
                            "developer": meta.get("developer",""), "publisher": meta.get("publisher",""),
                            "genre": meta.get("genre",""), "players": meta.get("players",""),
                            "release_date": meta.get("release_date",""), "rating": meta.get("rating",""),
                        }
                        ge = build_game_element(rel, entry)
                        if rel in ex: rt.remove(ex[rel])
                        rt.append(ge); ex[rel] = ge; write_gamelist(gp, rt); ok += 1

                    progress.value = 1.0
                    status.value = f"完成 {ok} 个"
                    for pdir in gamelists:
                        add_log(f"gamelist.xml -> {pdir}")
                except Exception as ex:
                    status.value = f"错误: {ex}"
                finally:
                    start_btn.disabled = False
                    start_btn.text = "开始刮削"
                    page.update()

            threading.Thread(target=_run, daemon=True).start()

        start_btn.on_click = do_scrape

        return ft.View(
            route="/scrape",
            bgcolor=BG,
            appbar=ft.AppBar(
                leading=ft.IconButton(
                    ft.Icons.ARROW_BACK, icon_color=ACCENT, on_click=pop_view,
                ),
                title=ft.Row([
                    ft.Text("刮削任务", size=18, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(width=8),
                    rom_count,
                ]),
                bgcolor=BG,
                actions=[toggle_btn],
            ),
            controls=[
                ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                    controls=[
                        # ROM 列表区
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Text("ROM 列表", size=13, weight=ft.FontWeight.BOLD, color=TEXT_DIM),
                                ]),
                                ft.Container(height=6),
                                rom_cards,
                            ]),
                            padding=ft.Padding(left=16, top=4, right=16, bottom=0),
                        ),
                        # 进度区
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.Icons.DOWNLOADING, color=ACCENT, size=16),
                                    ft.Container(width=6),
                                    status,
                                ], spacing=0),
                                ft.Container(height=8),
                                progress,
                            ]),
                            bgcolor=SURFACE, border_radius=12,
                            padding=ft.Padding(left=16, top=12, right=16, bottom=12),
                            margin=ft.Padding(left=16, top=0, right=16, bottom=0),
                        ),
                        # 日志区 (可滚动)
                        ft.Container(
                            content=ft.Column([
                                ft.Text("日志", size=12, weight=ft.FontWeight.BOLD, color=TEXT_DIM),
                                ft.Container(height=4),
                                ft.Column(
                                    controls=[log_lines],
                                    scroll=ft.ScrollMode.AUTO,
                                    expand=True,
                                ),
                            ]),
                            bgcolor=SURFACE, border_radius=12,
                            padding=ft.Padding(left=16, top=12, right=16, bottom=12),
                            margin=ft.Padding(left=16, top=0, right=16, bottom=0),
                        ),
                        # 按钮
                        ft.Container(
                            content=start_btn,
                            padding=ft.Padding(left=16, top=4, right=16, bottom=16),
                        ),
                    ],
                ),
            ],
        )

    # 启动
    go_home()


if __name__ == "__main__":
    ft.app(target=main)
