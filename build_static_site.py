"""Build the GitHub Pages data files for the newsletter gallery."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
OUTPUT_DIR = DOCS_DIR / "output"
WEEK_PATTERN = re.compile(r"^\d{4}-W\d{2}$")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def image_url(week: str, image: str) -> str:
    return f"./output/{week}/images/{quote(image)}"


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    os.replace(temporary, path)


def build_weeks() -> tuple[list[dict[str, object]], set[tuple[str, str]]]:
    weeks: list[dict[str, object]] = []
    available_images: set[tuple[str, str]] = set()
    if not OUTPUT_DIR.is_dir():
        return weeks, available_images

    for week_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        image_dir = week_dir / "images"
        if not WEEK_PATTERN.fullmatch(week_dir.name) or not image_dir.is_dir():
            continue
        images = [
            {"name": path.name, "url": image_url(week_dir.name, path.name)}
            for path in sorted(image_dir.iterdir())
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
        if not images:
            continue
        weeks.append({"id": week_dir.name, "images": images})
        available_images.update((week_dir.name, image["name"]) for image in images)
    return weeks, available_images


def build_search_index(available_images: set[tuple[str, str]]) -> tuple[dict[str, object], int]:
    records: list[dict[str, str]] = []
    indexed_weeks = 0
    if not OUTPUT_DIR.is_dir():
        return {"records": records, "indexed_weeks": indexed_weeks}, indexed_weeks

    for week_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        ocr_file = week_dir / "ocr.jsonl"
        if not WEEK_PATTERN.fullmatch(week_dir.name) or not ocr_file.is_file():
            continue
        indexed_weeks += 1
        for line in ocr_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                source = json.loads(line)
                image = str(source["image"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if (week_dir.name, image) not in available_images:
                continue
            text = " ".join(str(source.get("text", "")).split())
            if text:
                records.append({"week": week_dir.name, "image": image, "text": text})
    return {"records": records, "indexed_weeks": indexed_weeks}, indexed_weeks


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    weeks, available_images = build_weeks()
    search_index, indexed_weeks = build_search_index(available_images)
    write_json(DOCS_DIR / "weeks.json", weeks)
    write_json(DOCS_DIR / "search.json", search_index)
    print(
        f"网站数据已生成：{len(weeks)} 期、{len(available_images)} 张图片、"
        f"{len(search_index['records'])} 条 OCR 记录（{indexed_weeks} 期已索引）"
    )


if __name__ == "__main__":
    main()
