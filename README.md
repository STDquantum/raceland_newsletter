# Raceland Facebook 周报

抓取 `https://www.facebook.com/raceland.de` 指定自然周内正文包含 `Raceland Newsletter Magazin`（同时匹配德文 `Magazin` 和英文 `Magazine`）的图片帖子，按实际发布日期分周，下载页面接口暴露的最大尺寸图片，并生成一份 PDF。程序会先读取首屏 DOM 中的顶部帖子，再处理后续 GraphQL Feed；遇到时间线只显示 5 张和 `+N` 的帖子时，会自动打开照片查看器并遍历全部附件。其他帖子会被忽略。仅处理当前账号可正常看到的内容，不绕过登录、验证码或访问控制。

进入页面后会先按目标 ISO 周的周五选择 Facebook 年份和月份；跨月周以周五所在月份为准。筛选控件临时不可用时才回退到连续滚动。

## 2026-07-10 起使用本地 PDF

2026-07-10 起不再访问 Facebook。程序会在 `D:\F1\raceland_Newsletter` 查找文件名为 `YYYYMMDD.pdf` 的周报，按文件名日期归入 ISO 周，并将每个完整页面以 200 DPI 渲染到对应周的 `images/`。本地 PDF 缺失时会直接报错，不回退 Facebook。可用 `--pdf-dir` 指定其他目录。

```powershell
& 'D:\conda\env3.10\python.exe' .\facebook_newsletter.py --week 2026-W30 --ocr
```

## 使用日常 Chrome Cookie（推荐）

1. 在日常 Chrome 登录 Facebook，按 `F12` 打开开发者工具。
2. 进入 **Network**，刷新 Facebook 页面，点最上面的文档请求（通常是 `facebook.com`）。
3. 在 **Headers > Request Headers** 中复制完整的 `Cookie` 值。
4. 在本目录新建 `cookies.txt`，只粘贴这一行 Cookie；不要把内容发到聊天或提交到 Git。
5. 正常运行：

```powershell
& 'D:\conda\env3.10\python.exe' .\facebook_newsletter.py --headed --week current
```

`c_user` 和 `xs` 是登录所需的关键 Cookie；推荐复制完整请求头，让 Facebook 同时获得浏览器安全 Cookie。会话过期后重新复制即可。

## 单独登录（备选）

```powershell
& 'D:\conda\env3.10\python.exe' .\facebook_newsletter.py --login
```

程序会打开电脑上已安装的正式 Google Chrome。在其中手动登录 Facebook，再回到终端按 Enter。登录状态保存在本目录的 `chrome-profile` 中。

## 运行

```powershell
# 上一个完整自然周（适合每周一运行）
& 'D:\conda\env3.10\python.exe' .\facebook_newsletter.py

# 指定周或显示浏览器排查
& 'D:\conda\env3.10\python.exe' .\facebook_newsletter.py --week 2026-W29 --headed
```

结果位于 `output/YYYY-Www/`：原图在 `images/`，`manifest.json` 记录帖子、图片来源，以及实际识别为帖子载荷的 GraphQL `operation`/`doc_id`，PDF 文件名为 `raceland-YYYY-Www.pdf`。

## OCR 和检索索引

```powershell
# 抓取完当前周后立即 OCR
& 'D:\conda\env3.10\python.exe' .\facebook_newsletter.py --week 2026-W29 --headed --ocr

# 仅对 output 里所有已有图片做 OCR，不访问 Facebook
& 'D:\conda\env3.10\python.exe' .\facebook_newsletter.py --ocr-all
```

默认使用 Tesseract `deu+eng`。每周目录会生成 `ocr.jsonl` 和 `ocr.txt`；`output/ocr-index.jsonl` 是所有周的合并索引，可直接逐行导入检索系统。每条 JSON 包含 `week`、`image`、`post_id`、`text`，以及带置信度和坐标的 `words`。OCR 支持断点续跑；原图未变时会直接跳过。

每周自动运行可用 Windows“任务计划程序”，程序填 `D:\conda\env3.10\python.exe`，参数填 `facebook_newsletter.py`，起始位置填本目录。Facebook 会话失效时重新执行 `--login`。
