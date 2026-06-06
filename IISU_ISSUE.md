# iiSU Issue: iiSU-CN-Scraper — 中文 ROM 元数据刮削器

## English

### Summary
`iiSU-CN-Scraper` is a companion APK for iiSU that solves a critical pain point for Chinese retro gamers: **ROM files with garbled Chinese filenames** (containing hanization group tags, version numbers, language labels like `[某某汉化组] 最终幻想VI v1.2 (简繁中文).gba`) that traditional scrapers (ScreenScraper, TheGamesDB) cannot match by hash or filename.

### How it works
```
Garbled ROM filename → AI semantic cleaning (LLM) → Standard game name
    → Bangumi (bgm.tv) Chinese metadata + covers
    → ES-DE standard gamelist.xml + downloaded_media/
    → iiSU reads via "Link ES-DE Metadata" in ROM Import
```

### Key Features
- **Zero ROM modification** — never touches original ROM files
- **Chinese-first** — uses Bangumi (bgm.tv) for native Chinese game names, descriptions, ratings
- **Auto-detect** — scans Android storage for ROM directories, including user-created custom paths
- **Multi-select batch scraping** — scrape GBA + SFC + PS1 all at once
- **Incremental update** — only scrapes new ROMs, skips existing entries
- **ES-DE compatible** — generates standard `gamelist.xml` with relative paths
- **Open source** — free to use, modify, and redistribute

### Tech Stack
- Python/Flet (Flutter) → Android APK
- Bangumi API (free, no key required) → Chinese game metadata
- OpenAI-compatible LLM API → filename semantic cleaning
- TheGamesDB API → English fallback source

### Why this matters for iiSU
iiSU already supports "Link ES-DE Metadata" in ROM Import. This tool generates that metadata automatically for Chinese ROMs that would otherwise have no matches. It fills a gap in the ecosystem that ScreenScraper and other English-first scrapers leave open.

---

## 中文

### 概述
`iiSU-CN-Scraper` 是一款 iiSU 配套 APK，解决中国复古游戏玩家的核心痛点：**ROM 文件名杂乱**（含汉化组标签、版本号、语言标记等），传统刮削器（ScreenScraper、TheGamesDB）无法通过哈希或文件名匹配。

### 工作原理
```
乱码文件名 → AI 语义清洗 (LLM) → 标准游戏名
    → Bangumi (bgm.tv) 中文资料 + 封面
    → ES-DE 标准 gamelist.xml + downloaded_media/
    → iiSU 通过 "链接 ES-DE 元数据" 读取
```

### 核心特性
- **零 ROM 修改** — 绝不触动原始 ROM 文件
- **中文优先** — 使用 Bangumi (bgm.tv) 获取原生中文名称、简介、评分、封面
- **自动检测** — 扫描安卓存储中的 ROM 目录，包括玩家自建路径
- **多选批量刮削** — 同时刮削 GBA + SFC + PS1 等多个目录
- **增量更新** — 只处理新 ROM，跳过已刮削条目
- **ES-DE 兼容** — 生成标准 `gamelist.xml`，相对路径
- **开源免费** — 自由使用、修改、分发

### 技术栈
- Python/Flet (Flutter) → Android APK
- Bangumi API（免费，无需 Key） → 中文游戏资料
- OpenAI 兼容 LLM API → 文件名语义清洗
- TheGamesDB API → 英文备用数据源

### 对 iiSU 的意义
iiSU 的 ROM 导入已支持"链接 ES-DE 元数据"。此工具为中文 ROM 自动生成这些元数据，填补了 ScreenScraper 等英文优先刮削器留下的生态空白。

---
**Project Repository:** [GitHub link to be added]
**APK Download:** [Release link to be added]
