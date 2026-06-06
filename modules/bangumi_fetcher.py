"""Bangumi (bgm.tv) 中文刮削模块 — 免费、无需 API Key"""

import time
import urllib.parse

import requests
from pathlib import Path


class BangumiFetcher:
    """Bangumi API 封装 — 中文游戏数据库。"""

    BASE = "https://api.bgm.tv"

    def __init__(self, request_delay: float = 1.0):
        self.request_delay = request_delay
        self._last = 0.0

    def _rate(self):
        now = time.monotonic()
        gap = now - self._last
        if gap < self.request_delay:
            time.sleep(self.request_delay - gap)
        self._last = time.monotonic()

    # ------------------------------------------------------------------
    def search_game(self, name_zh: str, name_en: str = "") -> dict | None:
        """搜索游戏，优先中文名 → 英文名。"""
        for name in (name_zh, name_en):
            if not name: continue
            result = self._search(name)
            if result:
                return result
        return None

    def _search(self, name: str) -> dict | None:
        self._rate()
        try:
            resp = requests.get(
                f"{self.BASE}/search/subject/{urllib.parse.quote(name)}",
                params={"type": 4, "responseGroup": "large"},
                headers={"User-Agent": "iiSU-CN-Scraper/1.0"},
                timeout=15,
            )
        except requests.RequestException as e:
            return {"_error": f"Bangumi网络: {e}"}

        if resp.status_code >= 400:
            return {"_error": f"Bangumi错误({resp.status_code})"}

        try:
            data = resp.json()
        except:
            return {"_error": "Bangumi返回非JSON"}

        items = data.get("list", [])
        if not items:
            return None

        item = items[0]

        # 封面图
        images = item.get("images", {})
        cover_url = images.get("large", images.get("common", ""))

        # 评分
        rating = item.get("rating", {}).get("score", "")

        return {
            "name_zh": item.get("name_cn", ""),
            "name_en": item.get("name", ""),  # 原名(日文/英文)
            "desc": item.get("summary", ""),
            "developer": "",  # Bangumi 搜索 API 不返回开发商
            "publisher": "",
            "genre": "",
            "players": "",
            "release_date": item.get("air_date", ""),  # 发售日
            "rating": str(rating) if rating else "",
            "cover_url": cover_url,
        }

    # ------------------------------------------------------------------
    def download_cover(self, meta: dict, dest: Path) -> bool:
        url = meta.get("cover_url", "")
        if not url:
            return False
        # Bangumi 图片可能需要 referer
        if url.startswith("http:"):
            url = url.replace("http:", "https:", 1)
        self._rate()
        try:
            resp = requests.get(url, timeout=30,
                headers={"User-Agent": "iiSU-CN-Scraper/1.0", "Referer": "https://bgm.tv/"})
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return True
        except requests.RequestException:
            return False
