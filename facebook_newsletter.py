from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageOps
from playwright.sync_api import BrowserContext, Response, sync_playwright

PAGE_URL = "https://www.facebook.com/raceland.de"
NEWSLETTER_MARKER = "Raceland Newsletter Magazin"
ROOT = Path(__file__).resolve().parent
SITE_DIR = ROOT / "docs"
OUTPUT_DIR = SITE_DIR / "output"
COOKIE_FILE = ROOT / "cookies.txt"
TESSDATA = ROOT / "tessdata"
OCR_VERSION = 2
LOCAL_PDF_START = date(2026, 7, 10)
LOCAL_PDF_DIR = Path(
    os.environ.get("RACELAND_PDF_DIR", ROOT / "raceland_Newsletter")
)
BERLIN = ZoneInfo("Europe/Berlin")
CDN_RE = re.compile(r"https?://[^\"' ]+(?:fbcdn\.net|fbsbx\.com)[^\"' ]*", re.I)


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def json_documents(raw: bytes):
    text = raw.decode("utf-8", "replace").removeprefix("for (;;);")
    try:
        yield json.loads(text)
        return
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip().removeprefix("for (;;);")
        if line.startswith("{"):
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def first_text(node, key):
    for item in walk(node):
        if isinstance(item, dict) and key in item:
            value = item[key]
            if isinstance(value, str):
                return value
            if isinstance(value, dict) and isinstance(value.get("text"), str):
                return value["text"]
    return ""


def image_key(url):
    return urlparse(html.unescape(url)).path.rsplit("/", 1)[-1]


def cdn_images(roots):
    best = {}
    for root in roots:
        for item in walk(root):
            if not isinstance(item, dict):
                continue
            url = item.get("uri") or item.get("url")
            if not isinstance(url, str) or not CDN_RE.match(html.unescape(url)):
                continue
            width = item.get("width") if isinstance(item.get("width"), int) else 0
            height = item.get("height") if isinstance(item.get("height"), int) else 0
            candidate = {"url": html.unescape(url), "width": width, "height": height}
            key = image_key(url)
            if width * height >= best.get(key, {}).get("width", 0) * best.get(key, {}).get("height", 0):
                best[key] = candidate
    return list(best.values())


def photo_images(value):
    photos = {}
    for item in walk(value):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        if item.get("__typename") != "Photo" and "photo_image" not in item:
            continue
        candidates = cdn_images([item])
        if candidates:
            image = max(candidates, key=lambda candidate: candidate["width"] * candidate["height"])
            image["photo_id"] = str(item["id"])
            photos[image["photo_id"]] = image
    return list(photos.values())


def attachment_images(story):
    roots = []
    for item in walk(story):
        if isinstance(item, dict) and isinstance(item.get("attachments"), list):
            roots.extend(item["attachments"])
    return photo_images(roots) or cdn_images(roots)


def attachment_count(story, fallback):
    counts = [
        item["all_subattachments"].get("count", 0)
        for item in walk(story)
        if isinstance(item, dict) and isinstance(item.get("all_subattachments"), dict)
    ]
    return max([fallback, *counts])


