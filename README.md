# iiSU-CN-Scraper

中文 ROM 刮削 APK — 专为搭载 iiSU 前端的安卓掌机开发 (AYN Thor 等)。

## 解决的问题

国内 ROM 文件名通常包含汉化组标签、版本号、语言标记等杂乱信息，导致 ScreenScraper 无法匹配。本工具作为中间件：

```
乱码文件名 → LLM 语义清洗 → ScreenScraper 搜索 → gamelist.xml + 本地媒体
```

**绝不修改原始 ROM 文件。**

---

## 快速开始

### 安装 APK 到掌机

1. 下载 `iiSU-CN-Scraper-*.apk` 安装到掌机
2. 首次打开授予存储权限
3. 填入 API 密钥

### 使用流程

```
打开 App
  → 自动检测 iiSU/ROM 目录 (或手动输入路径)
  → 填入 LLM 和 ScreenScraper 密钥
  → 扫描 ROM，勾选要刮削的文件
  → 点击「开始刮削」
  → 等待完成，gamelist.xml 自动生成在原 ROM 目录
```

---

## 构建 APK

详见 [BUILD_APK.md](./BUILD_APK.md)

- **推荐：Google Colab 云端免费构建**（无需 Linux）
- WSL2 本地构建
- PC 端 `python app_ui.py` 预览 UI

---

## PC 命令行模式（开发/调试用）

```bash
pip install -r requirements.txt
python iisu_cn_scraper.py --config config.json          # 正式刮削
python iisu_cn_scraper.py --config config.json --dry-run # 仅分析
```

---

## 输出结构

```
/sdcard/ROMs/GBA/
├── gamelist.xml              ← 自动生成/更新
└── downloaded_media/
    ├── covers/               ← box-2D 封面 (.png)
    └── marquees/             ← wheel logo (.png)
```

## iiSU 兼容性

生成的 `gamelist.xml` 遵循 **ES-DE / EmulationStation** 标准，iiSU 导入 ES-DE Metadata 即可完美识别。

## API 注册

- **LLM**：推荐 DeepSeek（`api.deepseek.com`，极便宜）
- **ScreenScraper**：[screenscraper.fr](https://www.screenscraper.fr) 注册免费账号
