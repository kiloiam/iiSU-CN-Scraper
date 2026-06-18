# iiSU-CN-Scraper

中文 ROM 刮削工具 — Android 掌机 + Windows/macOS 桌面端通用。

## 解决的问题

国内 ROM 文件名通常包含汉化组标签、版本号、语言标记等杂乱信息，导致刮削器无法匹配。本工具：

```
乱码文件名 → LLM 语义清洗 → Bangumi (中文) / TGDB (英文) → gamelist.xml + 封面
```

**绝不修改原始 ROM 文件。**

---

## 快速开始

### Windows 桌面端

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动
双击 启动_iiSU.bat
# 或
python main.py
```

首次使用：设置页填入 LLM API Key（推荐 DeepSeek），点击扫描 → 选择 ROM 目录 → 开始刮削。

### Android 掌机

1. 下载 [最新 APK](../../releases/latest)
2. 安装后授予「所有文件访问」权限
3. 填入 API 密钥即可使用

---

## 数据源

| 数据源 | 用途 | 免费额度 |
|--------|------|----------|
| **Bangumi** | 中文游戏信息（首选） | 免费 |
| **TheGamesDB** | 英文备用补充 | 免费 |
| **LLM** | ROM 文件名语义清洗 | 按量付费（推荐 DeepSeek，极便宜） |

---

## 使用流程

```
打开 App
  → 自动扫描 ROM 目录（桌面端可手动浏览文件夹）
  → 填入 LLM API Key
  → 勾选要刮削的 ROM
  → 点击「开始刮削」
  → gamelist.xml + 封面自动生成在原 ROM 目录
```

---

## 输出结构

```
ROMs/GBA/
├── gamelist.xml              ← 自动生成/更新
└── downloaded_media/
    └── covers/               ← 封面 (.png)
```

---

## iiSU 兼容性

生成的 `gamelist.xml` 遵循 **ES-DE / EmulationStation** 标准，iiSU 可直接识别。

---

## 构建 APK

GitHub Actions 自动构建：[Actions](../../actions) → 最新 run → Artifacts 下载。

本地构建详见 [BUILD_APK.md](./BUILD_APK.md)。

---

## 命令行模式（开发/调试）

```bash
pip install -r requirements.txt
python iisu_cn_scraper.py --config config.json          # 正式刮削
python iisu_cn_scraper.py --config config.json --dry-run # 仅分析
```