def extract_posts(document):
    posts, seen = [], set()
    for node in walk(document):
        if not isinstance(node, dict) or not isinstance(node.get("creation_time"), (int, float)):
            continue
        images = attachment_images(node)
        if not images:
            continue
        post_id = str(node.get("id") or node.get("post_id") or f'{int(node["creation_time"])}-{len(posts)}')
        if post_id in seen:
            continue
        actor_names = {
            item.get("name", "").lower()
            for item in walk(node)
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        if actor_names and any("raceland" in name for name in actor_names) is False:
            continue
        text = first_text(node, "message")
        if NEWSLETTER_MARKER.casefold() not in text.casefold():
            continue
        seen.add(post_id)
        posts.append(
            {
                "id": post_id,
                "created": datetime.fromtimestamp(node["creation_time"], timezone.utc).isoformat(),
                "text": text,
                "url": first_text(node, "permalink_url") or first_text(node, "wwwURL") or first_text(node, "url"),
                "images": images,
                "image_count": attachment_count(node, len(images)),
            }
        )
    return posts


def parse_relative_time(value, now=None, default_year=None):
    now = now or datetime.now(BERLIN)
    absolute = re.search(r"(?:(\d{4})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", value)
    if absolute:
        return datetime(
            int(absolute[1] or default_year or now.year), int(absolute[2]), int(absolute[3]), 12, tzinfo=BERLIN
        )
    units = (
        (r"(\d+)\s*(?:分钟|minutes?|Min\.)", "minutes"),
        (r"(\d+)\s*(?:小时|hours?|Std\.)", "hours"),
        (r"(\d+)\s*(?:天|days?|Tage?)", "days"),
    )
    for pattern, unit in units:
        match = re.search(pattern, value, re.I)
        if match:
            return now - timedelta(**{unit: int(match[1])})
    if re.search(r"昨天|yesterday|gestern", value, re.I):
        return now - timedelta(days=1)
    return None


def dom_image_count(photo_links, overlays):
    visible = set()
    for href in photo_links:
        query = parse_qs(urlparse(href).query)
        if not (query.get("set") or [""])[0].startswith("pcb."):
            continue
        visible.add((query.get("fbid") or [href])[0])
    hidden = max([int(value[1:]) for value in overlays], default=0)
    # Facebook的“+N”遮罩格同时也在 visible 里，不能重复计数。
    return max(1, len(visible) + hidden - (1 if hidden else 0))


def extract_dom_posts(page, default_year=None):
    posts = []
    articles = page.locator('[role="article"]')
    for index in range(articles.count()):
        article = articles.nth(index)
        text = article.inner_text()
        if NEWSLETTER_MARKER.casefold() not in text.casefold():
            continue
        link = article.locator('a[href*="/posts/"]').first
        if not link.count():
            continue
        created = parse_relative_time(link.get_attribute("aria-label") or link.inner_text(), default_year=default_year)
        if created is None:
            continue
        url = (link.get_attribute("href") or "").split("?", 1)[0]
        photo_links = article.locator('a[href*="photo"]').evaluate_all("els => els.map(e => e.href)")
        overlays = article.get_by_text(re.compile(r"^\+\d+$")).all_inner_texts()
        posts.append(
            {
                "id": f"dom-{url.rstrip('/').rsplit('/', 1)[-1]}",
                "created": created.astimezone(timezone.utc).isoformat(),
                "text": text,
                "url": url,
                "images": [],
                "image_count": dom_image_count(photo_links, overlays),
            }
        )
    return posts


def ordered_photo_images(viewer, order, initial=()):
    result, used = [], set()
    for photo_id in order:
        if photo_id in viewer:
            result.append(viewer[photo_id])
            used.add(photo_id)
    for image in [*initial, *viewer.values()]:
        key = image.get("photo_id") or image_key(image["url"])
        if key not in used:
            result.append(image)
            used.add(key)
    return result


def expand_post_images(page, post):
    expected = post.get("image_count", len(post["images"]))
    if expected <= len(post["images"]) or not post.get("url"):
        return
    viewer, order = {}, []

    def keep(image):
        current = viewer.get(image["photo_id"])
        if current is None or image["width"] * image["height"] >= current["width"] * current["height"]:
            viewer[image["photo_id"]] = image

    def capture(response: Response):
        if "graphql" not in response.url or response.request.method != "POST":
            return
        form = parse_qs(response.request.post_data or "")
        operation = (form.get("fb_api_req_friendly_name") or [""])[0]
        if "PhotoRootContent" not in operation:
            return
        try:
            for document in json_documents(response.body()):
                for image in photo_images(document):
                    keep(image)
        except Exception:
            pass

    def remember_current():
        photo_id = (parse_qs(urlparse(page.url).query).get("fbid") or [""])[0]
        if not photo_id:
            return False
        fresh = photo_id not in order
        if fresh:
            order.append(photo_id)
        images = page.locator('img[src*="fbcdn"]').evaluate_all(
            """els => els.map(e => { const r=e.getBoundingClientRect(); return {
                url:e.currentSrc || e.src, width:e.naturalWidth, height:e.naturalHeight,
                area:r.width*r.height}; }).filter(x => x.area > 40000).sort((a,b) => b.area-a.area)"""
        )
        if images:
            image = images[0]
            keep({"url": image["url"], "width": image["width"], "height": image["height"], "photo_id": photo_id})
        return fresh

    page.on("response", capture)
    try:
        page.goto(post["url"], wait_until="domcontentloaded", timeout=90_000)
        article = page.locator('[role="article"]').filter(has_text=NEWSLETTER_MARKER).first
        article.wait_for(timeout=15_000)
        first_photo = article.locator('a[href*="photo"][href*="set=pcb"]').first
        if first_photo.count():
            first_photo.click(force=True)
        else:
            article.get_by_text(re.compile(r"^\+\d+$")).first.click(force=True)
        page.wait_for_timeout(3_000)
        remember_current()
        for _ in range(expected + 2):
            if len(order) >= expected:
                break
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(1_500)
            if not remember_current() and order and (parse_qs(urlparse(page.url).query).get("fbid") or [""])[0] == order[0]:
                break
    finally:
        page.remove_listener("response", capture)
    images = ordered_photo_images(viewer, order, post["images"])
    if len(images) > len(post["images"]):
        post["images"] = images
        post["image_count"] = len(images)


def week_range(spec):
    today = datetime.now(BERLIN).date()
    if spec == "last":
        day = today - timedelta(days=today.weekday() + 7)
    elif spec == "current":
        day = today
    else:
        match = re.fullmatch(r"(\d{4})-W(\d{2})", spec)
        if not match:
            raise ValueError("--week 应为 last、current 或 YYYY-Www")
        day = date.fromisocalendar(int(match[1]), int(match[2]), 1)
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=7)
    return start, end, f"{start.isocalendar().year}-W{start.isocalendar().week:02d}"


