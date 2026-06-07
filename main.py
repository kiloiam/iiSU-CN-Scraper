#!/usr/bin/env python3
"""iiSU-CN-Scraper — Android Kivy App

iiSU 设计风格：暗紫极简 + 圆形 Hero Button
独立 KV 文件：iisuapp.kv
"""

import os, sys, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.textinput import TextInput

from modules.llm_client import LLMClient
from modules.llm_normalizer import normalize_rom_name, translate_desc
from modules.ss_fetcher import ScreenScraperFetcher
from modules.bangumi_fetcher import BangumiFetcher
from modules.tgdb_fetcher import TGDBFetcher
from modules.xml_builder import (
    load_existing_gamelist, build_game_element, write_gamelist,
)

# ======================================================================
# 中文字体
# ======================================================================
def _cn_font():
    if sys.platform == "win32":
        for p in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msjh.ttc"]:
            if os.path.exists(p): return p
    elif sys.platform == "linux":
        for p in ["/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                   "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"]:
            if os.path.exists(p): return p
    return None

CN = _cn_font()
if CN:
    LabelBase.register("CNSans", CN)
    FONT = "CNSans"
else:
    FONT = "Roboto"

# ======================================================================
# iiSU 配色 (Python 侧使用)
# ======================================================================
BG      = (0.063, 0.063, 0.090, 1)
SURFACE = (0.094, 0.094, 0.125, 1)
CARD    = (0.125, 0.125, 0.157, 1)
ACCENT  = (0.49,  0.23,  0.93,  1)
TEXT    = (0.91,  0.91,  0.91,  1)
TEXT_DIM = (0.55, 0.55,  0.60,  1)

# ======================================================================
# ROM 检测
# ======================================================================
ROM_ROOTS = [
    "/storage/emulated/0/ROMs", "/storage/emulated/0/roms",
    "/sdcard/ROMs", "/sdcard/roms",
    "/storage/emulated/0/Emulation/roms",
]
ROM_EXTS = {
    ".gba", ".gbc", ".gb", ".nds", ".3ds", ".n64", ".z64", ".v64",
    ".nes", ".fds", ".sfc", ".smc", ".smd", ".md", ".gen", ".32x",
    ".gg", ".sms", ".pce", ".cue", ".bin", ".iso", ".cso", ".chd",
    ".pbp", ".wbfs", ".wad", ".nsp", ".xci", ".nsz", ".zip", ".7z",
}
SYSTEMS = {"gba":"GBA","gbc":"GBC","gb":"GB","nds":"NDS","3ds":"3DS",
           "n64":"N64","nes":"NES","fds":"FC","sfc":"SFC","smc":"SFC",
           "md":"MD","gen":"MD","smd":"MD","32x":"32X","gg":"GG","sms":"SMS",
           "pce":"PCE","psp":"PSP","ps1":"PS1","ps2":"PS2","dc":"DC",
           "ngc":"NGC","wii":"Wii","wiiu":"WiiU","nsp":"Switch","xci":"Switch"}

def _sys(dirname):
    low = dirname.lower().replace(" ","").replace("-","").replace("_","")
    for k,v in SYSTEMS.items():
        if k in low: return v
    return dirname[:12]

def detect_dirs():
    found = []
    for root in ROM_ROOTS:
        if not os.path.isdir(root): continue
        try:
            for entry in sorted(os.listdir(root)):
                full = os.path.join(root, entry)
                if not os.path.isdir(full): continue
                try:
                    n = sum(1 for f in os.listdir(full) if f.lower().endswith(tuple(ROM_EXTS)))
                    if n: found.append((f"{_sys(entry)}  ({n} ROM)", full, n))
                except: pass
        except: pass
    return found

def scan_roms(path):
    if not os.path.isdir(path): return []
    try:
        return sorted(
            (e, os.path.join(path, e)) for e in os.listdir(path)
            if os.path.isfile(os.path.join(path, e)) and e.lower().endswith(tuple(ROM_EXTS))
        )
    except: return []

def _slug(s):
    k = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-"
    return "".join(c if c in k else "_" for c in s)[:80]

# ======================================================================
# 屏幕类
# ======================================================================

class HomeScreen(Screen):
    """Home screen with large circular scan button"""

    def on_enter(self):
        self.ids.home_status.text = "点击圆形按钮自动检测 ROM 目录"
        self.ids.circle_sub.text = "Directory"

    def detect_press(self):
        self.ids.circle_sub.text = "..."

    def detect_release(self):
        self.ids.circle_sub.text = "检测中..."
        Clock.schedule_once(self._run_detect, 0.5)

    def _run_detect(self, dt):
        app = App.get_running_app()
        dirs = detect_dirs()
        if dirs:
            self._show_dir_modal(dirs)
            self.ids.home_status.text = f"检测到 {len(dirs)} 个 ROM 目录"
            self.ids.circle_sub.text = "已检测"
        else:
            self.ids.home_status.text = "未检测到 ROM 目录"
            self.ids.circle_sub.text = "去设置"
            Clock.schedule_once(lambda _: setattr(self.manager, "current", "settings"), 1.0)

    def _show_dir_modal(self, dirs):
        modal = ModalView(size_hint=(0.88, None), height=dp(360),
                          background_color=[0,0,0,0], auto_dismiss=True)
        content = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(14))
        content.canvas.before.clear()
        with content.canvas.before:
            from kivy.graphics import Color, Rectangle
            Color(*BG)
            Rectangle(pos=content.pos, size=content.size)

        # 标题
        hdr = BoxLayout(size_hint_y=None, height=dp(40))
        hdr.add_widget(Label(text="选择 ROM 目录", font_size="16sp", bold=True,
                             color=TEXT, halign="left", size_hint_x=0.7, font_name=FONT))
        dismiss_btn = Button(text="取消", size_hint_x=0.3, background_normal="",
                             background_color=[0,0,0,0], color=ACCENT, font_size="13sp",
                             font_name=FONT)
        dismiss_btn.bind(on_release=modal.dismiss)
        hdr.add_widget(dismiss_btn)
        content.add_widget(hdr)

        # 目录列表
        sv = ScrollView(do_scroll_x=False)
        gl = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        gl.bind(minimum_height=gl.setter("height"))
        for label, path, count in dirs:
            btn = Button(text=f"[b]{label}[/b]\n[size=11sp]{path}[/size]",
                         size_hint_y=None, height=dp(60), markup=True,
                         background_normal="", background_color=SURFACE,
                         color=TEXT, font_size="13sp", font_name=FONT,
                         halign="left", valign="middle", padding=[dp(16), dp(8)])
            btn.bind(on_release=lambda _, p=path: self._select_dir(p, modal))
            gl.add_widget(btn)
        sv.add_widget(gl)
        content.add_widget(sv)
        modal.add_widget(content)
        modal.open()

    def _select_dir(self, path, modal):
        app = App.get_running_app()
        app.rom_dir = path
        self.ids.home_status.text = path
        self.ids.circle_sub.text = "已选择"
        modal.dismiss()
        Clock.schedule_once(lambda dt: setattr(self.manager, "current", "scrape"), 0.2)

    def open_settings(self):
        app = App.get_running_app()
        # 先确保 rom_dir 不为空，避免设置页引用问题
        self.manager.current = "settings"


