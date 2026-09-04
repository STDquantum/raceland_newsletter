# Raceland Newsletter 周报网站

本项目将 Raceland Newsletter 按 ISO 周整理为图片周报，并生成可部署到 GitHub Pages 的静态图库。网站支持按周浏览、连续阅读、双页阅读和 OCR 文字搜索。

## 本地处理

双击 `发布并部署周报.bat`，或在本目录运行：

```powershell
.\发布并部署周报.bat
```

该命令默认使用 `current` 参数，完成周报图片处理、OCR 和网站索引生成。命令不执行 Git 提交或推送。

处理参数（对应 `publish_weekly.py`）：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--week` | `current` | 指定 `current`、`last` 或 ISO 周，例如 `2026-W32` |
| `--headed` | 关闭 | 显示浏览器窗口，便于排查 Facebook 页面问题 |
| `--pdf-dir` | `raceland_Newsletter/` | 指定周报 PDF 目录 |
| `--ocr-lang` | `deu+eng` | 指定 Tesseract OCR 语言 |
| `--no-ocr` | 关闭 | 不执行 OCR |

示例：

```powershell
.\发布并部署周报.bat --week 2026-W32
.\发布并部署周报.bat --headed
.\发布并部署周报.bat --pdf-dir "D:\其他目录"
.\发布并部署周报.bat --ocr-lang deu+eng
.\发布并部署周报.bat --no-ocr
```

## GitHub Pages

配置 GitHub Pages：

1. 在 GitHub 新建仓库，并将本地仓库关联到该远程仓库。
2. 在仓库的 **Settings → Pages** 中，将发布来源设为 **Deploy from a branch**，选择 `main` 分支和 `/docs` 目录。
3. 提交并推送项目内容。

## GitHub Actions 发布

`.github/workflows/publish-weekly.yml` 使用每周五 20:30（北京时间；UTC cron 为 `30 12 * * 5`）的计划，并支持在 Actions 页面通过 **Run workflow** 手动执行。工作流包含合并 PDF 下载、PDF 拆分、OCR、网站构建和 GitHub Pages 发布。

周报 PDF 按 `YYYYMMDD.pdf` 的格式存放在 `raceland_Newsletter/`，拆分逻辑位于 `scripts/split_raceland_pdf.py`。本地处理和 GitHub Actions 均使用该目录；Action 将下载的 PDF 按日期写入该目录，并将 PDF 与网站内容一并提交。

## 文件结构

```text
docs/                         GitHub Pages 发布目录
├─ index.html                 图库页面
├─ weeks.json                 周报和图片清单
├─ search.json                OCR 搜索索引
└─ output/YYYY-Www/images/    发布的周报图片

raceland_Newsletter/          按日期归档的 Raceland PDF
scripts/split_raceland_pdf.py 从合并 PDF 拆分周报
facebook_newsletter.py        周报采集、PDF 渲染和 OCR
build_static_site.py          根据周报数据生成网站索引
publish_weekly.py             串联采集、OCR 与网站索引生成
tessdata/                     Tesseract 德语、英语语言模型
```

图片存放在 `docs/output/YYYY-Www/images/`，作为网站内容发布。周报 PDF、`ocr.jsonl` 和 `manifest.json` 属于仓库数据；生成的 PDF、临时文件和 Python 缓存不属于网站发布内容。

## 周报来源

程序从 `raceland_Newsletter` 读取文件名为 `YYYYMMDD.pdf` 的周报，并按文件名日期归入 ISO 周。可用 `--pdf-dir` 指定其他 PDF 目录：

```powershell
.\发布并部署周报.bat --week 2026-W32 --pdf-dir "D:\其他目录"
```

日期早于 `2026-07-10` 的周报通过 Facebook 页面采集；`2026-07-10` 及以后的周报从 `raceland_Newsletter/` 读取。程序只处理账号可正常访问的内容，不尝试绕过登录、验证码或访问控制。

## Facebook Cookie

Facebook 页面采集使用 `cookies.txt` 中的完整 `Cookie` 请求头。该文件不提交到 Git。

## 仅重建网站索引

根据图片和 OCR 数据重建 `weeks.json` 与 `search.json`：

```powershell
python .\build_static_site.py
```

对全部周报图片执行 OCR：

```powershell
python .\facebook_newsletter.py --ocr-all
python .\build_static_site.py
```