def filter_date_for_week(start):
    return start + timedelta(days=4)


def apply_date_filter(page, start):
    target = filter_date_for_week(start)
    months = {
        1: "January|Januar", 2: "February|Februar", 3: "March|März|Maerz", 4: "April",
        5: "May|Mai", 6: "June|Juni", 7: "July|Juli", 8: "August", 9: "September",
        10: "October|Oktober", 11: "November", 12: "December|Dezember",
    }
    try:
        page.get_by_role("button", name=re.compile(r"筛选条件|Filter|Filtern", re.I)).first.click(timeout=10_000)
        dialog = page.locator('[role="dialog"]:visible').first
        year = dialog.get_by_role("combobox").first
        year.wait_for(timeout=15_000)
        year.click()
        page.get_by_role("option", name=re.compile(rf"^{target.year}(?:\s*年)?$", re.I)).click()
        month = dialog.get_by_role("combobox").nth(1)
        month.wait_for(timeout=10_000)
        month.click()
        page.get_by_role(
            "option", name=re.compile(rf"^(?:{target.month}\s*月|{months[target.month]})$", re.I)
        ).click()
        dialog.get_by_role("button", name=re.compile(r"完成|Done|Fertig", re.I)).click()
        dialog.wait_for(state="hidden", timeout=15_000)
        print(f"已按目标周周五筛选 Facebook：{target.year}-{target.month:02d}", flush=True)
        return True
    except Exception as error:
        print(f"Facebook 年月筛选失败，回退到滚动：{type(error).__name__}", flush=True)
        return False


def unscaled_url(url):
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != "stp"]
    return urlunparse(parsed._replace(query=urlencode(query)))


