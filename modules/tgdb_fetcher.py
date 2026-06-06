"""TheGamesDB 刮削模块 — 免费即时 API"""

import time
import requests
from pathlib import Path

BASE = "https://api.thegamesdb.net/v1"


class TGDBFetcher:
    """TheGamesDB API v1 封装。"""

    def __init__(self, api_key: str, request_delay: float = 1.0):
        self.api_key = api_key
        self.request_delay = request_delay
        self._last = 0.0

    @staticmethod
    def _similar(a: str, b: str) -> float:
        """简单的名称相似度检查"""
        a = a.lower().strip()
        b = b.lower().strip()
        if not a or not b: return 0
        if a == b: return 1.0
        # 检查一个是否包含另一个
        if a in b or b in a: return 0.7
        # 单词重叠
        wa = set(a.split())
        wb = set(b.split())
        if wa and wb:
            return len(wa & wb) / max(len(wa), len(wb))
        return 0

    def _rate(self):
        now = time.monotonic()
        gap = now - self._last
        if gap < self.request_delay:
            time.sleep(self.request_delay - gap)
        self._last = time.monotonic()

    # ------------------------------------------------------------------
    def search_game(self, name_zh: str, name_en: str) -> dict | None:
        """搜索游戏，返回统一格式元数据。"""
        # 尝试中文名 → 英文名
        for name in (name_zh, name_en):
            if not name: continue
            result = self._search(name)
            if result:
                return result
        return None

    def _search(self, name: str) -> dict | None:
        self._rate()
        params = {
            "apikey": self.api_key,
            "name": name,
            "fields": "players,publishers,genres,overview,developers,releasedate,boxart",
        }
        try:
            resp = requests.get(f"{BASE}/Games/ByGameName", params=params, timeout=15)
        except requests.RequestException as e:
            return {"_error": f"TGDB网络: {e}"}

        if resp.status_code >= 400:
            try:
                err = resp.json().get("status", str(resp.status_code))
            except:
                err = resp.text[:100]
            return {"_error": f"TGDB错误({resp.status_code}): {err}"}

        try:
            data = resp.json()
        except:
            return {"_error": "TGDB返回非JSON"}

        games = data.get("data", {}).get("games", [])
        if not games:
            return None

        # 取第一个匹配，检查相似度
        g = games[0]
        result_name = g.get("game_title", "")
        if self._similar(name, result_name) < 0.3:
            # 名称差异太大，可能是错误匹配
            return None
        includes = data.get("include", {})

        # 封面 URL
        cover_url = ""
        boxart_data = includes.get("boxart", {})
        if "data" in boxart_data:
            for key, art in boxart_data["data"].items():
                if art.get("side") == "front":
                    cover_url = art.get("url", art.get("filename", ""))
                    break
            if not cover_url and boxart_data["data"]:
                first = list(boxart_data["data"].values())[0]
                cover_url = first.get("url", first.get("filename", ""))

        # 简介
        overview = g.get("overview", "")

        # 日期
        release_date = g.get("release_date", "")

        # 开发商/发行商
        devs = includes.get("developers", {}).get("data", {})
        developer = ""
        if devs:
            developer = list(devs.values())[0].get("name", "")

        pubs = includes.get("publishers", {}).get("data", {})
        publisher = ""
        if pubs:
            publisher = list(pubs.values())[0].get("name", "")

        # 类型
        genres_data = includes.get("genres", {}).get("data", {})
        genre = ", ".join(v.get("name", "") for v in genres_data.values())

        # 玩家人数
        players = g.get("players", "")

        return {
            "name_en": g.get("game_title", ""),
            "name_zh": "",  # TGDB 英文为主，中文名由 LLM 提供
            "desc": overview,
            "developer": developer,
            "publisher": publisher,
            "genre": genre,
            "players": str(players) if players else "",
            "release_date": release_date,
            "cover_url": cover_url,
        }

    # ------------------------------------------------------------------
    # 媒体下载
    # ------------------------------------------------------------------

    def download_cover(self, meta: dict, dest: Path) -> bool:
        url = meta.get("cover_url", "")
        if not url:
            return False
        self._rate()
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return True
        except requests.RequestException:
            return False

    def download_marquee(self, meta: dict, dest: Path) -> bool:
        """TGDB 不提供 wheel/logo，返回 False"""
        return False