class SettingsScreen(Screen):
    """设置页 — ROM 路径 + API"""

    def on_enter(self):
        app = App.get_running_app()
        self.ids.set_llm_url.text = app.llm_base_url
        self.ids.set_llm_key.text = app.llm_api_key
        self.ids.set_llm_model.text = app.llm_model
        self.ids.set_ss_id.text = app.ss_devid
        self.ids.set_ss_pw.text = app.ss_devpw
        self.ids.set_tgdb_key.text = app.tgdb_api_key

    def auto_detect(self):
        self.ids.set_dir_list.clear_widgets()
        dirs = detect_dirs()
        if not dirs:
            self.ids.set_dir_list.add_widget(Label(
                text="未检测到目录", size_hint_y=None, height=dp(30),
                font_size="12sp", color=TEXT_DIM, font_name=FONT))
            return
        for label, path, count in dirs:
            btn = Button(text=f"[b]{label}[/b]  {path}", size_hint_y=None, height=dp(44),
                         markup=True, background_normal="", background_color=CARD,
                         color=TEXT, font_size="12sp", font_name=FONT,
                         halign="left", valign="middle", padding=[dp(12), dp(6)])
            btn.bind(on_release=lambda _, p=path: self._set_dir(p))
            self.ids.set_dir_list.add_widget(btn)

    def _set_dir(self, path):
        App.get_running_app().rom_dir = path
        self.ids.set_manual_path.text = path

    def apply_manual(self):
        path = self.ids.set_manual_path.text.strip()
        if path and os.path.isdir(path):
            App.get_running_app().rom_dir = path

    def on_leave(self):
        app = App.get_running_app()
        app.llm_base_url = self.ids.set_llm_url.text.strip()
        app.llm_api_key = self.ids.set_llm_key.text.strip()
        app.llm_model = self.ids.set_llm_model.text.strip()
        app.ss_devid = self.ids.set_ss_id.text.strip()
        app.ss_devpw = self.ids.set_ss_pw.text.strip()
        app.tgdb_api_key = self.ids.set_tgdb_key.text.strip()