def fetch_best(_context: BrowserContext, image):
    candidates = list(dict.fromkeys([unscaled_url(image["url"]), image["url"]]))
    for url in candidates:
        try:
            request = Request(url, headers={"Referer": PAGE_URL, "User-Agent": "Mozilla/5.0", "Accept": "image/*"})
            with urlopen(request, timeout=10) as response:
                data = response.read()
            with Image.open(io.BytesIO(data)) as im:
                size = im.width * im.height
                fmt = (im.format or "JPEG").lower().replace("jpeg", "jpg")
            return size, data, fmt, url
        except Exception:
            continue
    raise RuntimeError("图片下载失败或 URL 已过期")


def font(size, bold=False):
    names = ["arialbd.ttf" if bold else "arial.ttf", "msyhbd.ttc" if bold else "msyh.ttc"]
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def make_pdf(posts, image_files, output, label, start, end, title="Facebook Wochen-Newsletter"):
    page_size = (1240, 1754)
    pages = []
    cover = Image.new("RGB", page_size, "white")
    draw = ImageDraw.Draw(cover)
    draw.text((90, 260), "Raceland GmbH", fill="#1455a0", font=font(72, True))
    draw.text((90, 375), title, fill="#222", font=font(50, True))
    draw.text((90, 480), f"{start:%d.%m.%Y} – {(end - timedelta(days=1)):%d.%m.%Y}", fill="#555", font=font(34))
    draw.text((90, 1480), f"{len(posts)} Beiträge · {len(image_files)} Bilder · {label}", fill="#777", font=font(28))
    pages.append(cover)
    for item in image_files:
        with Image.open(item["path"]) as source:
            picture = ImageOps.exif_transpose(source).convert("RGB")
            picture.thumbnail((1100, 1420), Image.Resampling.LANCZOS)
            page = Image.new("RGB", page_size, "white")
            page.paste(picture, ((page.width - picture.width) // 2, 170 + (1420 - picture.height) // 2))
        draw = ImageDraw.Draw(page)
        created = datetime.fromisoformat(item["post"]["created"]).astimezone(BERLIN)
        draw.text((70, 55), f"{created:%A, %d.%m.%Y %H:%M}", fill="#222", font=font(30, True))
        draw.text((70, 1635), f"Beitrag {item['post']['id']}", fill="#777", font=font(22))
        pages.append(page)
    output.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(output, "PDF", resolution=150, save_all=True, append_images=pages[1:])


def ocr_output(out, lang="deu+eng"):
    import pytesseract

    out = out.resolve()
    executable = shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if not Path(executable).exists():
        raise RuntimeError("未找到 Tesseract OCR")
    missing = [code for code in lang.split("+") if not (TESSDATA / f"{code}.traineddata").exists()]
    if missing:
        raise RuntimeError(f"缺少 OCR 语言模型：{missing}（请放入 {TESSDATA}）")
    pytesseract.pytesseract.tesseract_cmd = executable
    images_dir = out / "images"
    images = sorted(path for path in images_dir.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if not images:
        return 0
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"posts": []}
    post_by_image = {
        image.get("downloaded"): post.get("id")
        for post in manifest.get("posts", [])
        for image in post.get("images", [])
        if image.get("downloaded")
    }
    jsonl = out / "ocr.jsonl"
    records = {}
    if jsonl.exists():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                if record.get("lang") == lang:
                    records[record["image"]] = record
            except (json.JSONDecodeError, KeyError):
                pass
    image_by_name = {path.name: path for path in images}
    records = {
        name: record
        for name, record in records.items()
        if name in image_by_name
        and record.get("size") == image_by_name[name].stat().st_size
        and record.get("mtime_ns") == image_by_name[name].stat().st_mtime_ns
        and (record.get("ocr_version") == OCR_VERSION or record.get("text", "").strip())
    }
    jsonl.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records.values()), encoding="utf-8"
    )
    done = 0
    def recognize(picture, psm):
        # Tesseract for Windows 无法打开含中文的 tessdata 绝对路径，相对路径可以。
        previous_cwd = Path.cwd()
        try:
            os.chdir(ROOT)
            return pytesseract.image_to_data(
                picture,
                lang=lang,
                config=f'--tessdata-dir tessdata --psm {psm} -c preserve_interword_spaces=1',
                output_type=pytesseract.Output.DICT,
            )
        finally:
            os.chdir(previous_cwd)

    for index, path in enumerate(images, 1):
        stat = path.stat()
        cached = records.get(path.name)
        if cached and cached.get("size") == stat.st_size and cached.get("mtime_ns") == stat.st_mtime_ns:
            continue
        with Image.open(path) as source:
            picture = ImageOps.exif_transpose(source).convert("RGB")
            width, height = picture.size
            scale, psm = 1, 3
            data = recognize(picture, psm)
            if not any(value.strip() for value in data["text"]):
                scale, psm = (2 if width < 1000 else 1), 11
                if scale > 1:
                    picture = picture.resize((width * scale, height * scale), Image.Resampling.LANCZOS)
                data = recognize(picture, psm)
        words, lines = [], {}
        for i, text_value in enumerate(data["text"]):
            text_value = text_value.strip()
            if not text_value:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(text_value)
            words.append(
                {
                    "text": text_value,
                    "confidence": float(data["conf"][i]),
                    "x": round(data["left"][i] / scale),
                    "y": round(data["top"][i] / scale),
                    "width": round(data["width"][i] / scale),
                    "height": round(data["height"][i] / scale),
                }
            )
        record = {
            "week": out.name,
            "image": path.name,
            "post_id": post_by_image.get(path.name),
            "lang": lang,
            "ocr_version": OCR_VERSION,
            "psm": psm,
            "width": width,
            "height": height,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "text": "\n".join(" ".join(values) for values in lines.values()),
            "words": words,
        }
        records[path.name] = record
        with jsonl.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
        done += 1
        print(f"  OCR {out.name} {index}/{len(images)} {path.name}", flush=True)
    return done


