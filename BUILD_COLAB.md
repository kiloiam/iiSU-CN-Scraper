# Google Colab 构建 APK 指南

## 步骤 1：上传项目到 Google Drive

将整个 `iiSU-CN-Scraper` 文件夹压缩为 ZIP，上传到 Google Drive 根目录。

## 步骤 2：打开 Colab

打开 https://colab.research.google.com/ → 新建笔记本 → 逐格运行以下代码：

### 格 1：挂载 Google Drive
```python
from google.colab import drive
drive.mount('/content/drive')
```

### 格 2：解压项目
```python
!cp /content/drive/MyDrive/iiSU-CN-Scraper.zip /content/
!unzip -o /content/iiSU-CN-Scraper.zip -d /content/
%cd /content/iiSU-CN-Scraper
```

### 格 3：安装依赖
```python
!pip install flet requests openai
!flet build apk --project "iiSU CN Scraper" --org com.iisucn.scraper --product "iiSU CN Scraper" --description "Chinese ROM metadata scraper for iiSU frontend" --android-permissions android.permission.INTERNET=true --android-permissions android.permission.READ_EXTERNAL_STORAGE=true --android-permissions android.permission.WRITE_EXTERNAL_STORAGE=true --android-permissions android.permission.READ_MEDIA_IMAGES=true --android-permissions android.permission.READ_MEDIA_VIDEO=true --android-permissions android.permission.MANAGE_EXTERNAL_STORAGE=true
```

### 格 4：下载 APK
```python
from google.colab import files
!ls build/apk/
files.download('build/apk/app-release.apk')
```

## 构建时间

约 5-10 分钟（Colab 国际带宽快）。
