# 构建 APK 指南

## 方式一：Google Colab 云端构建（推荐，无需 Linux 环境）

打开这个 Colab 链接，逐步执行即可得到 APK：
https://colab.research.google.com/gist/

在 Colab 中执行以下步骤：

```python
# 1. 安装 Buildozer
!pip install buildozer cython

# 2. 安装 Android SDK/NDK 依赖
!sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev

# 3. 克隆项目（替换为你的仓库地址）
!git clone https://github.com/YOUR_USER/iiSU-CN-Scraper.git
%cd iiSU-CN-Scraper

# 4. 构建 APK（首次较慢，约15-30分钟）
!buildozer android debug
```

构建完成后，APK 位于 `bin/` 目录下，下载安装到掌机即可。

## 方式二：WSL2 本地构建（Windows 用户）

```bash
# 在 WSL2 中执行
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip \
  autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
  libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev

pip install buildozer cython

cd /mnt/d/Agent/Open-ClaudeCode/iiSU-CN-Scraper
buildozer android debug
```

## 方式三：PC 端先测试 UI（不打包）

```bash
pip install -r requirements.txt
python app_ui.py
```

在电脑上预览 UI 效果，确保配置和流程无误后再打包。

## 安装 APK 到掌机

1. 将 `bin/*.apk` 传输到掌机
2. 在文件管理器中点击 APK 安装
3. 首次打开授予存储权限
4. 填入 API 密钥后即可使用
