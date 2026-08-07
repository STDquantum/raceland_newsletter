"""Collect one newsletter, run OCR, and update the GitHub Pages files."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
COLLECTOR = ROOT / "facebook_newsletter.py"
BUILDER = ROOT / "build_static_site.py"
def run(command: list[str]) -> None:
    print("\n> " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集周报、OCR 并更新 GitHub Pages 静态文件")
    parser.add_argument("--week", default="current", help="current（默认）、last 或 YYYY-Www")
    parser.add_argument("--headed", action="store_true", help="显示浏览器，便于排查登录")
    parser.add_argument("--pdf-dir", help="本地 PDF 目录；不传则使用采集脚本的默认目录")
    parser.add_argument("--ocr-lang", default="deu+eng", help="Tesseract 语言，默认 deu+eng")
    parser.add_argument("--no-ocr", action="store_true", help="跳过当前周的 OCR")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    collect_command = [
        sys.executable,
        str(COLLECTOR),
        "--week",
        args.week,
        "--ocr-lang",
        args.ocr_lang,
    ]
    if args.headed:
        collect_command.append("--headed")
    if args.no_ocr:
        collect_command.append("--no-ocr")
    if args.pdf_dir:
        collect_command.extend(["--pdf-dir", args.pdf_dir])

    run(collect_command)
    run([sys.executable, str(BUILDER)])
    print("网站文件已更新；请自行提交并推送 docs/ 及相关代码。")


if __name__ == "__main__":
    main()