def ocr_all_outputs(lang):
    outputs = sorted(path for path in OUTPUT_DIR.glob("????-W??") if (path / "images").is_dir())
    total = 0
    for out in outputs:
        print(f"开始 OCR {out.name}", flush=True)
        total += ocr_output(out, lang)
    print(f"OCR 完成：{len(outputs)} 个周目录，新识别 {total} 张图片", flush=True)


def parse_cookie_header(raw):
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1]
    cookies = []
    for part in raw.split(";"):
        if "=" not in part:
            continue
        name, value = part.strip().split("=", 1)
        if name:
            cookies.append({"name": name, "value": value, "domain": ".facebook.com", "path": "/", "secure": True})
    names = {cookie["name"] for cookie in cookies}
    if not {"c_user", "xs"}.issubset(names):
        raise RuntimeError("Cookie 中缺少 c_user 或 xs；请复制 facebook.com 文档请求的完整 Cookie 请求头")
    return cookies


def add_cookie_file(context, path):
    if path.exists():
        context.add_cookies(parse_cookie_header(path.read_text(encoding="utf-8")))
        print(f"已从 {path.name} 注入 Facebook Cookie", flush=True)


def local_pdf_sources(start, end, directory):
    sources = []
    for path in directory.glob("*.pdf"):
        try:
            issue_date = datetime.strptime(path.stem, "%Y%m%d").date()
        except ValueError:
            continue
        if start <= issue_date < end:
            sources.append((issue_date, path))
    return sorted(sources)


