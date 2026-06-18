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
if sys.platform == "win32":
    ROM_ROOTS = [
        os.path.expanduser("~/ROMs"),
        os.path.expanduser("~/Documents/ROMs"),
        os.path.expanduser("~/Desktop/ROMs"),
        os.path.expanduser("~/Documents/RetroArch/roms"),
        os.path.expanduser("~/Documents/Dolphin Emulator/Games"),
        os.path.expanduser("~/Documents/PCSX2/roms"),
        "D:\\ROMs", "D:\\Games", "D:\\Emulation\\roms",
    ]
elif sys.platform == "darwin":
    ROM_ROOTS = [
        os.path.expanduser("~/ROMs"),
        os.path.expanduser("~/Documents/ROMs"),
        os.path.expanduser("~/Desktop/ROMs"),
        os.path.expanduser("~/Documents/RetroArch/roms"),
        os.path.expanduser("~/Documents/Dolphin Emulator/Games"),
        os.path.expanduser("~/Library/Application Support/RetroArch/roms"),
        os.path.expanduser("~/Games"),
    ]
else:
    # Android / Linux
    ROM_ROOTS = [
        "/storage/emulated/0/ROMs", "/storage/emulated/0/roms",
        "/sdcard/ROMs", "/sdcard/roms",
        "/storage/emulated/0/Emulation/roms",
        "/storage/emulated/0/Games",
        "/storage/emulated/0/Download",
        "/storage/0000-0000/ROMs", "/storage/0000-0000/roms",
        "/storage/emulated/0/RetroArch/roms",
        "/storage/emulated/0/Documents/ROMs",
        "/storage/emulated/0/Documents/roms",
        "/storage/emulated/0/Documents/Games",
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
             ".thumbnails", ".Trash", "Pendownload", "Tencent", "backups",
             "Recordings", "SpeedSoftware", "TitaniumBackup", "MIUI",
             "ColorOS", "Snapdrop", "Edit", "Fonts", "Notifications",
             "Sounds", "Ringtones", "Pictures", "Movies", "Podcasts",
             "Recordings", "tbs", "tp", "talkingdata", "bugly", "umeng"}

# 桌面端系统目录 — 避免递归扫描浪费在系统文件上
if sys.platform == "win32":
    SKIP_DIRS |= {
        "Windows", "Program Files", "Program Files (x86)",
        "ProgramData", "$Recycle.Bin", "System Volume Information",
        "Recovery", "Config.Msi", "MSOCache", "PerfLogs",
        "WindowsApps", "AppData", "Application Data",
        "Local Settings", "NetHood", "PrintHood", "Recent",
        "SendTo", "Start Menu", "Templates", "Cookies",
        "Intel", "AMD", "NVIDIA", "Drivers",
    }
elif sys.platform == "darwin":
    SKIP_DIRS |= {
        "Applications", "Library", "System", "opt", "private",
        "usr", "bin", "sbin", "etc", "var", "tmp", "cores",
        "dev", "home", "net",
        ".Spotlight-V100", ".Trashes", ".fseventsd",
        ".DocumentRevisions-V100", ".TemporaryItems",
    }
SKIP_PREFIXES = ("com.", "org.", "net.", "io.", "cn.", "de.")