class ScrapeScreen(Screen):
    """刮削页 — ROM list + progress"""

    _thread = None
    _rom_paths = []

    def on_enter(self):
        Clock.schedule_once(self._do_scan, 0.1)

    def _do_scan(self, dt):
        app = App.get_running_app()
        roms = scan_roms(app.rom_dir)
        self._rom_paths = [p for _, p in roms]
        self.ids.rom_count.text = f"{len(roms)} ROM"
        self.ids.rom_list.clear_widgets()
        if not roms:
            self.ids.status_label.text = "没有 ROM 文件"
            return
        for fname, _ in roms:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(44))
            row.add_widget(Label(
                text=fname[:55], size_hint_x=0.85,
                font_size="12sp", color=TEXT, font_name=FONT,
                halign="left", valign="middle"))
            row.add_widget(CheckBox(size_hint_x=0.15, active=True))
            self.ids.rom_list.add_widget(row)

    def start_scrape(self):
        if self._thread and self._thread.is_alive(): return
        self.ids.start_btn.disabled = True
        self.ids.start_btn.text = "刮削中..."
        self.ids.progress.value = 0
        self.ids.log_label.text = ""
        self._thread = threading.Thread(target=self._scrape, daemon=True)
        self._thread.start()

    def _selected(self):
        res = []
        children = list(self.ids.rom_list.children)[::-1]
        for i, c in enumerate(children):
            if isinstance(c, BoxLayout) and i < len(self._rom_paths):
                if isinstance(c.children[0], CheckBox) and c.children[0].active:
                    res.append(self._rom_paths[i])
        return res

    def _scrape(self):
        app = App.get_running_app()
        roms = self._selected()
        if not roms:
            Clock.schedule_once(lambda _: self._ui("未选中 ROM", 0))
            Clock.schedule_once(lambda _: self._reset()); return

        Clock.schedule_once(lambda _: self._ui("AI 清洗中...", 5))
        try:
            cl = LLMClient(base_url=app.llm_base_url, api_key=app.llm_api_key)
            lm = {}
            for i, p in enumerate(roms):
                pc = 5 + int(i / len(roms) * 25)
                fn = os.path.basename(p)
                Clock.schedule_once(lambda _, n=fn, v=pc: self._ui(f"清洗: {n[:40]}", v))
                try: lm[fn] = normalize_rom_name(cl, app.llm_model, fn)
                except: lm[fn] = {"standard_zh": "", "standard_en": ""}
        except Exception as e:
            Clock.schedule_once(lambda _: self._ui(f"LLM 错误: {e}", 0))
            Clock.schedule_once(lambda _: self._reset()); return

        Clock.schedule_once(lambda _: self._ui("刮削中...", 30))
        bgm = BangumiFetcher()
        ss = ScreenScraperFetcher(app.ss_devid, app.ss_devpw, "iiSU-CN-Scraper") if app.ss_devid else None
        tgdb = TGDBFetcher(app.tgdb_api_key) if app.tgdb_api_key else None
        gp = Path(app.rom_dir) / "gamelist.xml"
        rt, ex = load_existing_gamelist(gp)
        cd = Path(app.rom_dir) / "downloaded_media" / "covers"
        md = Path(app.rom_dir) / "downloaded_media" / "marquees"
        ok = 0

        for i, rp in enumerate(roms):
            pc = 30 + int(i / len(roms) * 65); fn = os.path.basename(rp); rel = "./" + fn
            Clock.schedule_once(lambda _, n=fn, v=pc: self._ui(n[:50], v))
            if rel in ex:
                Clock.schedule_once(lambda _, n=fn[:40]: self._log(f"跳过: {n}")); continue
            ll = lm.get(fn, {"standard_zh": "", "standard_en": "", "desc_zh": ""})
            if not zh and not en:
                Clock.schedule_once(lambda _, n=fn[:40]: self._log(f"无名称: {n}")); continue
            zh = ll.get("standard_zh", "")
            en = ll.get("standard_en", "")
            meta = bgm.search_game(zh, en)
            source = ""
            if meta and "_error" not in meta:
                source = "Bangumi"
            if not meta and ss:
                meta = ss.search_game(zh, en)
                if meta and "_error" not in meta:
                    source = "ScreenScraper"
            if not meta and tgdb:
                meta = tgdb.search_game(zh, en)
                if meta and "_error" not in meta:
                    source = "TGDB"
            if not meta:
                Clock.schedule_once(lambda _, n=fn[:40]: self._log(f"未匹配: {n}")); continue
            sf = _slug(Path(fn).stem)
            cr = ""; mr = ""
            if source == "ScreenScraper" and ss:
                if ss.download_cover(meta.get("media_urls", {}), cd / f"{sf}-image.png"):
                    cr = f"./downloaded_media/covers/{sf}-image.png"
                if ss.download_marquee(meta.get("media_urls", {}), md / f"{sf}-marquee.png"):
                    mr = f"./downloaded_media/marquees/{sf}-marquee.png"
            elif source == "Bangumi":
                if bgm.download_cover(meta, cd / f"{sf}-image.png"):
                    cr = f"./downloaded_media/covers/{sf}-image.png"
            elif source == "TGDB" and tgdb:
                if tgdb.download_cover(meta, cd / f"{sf}-image.png"):
                    cr = f"./downloaded_media/covers/{sf}-image.png"
            desc = meta.get("desc", "")
            if source == "TGDB" and desc and cl:
                try:
                    zh_desc = translate_desc(cl, app.llm_model, desc)
                    if zh_desc: desc = zh_desc
                except: pass
            entry = {
                "name": meta.get("name_zh") or ll.get("standard_zh", "") or meta.get("name_en", Path(fn).stem),
                "desc": desc or "", "image": cr, "marquee": mr,
                "developer": meta.get("developer",""), "publisher": meta.get("publisher",""),
                "rating": meta.get("rating",""),
                "genre": meta.get("genre",""), "players": meta.get("players",""),
                "release_date": meta.get("release_date",""), "rating": "",
            }
            ge = build_game_element(rel, entry)
            if rel in ex: rt.remove(ex[rel])
            rt.append(ge); ex[rel] = ge
            write_gamelist(gp, rt); ok += 1
            Clock.schedule_once(lambda _, n=fn[:40]: self._log(f"完成: {n}"))

        Clock.schedule_once(lambda _: self._ui(f"完成 {ok} 个", 100))
        Clock.schedule_once(lambda _: self._log(f"gamelist.xml -> {gp}"))
        Clock.schedule_once(lambda _: self._reset())

    def _ui(self, msg, pct):
        self.ids.status_label.text = msg
        self.ids.progress.value = pct

    def _log(self, msg):
        self.ids.log_label.text = (self.ids.log_label.text + "\n" + msg).strip()

    def _reset(self):
        self.ids.start_btn.disabled = False
        self.ids.start_btn.text = "开始刮削"


# ======================================================================
# App
# ======================================================================
class IISUApp(App):
    rom_dir = ""
    llm_base_url = "https://api.deepseek.com/v1"
    llm_api_key = ""
    llm_model = "deepseek-chat"
    ss_devid = ""
    ss_devpw = ""
    tgdb_api_key = ""
    font_name = FONT

    def build(self):
        self.title = "iiSU CN Scraper"
        Window.clearcolor = BG
        root = Builder.load_file(os.path.join(os.path.dirname(__file__), "iisuapp.kv"))
        sm = ScreenManager()
        sm.add_widget(HomeScreen(name="home"))
        sm.add_widget(SettingsScreen(name="settings"))
        sm.add_widget(ScrapeScreen(name="scrape"))
        # Kivy auto-loads iisuapp.kv for the IISUApp class; Builder.load_file is extra insurance
        return sm


if __name__ == "__main__":
    IISUApp().run()
