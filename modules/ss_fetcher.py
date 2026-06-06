"""ScreenScraper 核心刮削模块：搜索 + 媒体下载 + 速率限制"""

import json
import time
from pathlib import Path

import requests


class ScreenScraperFetcher:
    """ScreenScraper API 封装。支持中→英降级搜索，媒体下载，速率限制。"""

    def __init__(self, devid: str, devpassword: str, softname: str,
                 base_url: str = "https://api.screenscraper.fr/api2",
                 request_delay: float = 1.5,
                 ssid: str = "", sspassword: str = ""):
        self.devid = devid
        self.devpassword = devpassword
        self.softname = softname
        self.ssid = ssid
        self.sspassword = sspassword
        self.base_url = base_url
        self.request_delay = request_delay
        self._last_request = 0.0

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

    def search_game(self, name_zh: str, name_en: str,
                    system_id: int = 0) -> dict | None:
        """降级搜索策略：先中文 → 后英文。返回游戏元数据 dict 或 None。"""
        last_error = None
        # 优先中文搜索
        if name_zh:
            result = self._call_api(name_zh, langue="zh", system_id=system_id)
            if result:
                if "_error" in result:
                    last_error = result["_error"]
                else:
                    return result

        # 降级英文搜索
        if name_en:
            result = self._call_api(name_en, langue="en", system_id=system_id)
            if result:
                if "_error" in result:
                    last_error = result["_error"]
                else:
                    return result

        # 如果有错误信息，返回它以便 UI 显示
        if last_error:
            return {"_error": last_error}
        return None

    def _call_api(self, rom_name: str, langue: str = "zh",
                  system_id: int = 0) -> dict | None:
        """调用 jeuInfos.php 搜索游戏。"""
        self._rate_limit()

        params = {
            "devid": self.devid,
            "devpassword": self.devpassword,
            "softname": self.softname,
            "output": "json",
            "romnom": rom_name,
            "langue": langue,
        }
        # 付费账号凭证
        if self.ssid:
            params["ssid"] = self.ssid
        if self.sspassword:
            params["sspassword"] = self.sspassword
        # systemeid 提高匹配率
        if system_id:
            params["systemeid"] = system_id

        url = f"{self.base_url}/jeuInfos.php"
        try:
            resp = requests.get(url, params=params, timeout=15)
        except requests.ConnectionError as e:
            return {"_error": f"SS连接失败(DNS/网络): {e}"}
        except requests.Timeout:
            return {"_error": "SS超时(15s) — 检查网络"}
        except requests.RequestException as e:
            return {"_error": f"SS请求异常: {type(e).__name__}: {str(e)[:80]}"}

        # 检查 HTTP 状态
        if resp.status_code >= 500:
            return {"_error": f"SS服务器错误({resp.status_code})"}
        if resp.status_code >= 400:
            text = resp.text[:120]
            return {"_error": f"SS拒绝({resp.status_code}): {text}"}

        # 解析 JSON
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return {"_error": f"SS返回非JSON: {resp.text[:80]}"}

        # 检查 API 级别错误
        if data.get("header", {}).get("success") != "true":
            error_msg = data.get("header", {}).get("error", "未知")
            if "not found" in error_msg.lower() or "no result" in error_msg.lower():
                return None  # 正常未匹配
            return {"_error": f"SS错误: {error_msg}"}
        return None

        jeu = data.get("response", {}).get("jeu")
        if not jeu:
            return None

        # 处理 jeu 为列表的情况（多个匹配结果，取第一个）
        if isinstance(jeu, list):
            jeu = jeu[0]

        return self._parse_game_info(jeu, data.get("response", {}))

    def _parse_game_info(self, jeu: dict, response: dict) -> dict:
        """解析 SS 返回的游戏数据为统一格式。"""
        # 名称
        noms = jeu.get("noms") or []
        names_by_lang = {}
        for n in noms:
            region = n.get("region", "")
            text = n.get("text", "")
            if region and text:
                names_by_lang[region] = text

        # 描述
        synopsis_list = jeu.get("synopsis") or []
        desc_zh = ""
        desc_en = ""
        for s in synopsis_list:
            if s.get("langue") == "zh":
                desc_zh = s.get("text", "")
            elif s.get("langue") == "en":
                desc_en = s.get("text", "")
        desc = desc_zh or desc_en or ""

        # 日期
        dates = jeu.get("dates") or []
        release_date = ""
        for d in dates:
            if d.get("region") in ("ss", "jp", "us", "eu", "wor"):
                release_date = d.get("text", "")
                break
        if not release_date and dates:
            release_date = dates[0].get("text", "")

        # 媒体资源 URL
        medias = jeu.get("medias") or []
        media_urls = {}
        for m in medias:
            mtype = m.get("type", "")
            if mtype in ("box-2D", "box-texture-2D", "wheel", "wheel-steel", "ss", "sstitle", "video"):
                if mtype not in media_urls or not media_urls[mtype]:
                    # 拼接完整 URL
                    parent = m.get("parent", m)
                    url = m.get("url", "")
                    if url and not url.startswith("http"):
                        # 使用 response 中的服务器地址
                        serveurs = response.get("serveurs", [])
                        if serveurs:
                            base_media = serveurs[0].get("url", "")
                            url = base_media.rstrip("/") + "/" + url.lstrip("/")
                    if url:
                        media_urls[mtype] = url

        # 开发商 / 发行商
        developer = (jeu.get("developpeur") or {}).get("text", "")
        publisher = (jeu.get("editeur") or {}).get("text", "")
        genre_list = jeu.get("genres") or []
        genre = ", ".join(
            g.get("nom_eu", g.get("nom_en", g.get("nom_ss", "")))
            for g in genre_list
            if g.get("nom_eu") or g.get("nom_en") or g.get("nom_ss")
        )
        players = (jeu.get("joueurs") or {}).get("text", "")

        return {
            "name_zh": names_by_lang.get("zh", names_by_lang.get("cn", "")),
            "name_en": names_by_lang.get("en", names_by_lang.get("ss", "")),
            "desc": desc,
            "developer": developer,
            "publisher": publisher,
            "genre": genre,
            "players": players,
            "release_date": release_date,
            "media_urls": media_urls,
        }

    # ------------------------------------------------------------------
    # 媒体下载
    # ------------------------------------------------------------------

    def download_cover(self, media_urls: dict, dest_path: Path) -> bool:
        """下载 2D 封面到指定路径。成功返回 True。"""
        url = media_urls.get("box-2D") or media_urls.get("box-texture-2D")
        if not url:
            return False
        return self._download_file(url, dest_path)

    def download_marquee(self, media_urls: dict, dest_path: Path) -> bool:
        """下载 Logo/Wheel 到指定路径。成功返回 True。"""
        url = media_urls.get("wheel") or media_urls.get("wheel-steel")
        if not url:
            return False
        return self._download_file(url, dest_path)

    def _download_file(self, url: str, dest_path: Path) -> bool:
        """通用文件下载。"""
        self._rate_limit()
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return True
        except requests.RequestException as e:
            print(f"  [下载失败] {url} → {e}")
            return False

    # ------------------------------------------------------------------
    # 速率限制
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """确保连续请求之间有足够延迟。"""
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request = time.monotonic()