if sys.platform == "win32":
    ROM_SEARCH_ROOTS = [
        os.path.expanduser("~"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Desktop"),
    ]
elif sys.platform == "darwin":
    ROM_SEARCH_ROOTS = [
        os.path.expanduser("~"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Desktop"),
        "/Volumes",
    ]
else:
    # Android
    ROM_SEARCH_ROOTS = [
        "/storage/emulated/0",
        "/sdcard",
    ]

def _detect_device_vendor() -> str:
    """Detect device manufacturer for vendor-specific permission intents."""
    for prop in ['ro.product.manufacturer', 'ro.product.brand']:
        try:
            result = subprocess.run(['getprop', prop], capture_output=True, text=True, timeout=1)
            v = result.stdout.strip().lower()
            if v:
                return v
        except Exception:
            continue
    return "unknown"


def _am_start(*args):
    """Try /system/bin/am first, then am (some devices only have one)."""
    for am in ['/system/bin/am', 'am']:
        try:
            subprocess.run([am, 'start'] + list(args), timeout=3, check=False)
            return True
        except Exception:
            continue
    return False


def _open_app_settings():
    """Open the app's own system settings page where all permissions can be toggled."""
    if sys.platform in ("win32", "darwin"):
        return False
    for action in [
        '-a', 'android.settings.APPLICATION_DETAILS_SETTINGS',
        '-d', 'package:com.kiloiam.iisu_cn_scraper',
    ]:
        pass
    return _am_start(
        '-a', 'android.settings.APPLICATION_DETAILS_SETTINGS',
        '-d', 'package:com.kiloiam.iisu_cn_scraper',
    )


def _open_all_files_access(vendor: str = ""):
    """Open the All Files Access permission page using the most compatible intent.

    Tries multiple intent actions in order of specificity, falling back to
    the generic page that works on all Android 11+ devices.
    """
    if sys.platform in ("win32", "darwin"):
        return False
    pkg = 'package:com.kiloiam.iisu_cn_scraper'

    # 1) Directed intent (Android 12+, may work on stock Android)
    if _am_start('-a', 'android.settings.MANAGE_APP_ALL_FILES_ACCESS_PERMISSION', '-d', pkg):
        return True

    # 2) Generic all-files-access page (all Android 11+)
    if _am_start('-a', 'android.settings.MANAGE_ALL_FILES_ACCESS_PERMISSION'):
        return True

    # 3) Last resort: open app details page so user can find the toggle manually
    return _open_app_settings()


def _auto_grant_storage():
    """Android 手动触发：打开「所有文件访问」权限页面（多 intent 回退）。"""
    if sys.platform in ("win32", "darwin"):
        return
    _open_all_files_access()


def _normalize_android_path(path: str) -> str:
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        return ""
    # Windows 绝对路径 (如 D:\ROMs) — 直接返回，不要当成 Android URI 处理
    if len(raw) >= 2 and raw[1] == ":":
        return os.path.normpath(raw)
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
    if sys.platform == "win32":
        import string as _string
        roots = []
        for letter in _string.ascii_uppercase:
            if letter in ("A", "B"):
                continue
            drive = f"{letter}:\\"
            if letter == "C":
                continue  # 已被 ROM_SEARCH_ROOTS ~/ 覆盖
            if os.path.isdir(drive):
                roots.append(drive)
        return roots

    if sys.platform == "darwin":
        roots = []
        volumes = "/Volumes"
        if os.path.isdir(volumes):
            try:
                for entry in sorted(os.listdir(volumes)):
                    if entry.startswith(".") or entry == "Macintosh HD":
                        continue
                    full = os.path.join(volumes, entry)
                    if os.path.isdir(full) and os.access(full, os.R_OK):
                        roots.append(full)
            except PermissionError:
                pass
        return roots

    # Android / Linux
    roots = ["/storage/emulated/0", "/sdcard"]
    storage = "/storage"
    try:
        for entry in sorted(os.listdir(storage)):
            if entry in {"self", "emulated"} or entry.startswith("."):
                continue
            full = os.path.join(storage, entry)
            if os.path.isdir(full) and os.access(full, os.R_OK):
                roots.append(full)
    except PermissionError:
        pass
    except Exception:
        pass
    # 去重 (follow symlinks)
    seen = set()
    unique = []
    for root in roots:
        try:
            real = os.path.realpath(root)
        except Exception:
            real = root
        if real not in seen:
            seen.add(real)
            unique.append(root)
    return unique


_COUNT_ERRORS = []  # 全局，供 UI 展示

_AMBIGUOUS_EXTS = {".bin", ".cue", ".zip", ".7z"}

def _is_ambiguous_ext(filename: str) -> bool:
    """歧义扩展名：不一定是 ROM 文件，需结合目录名判断"""
    return filename.lower().endswith(tuple(_AMBIGUOUS_EXTS))

def _is_rom_dir(path: str) -> bool:
    """判断目录名是否匹配已知 ROM 平台，用于歧义扩展名过滤"""
    basename = os.path.basename(path).lower().replace(" ", "").replace("-", "").replace("_", "")
    return any(k in basename for k in SYSTEMS)

def _count_roms(path: str) -> int:
    """统计目录下 ROM 文件数量（仅一级，不递归）。使用 scandir 减少 stat 调用。"""
    try:
        count = 0
        for entry in os.scandir(path):
            if not entry.is_file():
                continue
            if entry.name.lower().endswith(tuple(ROM_EXTS)):
                # 对歧义扩展名做额外过滤：目录名不在 SYSTEMS 映射中则跳过
                if _is_ambiguous_ext(entry.name) and not _is_rom_dir(path):
                    continue
                count += 1
        return count
    except PermissionError:
        _COUNT_ERRORS.append(f"无权限: {path}")
        return 0
    except FileNotFoundError:
        return 0
    except NotADirectoryError:
        return 0
    except Exception as ex:
        _COUNT_ERRORS.append(f"{path}: {ex}")
        return 0

def _scan_parent(parent: str, depth: int = 2) -> list:
    """递归扫描目录树，寻找含 ROM 的目录。使用 scandir 减少 stat 调用。"""
    results = []
    parent = _normalize_android_path(parent)
    if depth <= 0:
        return results
    try:
        with os.scandir(parent) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                if entry.name.startswith("."):
                    continue
                if not entry.is_dir():
                    continue
                if entry.name in SKIP_DIRS or entry.name.startswith(SKIP_PREFIXES):
                    continue
                n = _count_roms(entry.path)
                if n >= 1:
                    results.append((f"{_sys(entry.name)}  ({n} ROM)", entry.path))
                if depth > 1:
                    results.extend(_scan_parent(entry.path, depth - 1))
    except PermissionError:
        _COUNT_ERRORS.append(f"无权限扫描: {parent}")
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return results

def _scan_root(root: str, depth: int = 2) -> list:
    """扫描单个根目录，返回 (label, path) 列表。"""
    results = []
    root = _normalize_android_path(root)
    if not os.path.isdir(root):
        return results
    try:
        n = _count_roms(root)
        if n >= 1:
            results.append((f"{_sys(os.path.basename(root))}  ({n} ROM)", root))
        results.extend(_scan_parent(root, depth=depth))
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return results


def detect_dirs(on_found=None, on_progress=None):
    """检测 ROM 目录。on_found/on_progress 可选回调用于增量通知。返回 (dirs, errors)。"""
    global _COUNT_ERRORS
    _COUNT_ERRORS = []
    found = []
    errors = []
    seen = set()

    def _add(label, path):
        if path in seen:
            return
        seen.add(path)
        found.append((label, path))
        if on_found:
            on_found(label, path)

    def _report(msg):
        if on_progress:
            on_progress(msg)

    # 1) 预设路径 — 快速扫描
    for root in ROM_ROOTS:
        _report(f"扫描 {os.path.basename(root) or root[:20]}...")
        for label, path in _scan_root(root, 2):
            _add(label, path)

    # 2) 全盘扫描 — 发现玩家自建目录
    for search_root in ROM_SEARCH_ROOTS + _iter_storage_roots():
        short = os.path.basename(search_root) or search_root.replace("/storage/", "")[:20]
        _report(f"扫描 {short}...")
        for label, path in _scan_root(search_root, 2):
            _add(label, path)

    errors.extend(_COUNT_ERRORS)
    return found, errors

def scan_roms(path):
    path = _normalize_android_path(path)
    if not path:
        return []
    try:
        result = []
        for entry in os.scandir(path):
            if entry.is_file() and entry.name.lower().endswith(tuple(ROM_EXTS)):
                result.append(entry.name)
        result.sort()
        return result
    except:
        return []

def _slug(s):
    k = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-"
    return "".join(c if c in k else "_" for c in s)[:80]

# ======================================================================
# Flet App
# ======================================================================

def _writable_dir():
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


def _has_storage_permission() -> bool:
    """Test if storage is readable."""
    if sys.platform in ("win32", "darwin"):
        return True
    for p in ["/storage/emulated/0", "/sdcard"]:
        try:
            os.listdir(p)
            return True
        except Exception:
            continue
    return False


def _check_storage_permission_on_startup(page: ft.Page):
    """启动时检测存储权限，无权限则弹窗引导用户去系统设置开启。"""
    if _has_storage_permission():
        return

    def _close_permission_dlg(e=None):
        page.pop_dialog()

    def open_settings(e):
        _close_permission_dlg()
        _open_all_files_access()
        # 注册回扫：用户从设置返回后自动重扫
        if _rescan_fn[0]:
            _rescan_fn[0](None)

    dlg = ft.AlertDialog(
        title=ft.Text("需要存储权限", color=TEXT),
        content=ft.Text(
            "检测 ROM 和写入 gamelist.xml 需要「所有文件访问」权限。\n\n"
            "点击「去设置」→ 找到 iiSU CN Scraper → 开启允许管理所有文件 → 返回即可。",
            color=TEXT_DIM, size=13,
        ),
        actions=[
            ft.TextButton("稍后", on_click=_close_permission_dlg,
                          style=ft.ButtonStyle(color=TEXT_DIM)),
            ft.TextButton("去设置", on_click=open_settings, style=ft.ButtonStyle(color=ACCENT)),
        ],
        bgcolor=SURFACE,
    )
    page.show_dialog(dlg)


_rescan_fn = [None]
_home_reset_fn = [None]  # 从刮削页返回首页时恢复 UI

_last_scan_dirs = []  # 缓存上次扫描结果，供后台重扫对比

def _background_rescan_home():
    """后台线程：轻量重扫，仅结果变化时才触发 UI 刷新。"""
    try:
        dirs, _ = detect_dirs()
        new_paths = {p for _, p in dirs}
        old_paths = {p for _, p in _last_scan_dirs}
        if new_paths != old_paths and new_paths:
            _last_scan_dirs[:] = dirs
    except Exception:
        pass

def main(page: ft.Page):
    # 启动即检查存储权限，无权限弹窗引导
    _check_storage_permission_on_startup(page)

    def on_lifecycle(e):
        """从权限设置页或 SAF 目录选择器返回时自动重扫。"""
        if e.data in ("resume", "show") and _rescan_fn[0]:
            page.run_task(_rescan_fn[0], None)

    page.on_app_lifecycle_state_change = on_lifecycle
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
        _rescan_fn[0] = None
        # 先移除旧 scrape 页（如果有），确保 build_scrape 读到最新的 state
        page.views = [v for v in page.views if v.route != "/scrape"]
        page.views.append(build_scrape())
        page.update()

    def pop_view(e=None):
        if len(page.views) > 1:
            page.views.pop()
            page.update()
        # 回到首页时恢复 UI + 后台轻量重扫
        if page.views and page.views[-1].route == "/":
            if _home_reset_fn[0]:
                _home_reset_fn[0]()
            page.run_thread(_background_rescan_home)

    # ================================================================
    # 首页
    # ================================================================
    def build_home():
        scan_state = {"state": "idle"}  # idle | scanning | done

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

        # 桌面端：扫描未找到时的浏览按钮
        def _browse_folder(e):
            try:
                from tkinter import Tk, filedialog
                root = Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                path = filedialog.askdirectory(title="选择 ROM 文件夹")
                root.destroy()
                if path:
                    path = os.path.normpath(path)
                    n = _count_roms(path)
                    label = f"{_sys(os.path.basename(path))}  ({n} ROM)" if n else f"{os.path.basename(path)}"
                    state.rom_dir = path
                    state.rom_dirs = [path]
                    btn_icon.name = ft.Icons.CHECK_CIRCLE
                    btn_icon.color = ACCENT
                    btn_title.value = "已选择"
                    btn_sub.value = os.path.basename(path)[:20]
                    browse_btn.visible = False
                    status_text.visible = False
                    page.update()
                    go_scrape()
            except Exception:
                pass

        browse_btn = ft.Button(
            "浏览文件夹...",
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT, shape=ft.RoundedRectangleBorder(radius=10)),
            visible=False,
            on_click=_browse_folder,
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
                ink=True,
                on_click=lambda e, p=path: _pick_one(p),
            )

        def _guess_icon(path: str) -> str:
            low = path.lower()
            if any(x in low for x in ("gba","gbc","gb","nds","3ds","n64","nes","sfc","sn")):
                return ft.Icons.VIDEOGAME_ASSET
            if any(x in low for x in ("psp","ps1","ps2","psx","playstation")):
                return ft.Icons.SPORTS_ESPORTS
            return ft.Icons.FOLDER

        def on_scan(e):
            if scan_state["state"] == "scanning":
                return
            if scan_state["state"] == "done":
                def _close_rescan_dlg(ev=None):
                    page.pop_dialog()

                def do_rescan(ev):
                    page.pop_dialog()
                    scan_state["state"] = "idle"
                    reset_button()
                    on_scan(None)
                dlg = ft.AlertDialog(
                    title=ft.Text("重新扫描", color=TEXT),
                    content=ft.Text("已有扫描结果，是否重新扫描？", color=TEXT),
                    actions=[
                        ft.TextButton("取消", on_click=_close_rescan_dlg),
                        ft.TextButton("重新扫描", on_click=do_rescan,
                                      style=ft.ButtonStyle(color=ACCENT)),
                    ],
                    bgcolor=SURFACE,
                )
                page.show_dialog(dlg)
                return
            _rescan_fn[0] = on_scan  # 从权限/SAF页面返回时自动重扫
            scan_state["state"] = "scanning"
            btn_icon.name = ft.Icons.HOURGLASS_BOTTOM
            btn_icon.color = ACCENT
            btn_title.value = "扫描中..."
            btn_sub.value = "正在检测 ROM 目录"
            dir_picker.visible = False
            dir_picker.controls.clear()
            dir_checks.clear()
            batch_btn.visible = False
            browse_btn.visible = False
            status_text.visible = True
            page.update()

            def _on_progress(msg):
                btn_sub.value = msg
                try: page.update()
                except: pass

            def _scan_thread():
                # 不切换主标题 — 进度由 btn_sub 展示，结果由 show_found/show_not_found 驱动
                dirs, errors = detect_dirs(on_progress=_on_progress)
                _last_scan_dirs[:] = dirs
                if dirs:
                    _show_results(dirs)
                    scan_state["state"] = "done"
                else:
                    if errors:
                        status_text.value = f"权限不足: {'; '.join(errors[:2])}"
                        status_text.color = "#ff9f43"
                    show_not_found()
                    scan_state["state"] = "done"
                page.update()
                # 桌面端未找到 → 展示浏览按钮；Android 端 → 跳转设置
                if not dirs:
                    if sys.platform in ("win32", "darwin"):
                        status_text.visible = False
                        browse_btn.visible = True
                    else:
                        def _delayed_go():
                            if not _last_scan_dirs:
                                go_settings()
                        threading.Timer(1.2, _delayed_go).start()

            page.run_thread(_scan_thread)

        def _pick_one(path):
            """单击卡片 → 只刮削这一个目录"""
            if not os.path.isdir(_normalize_android_path(path)):
                status_text.value = "目录已失效，请重新扫描"
                status_text.color = "#ff9f43"
                page.update()
                return
            state.rom_dir = path
            state.rom_dirs = [path]
            btn_icon.name = ft.Icons.CHECK_CIRCLE
            btn_icon.color = ACCENT
            btn_title.value = "已选择"
            btn_sub.value = os.path.basename(path)[:20]
            dir_picker.visible = False
            status_text.visible = True
            page.update()
            go_scrape()

        def _pick_batch(e):
            """批量刮削所有勾选的目录"""
            selected = [p for p, cb in dir_checks.items() if cb.value]
            if not selected:
                status_text.value = "请先勾选要刮削的目录"
                status_text.color = "#ff9f43"
                page.update()
                return
            # 过滤掉已失效的目录
            valid = [p for p in selected if os.path.isdir(_normalize_android_path(p))]
            invalid = len(selected) - len(valid)
            if not valid:
                status_text.value = "所选目录均已失效，请重新扫描"
                status_text.color = "#ff9f43"
                page.update()
                return
            if invalid:
                status_text.value = f"已跳过 {invalid} 个失效目录"
                status_text.color = "#ff9f43"
                page.update()
            state.rom_dir = valid[0]
            state.rom_dirs = valid
            btn_icon.name = ft.Icons.CHECK_CIRCLE
            btn_icon.color = ACCENT
            btn_title.value = f"{len(valid)} 个目录"
            btn_sub.value = "批量刮削"
            dir_picker.visible = False
            status_text.visible = True
            page.update()
            go_scrape()
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

        def _show_results(dirs):
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
            _add_section("内部存储", internal)
            if external: _add_section("SD 卡", external)
            other = [(l, p) for l, p in dirs if (l, p) not in internal and (l, p) not in external]
            _add_section("其他", other) if other else None
            dir_picker.visible = True
            batch_btn.visible = len(dir_checks) > 0
            status_text.visible = False

        def show_found(count):
            btn_icon.name = ft.Icons.CHECK_CIRCLE
            btn_icon.color = ACCENT
            btn_title.value = f"发现 {count} 个目录"
            btn_sub.value = "点击选择目标"
            circle_body.bgcolor = CARD_BG
            page.update()

        def show_not_found():
            btn_title.value = "未发现"
            btn_sub.value = "前往设置"
            btn_icon.name = ft.Icons.SETTINGS
            btn_icon.color = ACCENT
            circle_body.bgcolor = CARD_BG
            page.update()

        # 从刮削页返回时恢复 UI
        def _reset_home():
            browse_btn.visible = False
            if scan_state["state"] == "done":
                if _last_scan_dirs:
                    dir_picker.controls.clear()
                    _show_results(_last_scan_dirs)
                else:
                    show_not_found()
                    status_text.visible = True
            page.update()
        _home_reset_fn[0] = _reset_home

        # 鼠标悬浮放大 + 点击缩小
        def on_hover_enter(e):
            if scan_state["state"] == "scanning": return
            circle_body.scale = 1.08
            page.update()

        def on_hover_exit(e):
            circle_body.scale = 1.0
            page.update()

        def scan_with_anim(e):
            if scan_state["state"] == "scanning": return
            if scan_state["state"] == "done":
                on_scan(e)
                return
            circle_body.scale = 0.93
            page.update()
            on_scan(e)  # 同步调用，立即切换 UI
            # 延迟弹回动画
            def _bounce():
                circle_body.scale = 1.0
                page.update()
            threading.Timer(0.15, _bounce).start()

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
                        browse_btn,
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
                picked_path.value = "无读取权限，正在打开系统权限设置..."
                _auto_grant_storage()
                page.update()
            except (FileNotFoundError, NotADirectoryError):
                picked_path.value = "路径不存在，请检查拼写"
                page.update()
            except Exception as ex:
                picked_path.value = f"无法访问: {ex}"
                page.update()

        def do_detect(e):
            _rescan_fn[0] = do_detect  # 从权限/SAF页面返回时自动重扫
            dir_list.controls.clear()
            page.update()

            def _scan_thread():
                def _on_progress(msg):
                    dir_list.controls[-1].value = f"检测中 — {msg}" if dir_list.controls else msg
                    try: page.update()
                    except: pass

                dir_list.controls.append(ft.Text("检测中...", size=12, color=TEXT_DIM))
                try: page.update()
                except: pass

                try:
                    dirs, errors = detect_dirs(on_progress=_on_progress)
                    _last_scan_dirs[:] = dirs
                except Exception as ex:
                    dirs, errors = [], [str(ex)]

                # 原子替换，避免 clear() 中间态闪烁
                new_controls = []
                if errors:
                    for err in errors[:3]:
                        new_controls.append(
                            ft.Text(f"\u26a0 {err}", size=12, color="#ff9f43"))
                if not dirs:
                    new_controls.append(
                        ft.Text("未检测到 ROM 目录", size=12, color=TEXT_DIM) if not errors else
                        ft.Text("无存储权限 \u2192 请到系统设置 \u2192 应用 \u2192 iiSU CN Scraper \u2192 所有文件访问权限", size=12, color="#ff9f43"))
                else:
                    for label, path in dirs:
                        short = path if len(path) <= 55 else "..." + path[-52:]
                        new_controls.append(
                            ft.TextButton(
                                content=ft.Column([
                                    ft.Text(label, size=13, color=TEXT, weight=ft.FontWeight.BOLD),
                                    ft.Text(short, size=10, color=TEXT_DIM),
                                ], spacing=1, alignment=ft.CrossAxisAlignment.START),
                                style=ft.ButtonStyle(
                                    bgcolor=SURFACE, shape=ft.RoundedRectangleBorder(radius=8),
                                    padding=ft.Padding(left=10, top=8, right=10, bottom=8),
                                ),
                                on_click=lambda e, p=path: _set(p),
                            )
                        )
                dir_list.controls = new_controls
                page.update()

            page.run_thread(_scan_thread)

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
                # pop 设置页 → 移除旧 scrape 页 → 推入新 scrape 页
                if len(page.views) > 1:
                    page.views.pop()
                page.views = [v for v in page.views if v.route != "/scrape"]
                page.views.append(build_scrape())
                page.update()

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
                                ft.Button("自动检测", on_click=do_detect,
                                        style=ft.ButtonStyle(bgcolor=SURFACE, color=ACCENT,
                                                             shape=ft.RoundedRectangleBorder(radius=8))),
                                manual_path,
                                ft.Button("确认路径", on_click=apply_manual_path,
                                    style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT,
                                                         shape=ft.RoundedRectangleBorder(radius=8))),
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
        # 支持批量目录。先校验路径有效性
        raw_dirs = state.rom_dirs if state.rom_dirs else [state.rom_dir]
        rom_dirs = []
        skipped_dirs = 0
        for d in raw_dirs:
            d = _normalize_android_path(d)
            if d and os.path.isdir(d):
                rom_dirs.append(d)
            else:
                skipped_dirs += 1
        all_roms = []
        for d in rom_dirs:
            for fname in scan_roms(d):
                all_roms.append((fname, os.path.join(d, fname)))
        total = len(all_roms)
        dir_label = f"{len(rom_dirs)} 目录"
        if skipped_dirs:
            dir_label += f" (跳过 {skipped_dirs} 无效)"
        rom_count = ft.Text(f"{total} ROM ({dir_label})", size=14, color=TEXT)
        status = ft.Text("就绪", size=13, color=TEXT_DIM)
        progress = ft.ProgressBar(value=0, color=ACCENT, bgcolor=SURFACE, expand=True)
        log_list = ft.ListView(spacing=1, expand=True)
        log_controls = []  # 保持引用，用于 add_log

        def add_log(msg):
            log_controls.append(ft.Text(msg, size=11, color=TEXT_DIM))
            log_list.controls = log_controls
            try:
                page.update()
            except RuntimeError:
                pass
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
            checks[fname] = cb
            card = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.VIDEOGAME_ASSET, color=TEXT_DIM, size=18),
                    ft.Text(
                        fname, size=13, color=TEXT,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True,
                    ),
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
            path_map = {fn: fp for fn, fp in all_roms}
            selected = [path_map[f] for f, cb in checks.items() if cb.value and f in path_map]
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
            log_controls.clear()
            log_list.controls = []
            status.value = "初始化..."
            add_log("--- 初始化 API 客户端 ---")
            page.update()

            def _update_ui():
                try:
                    page.update()
                except RuntimeError:
                    pass  # 页面已关闭
                except Exception:
                    # 一次重试
                    try:
                        page.update()
                    except Exception:
                        pass

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
                        # 进度：元数据获取 30%-90%，写入 gamelist 90%-98%
                        progress.value = 0.30 + 0.68 * (i+1)/len(selected)

                    # 写入 gamelist 阶段
                    add_log("--- 写入 gamelist.xml ---")
                    gkeys = list(gamelists.keys())
                    for j, pdir in enumerate(gkeys):
                        gp, rt_existing, _ = gamelists[pdir]
                        progress.value = 0.98 + 0.02 * (j+1)/len(gkeys)
                        status.value = f"写入 {j+1}/{len(gkeys)}"
                        _update_ui()
                        add_log(f"gamelist.xml -> {pdir}")
                    progress.value = 1.0
                    status.value = f"完成 {ok} 个"
                except Exception as ex:
                    status.value = f"错误: {ex}"
                finally:
                    start_btn.disabled = False
                    start_btn.text = "开始刮削"
                    page.update()

            page.run_thread(_run)

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
                        # 日志区 (ListView 自动滚动)
                        ft.Container(
                            content=ft.Column([
                                ft.Text("日志", size=12, weight=ft.FontWeight.BOLD, color=TEXT_DIM),
                                ft.Container(height=4),
                                ft.Container(
                                    content=log_list,
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
    ft.run(main)