def collect_local_pdf(args):
    import fitz

    start, end, label = week_range(args.week)
    sources = local_pdf_sources(start, end, args.pdf_dir)
    if not sources:
        raise RuntimeError(f"{label} 在 {args.pdf_dir} 中没有 YYYYMMDD.pdf；2026-07-10 起不再回退 Facebook")
    out = OUTPUT_DIR / label
    images_dir = out / "images"
    if images_dir.exists():
        shutil.rmtree(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    (out / "ocr.jsonl").unlink(missing_ok=True)
    posts, downloaded = [], []
    image_number = 0
    for issue_date, source in sources:
        post = {
            "id": f"pdf-{source.stem}",
            "created": datetime.combine(issue_date, datetime.min.time(), BERLIN).isoformat(),
            "text": "",
            "url": str(source),
            "images": [],
            "image_count": 0,
            "issue_week": label,
        }
        document = fitz.open(source)
        try:
            for page_number, page in enumerate(document, 1):
                image_number += 1
                pixmap = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False)
                path = images_dir / f"{image_number:03d}_{source.stem}_page-{page_number:03d}.jpg"
                Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples).save(
                    path, "JPEG", quality=95, subsampling=0
                )
                image = {
                    "downloaded": path.name,
                    "source_pdf": str(source),
                    "source_page": page_number,
                    "width": pixmap.width,
                    "height": pixmap.height,
                    "pixels": pixmap.width * pixmap.height,
                }
                post["images"].append(image)
                downloaded.append({"path": path, "post": post})
                print(f"  已渲染 {source.name} {page_number}/{document.page_count}", flush=True)
        finally:
            document.close()
        post["image_count"] = len(post["images"])
        posts.append(post)
    manifest = {
        "source": "local_pdf",
        "week": label,
        "source_pdfs": [str(path) for _, path in sources],
        "posts": posts,
        "graphql_requests": [],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    output_pdf = out / f"raceland-{label}.pdf"
    make_pdf(posts, downloaded, output_pdf, label, start, end, "Raceland Newsletter")
    if args.ocr:
        ocr_output(out, args.ocr_lang)
    print(f"完成：{len(sources)} 份本地 PDF，{len(downloaded)} 页，{output_pdf}", flush=True)


def collect(playwright, args):
    start, end, label = week_range(args.week)
    captured, requests = [], []
    browser = playwright.chromium.launch(channel="chrome", headless=not args.headed)
    context = browser.new_context(locale="de-DE", viewport={"width": 1440, "height": 1000})
    add_cookie_file(context, args.cookie_file)
    page = context.pages[0] if context.pages else context.new_page()

    def on_response(response: Response):
        request = response.request
        if "graphql" not in response.url or request.method != "POST":
            return
        form = parse_qs(request.post_data or "")
        operation = (form.get("fb_api_req_friendly_name") or [""])[0]
        doc_id = (form.get("doc_id") or [""])[0]
        try:
            raw = response.body()
        except Exception:
            return
        captured.append(raw)
        requests.append({"operation": operation, "doc_id": doc_id, "url": response.url})

    context.on("response", on_response)
    page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=90_000)
    for label_text in ("Close", "Schließen", "Not now", "Jetzt nicht"):
        locator = page.get_by_role("button", name=label_text, exact=True)
        if locator.count():
            try:
                locator.first.click(timeout=1_000)
            except Exception:
                pass
    page.wait_for_timeout(5_000)
    apply_date_filter(page, start)
    page.wait_for_timeout(5_000)
    dom_posts = extract_dom_posts(page, filter_date_for_week(start).year)
    out = OUTPUT_DIR / label
    images_dir = out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    seen_posts, seen_urls, posts, downloaded, hashes = {}, set(), {}, [], set()
    processed = 0

    def save_manifest():
        manifest = {
            "page": PAGE_URL,
            "week": label,
            "posts": sorted(posts.values(), key=lambda post: post["created"]),
            "graphql_requests": requests,
        }
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def process_new_responses():
        nonlocal processed
        for raw in captured[processed:]:
            for document in json_documents(raw):
                for post in extract_posts(document):
                    handle_post(post)
        processed = len(captured)

    def handle_post(post):
        if post["id"] in seen_posts or post.get("url") in seen_urls:
            return
        seen_posts[post["id"]] = post
        if post.get("url"):
            seen_urls.add(post["url"])
        created = datetime.fromisoformat(post["created"]).astimezone(BERLIN).date()
        post["issue_week"] = f"{created.isocalendar().year}-W{created.isocalendar().week:02d}"
        if not start <= created < end:
            return
        posts[post["id"]] = post
        if post["image_count"] > len(post["images"]):
            print(
                f"帖子共有 {post['image_count']} 张图片，正在展开其余 {post['image_count'] - len(post['images'])} 张",
                flush=True,
            )
            try:
                expand_post_images(page, post)
            except Exception as error:
                post["expand_error"] = f"{type(error).__name__}: {error}"
        print(f"发现周报帖子 {post['id']}，立即保存 {len(post['images'])} 张图片", flush=True)
        for image in post["images"]:
            try:
                pixels, data, suffix, source_url = fetch_best(context, image)
            except RuntimeError as error:
                image["error"] = str(error)
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest in hashes:
                continue
            hashes.add(digest)
            path = images_dir / f"{len(downloaded) + 1:03d}_{post['id']}.{suffix}"
            path.write_bytes(data)
            image.update({"downloaded": path.name, "source_url": source_url, "pixels": pixels})
            downloaded.append({"path": path, "post": post})
            save_manifest()
            print(f"  已保存 {path.name}", flush=True)
        save_manifest()

    for post in dom_posts:
        handle_post(post)
    process_new_responses()
    for _ in range(args.scrolls):
        dates = [datetime.fromisoformat(post["created"]).astimezone(BERLIN).date() for post in seen_posts.values()]
        if posts and dates and min(dates) < start:
            break
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(3_000)
        process_new_responses()
    save_manifest()
    posts = sorted(posts.values(), key=lambda post: post["created"])
    context.close()
    browser.close()
    if not captured:
        raise RuntimeError("没有捕获到帖子 GraphQL 请求；请检查 cookies.txt 是否有效，或用 --headed 检查登录状态")
    if not posts:
        found = sorted(
            {
                f"{datetime.fromisoformat(post['created']).astimezone(BERLIN):%Y-%m-%d %H:%M}"
                for post in seen_posts.values()
            },
            reverse=True,
        )
        raise RuntimeError(
            f"捕获了 {len(captured)} 个 GraphQL 响应，但 {label} 没有命中；实际解析到的 Newsletter 日期：{found or '无'}"
        )
    make_pdf(posts, downloaded, out / f"raceland-{label}.pdf", label, start, end)
    if args.ocr:
        ocr_output(out, args.ocr_lang)
    print(f"完成：{len(posts)} 个帖子，{len(downloaded)} 张原图，{out / f'raceland-{label}.pdf'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="按周处理 Raceland Newsletter 图片并生成 PDF")
    parser.add_argument("--cookie-file", type=Path, default=COOKIE_FILE, help="Cookie 请求头文件（默认 cookies.txt）")
    parser.add_argument("--week", default="current", help="current（默认）、last 或 YYYY-Www")
    parser.add_argument("--headed", action="store_true", help="显示浏览器，便于排查登录/页面问题")
    parser.add_argument("--scrolls", type=int, default=20, help="最多向下加载次数")
    parser.add_argument("--ocr", dest="ocr", action="store_true", default=True, help="抓取后对当前周图片做 OCR（默认开启）")
    parser.add_argument("--no-ocr", dest="ocr", action="store_false", help="跳过当前周的 OCR")
    parser.add_argument("--ocr-all", action="store_true", help="对 output 中所有已有图片做 OCR，不访问 Facebook")
    parser.add_argument("--ocr-lang", default="deu+eng", help="Tesseract 语言（默认 deu+eng）")
    parser.add_argument("--pdf-dir", type=Path, default=LOCAL_PDF_DIR, help="2026-07-10 起的 Newsletter PDF 目录")
    args = parser.parse_args()
    if args.ocr_all:
        ocr_all_outputs(args.ocr_lang)
        return
    start, _, _ = week_range(args.week)
    if filter_date_for_week(start) >= LOCAL_PDF_START:
        collect_local_pdf(args)
    else:
        with sync_playwright() as playwright:
            collect(playwright, args)


if __name__ == "__main__":
    main()
