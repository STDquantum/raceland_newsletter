# Raceland Newsletter 周报网站

本项目将 Raceland Newsletter 按 ISO 周整理为图片周报，并生成可部署到 GitHub Pages 的静态图库。网站支持按周浏览、连续阅读、双页阅读和 OCR 文字搜索。

## 日常更新

双击 `发布并部署周报.bat`，或在本目录运行：

```powershell
.\发布并部署周报.bat
```

该命令默认处理**当周**（`current`）：采集或渲染周报图片、执行 OCR，并更新网站索引文件。它不会执行 Git 提交或推送，更新完成后请自行提交并推送。

常用参数：

```powershell
# 处理上一周
.\发布并部署周报.bat --week last

# 处理指定 ISO 周
.\发布并部署周报.bat --week 2026-W32

# 显示浏览器以排查 Facebook 登录或页面问题
.\发布并部署周报.bat --headed

# 跳过 OCR
.\发布并部署周报.bat --no-ocr
```

OCR 默认使用 `deu+eng`，所需语言模型保存在 `tessdata/`，应一并提交到 Git。

## GitHub Pages 部署

首次部署时：

1. 在 GitHub 新建仓库，并将本地仓库关联到该远程仓库。
2. 在仓库的 **Settings → Pages** 中，将发布来源设为 **GitHub Actions**。
3. 提交并推送项目内容。

项目内的 `.github/workflows/deploy-pages.yml` 会在 `main` 分支收到推送后，将 `docs/` 部署到 GitHub Pages。

每次运行完日常更新脚本后，手动提交并推送即可：

```powershell
git add docs facebook_newsletter.py build_static_site.py publish_weekly.py tessdata README.md .gitignore
git commit -m "更新周报"
git push
```

## 文件结构

```text
docs/                         GitHub Pages 发布目录
├─ index.html                 图库页面
├─ weeks.json                 周报和图片清单
├─ search.json                OCR 搜索索引
└─ output/YYYY-Www/images/    发布的周报图片

facebook_newsletter.py        周报采集、PDF 渲染和 OCR
build_static_site.py          从已有周报数据生成网站索引
publish_weekly.py             串联采集、OCR 与网站索引更新
tessdata/                     Tesseract 德语、英语语言模型
```

图片直接生成在 `docs/output/YYYY-Www/images/`，因此会随网站发布。PDF、原始 OCR 文件和采集清单仅用于本地处理，已由 `.gitignore` 排除，不会上传。

## 周报来源

自 2026-07-10 起，程序默认从本地 PDF 目录 `D:\F1\raceland_Newsletter` 读取文件名为 `YYYYMMDD.pdf` 的周报，并按文件名日期归入 ISO 周。可用 `--pdf-dir` 指定其他 PDF 目录：

```powershell
.\发布并部署周报.bat --week 2026-W32 --pdf-dir "D:\其他目录"
```

较早的周报会从 Facebook 页面采集。程序只处理当前账号可正常访问的内容，不尝试绕过登录、验证码或访问控制。

## Facebook 登录（仅采集旧周报时需要）

推荐在日常 Chrome 中登录 Facebook 后，将请求头中的完整 `Cookie` 值保存为本目录的 `cookies.txt`。该文件不会提交到 Git。

如需建立独立登录会话，可运行：

```powershell
& 'D:\conda\env3.10\python.exe' .\facebook_newsletter.py --login
```

登录状态保存在 `chrome-profile/`，不要删除。

## 仅重建网站索引

如果图片和 OCR 数据已经存在，只需重建 `weeks.json` 与 `search.json`：

```powershell
& 'D:\conda\env3.10\python.exe' .\build_static_site.py
```

若要对所有已有图片重新执行 OCR，运行：

```powershell
& 'D:\conda\env3.10\python.exe' .\facebook_newsletter.py --ocr-all
& 'D:\conda\env3.10\python.exe' .\build_static_site.py
```
