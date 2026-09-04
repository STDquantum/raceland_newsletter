#!/usr/bin/env python3
"""Split Raceland's combined weekly newsletter PDF into dated PDFs.

The English newsletter PDF contains the newest newsletter first and the
previous newsletter immediately after it.  The page count changes from week
to week, so the split is found from the repeated newsletter date printed on
the pages instead of from a hard-coded page number.
"""

from __future__ import annotations

import argparse
import re
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

from pypdf import PdfReader, PdfWriter


MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERN = re.compile(
    rf"\b(?P<month>{MONTH_PATTERN})\s*,?\s*"
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*"
    rf"(?P<year>20\d{{2}})\b",
    re.IGNORECASE,
)


def page_newsletter_dates(text: str) -> set[date]:
    """Return valid full dates found in one page's text layer."""

    dates: set[date] = set()
    for match in DATE_PATTERN.finditer(text):
        try:
            dates.add(
                date(
                    int(match.group("year")),
                    MONTHS[match.group("month").lower()],
                    int(match.group("day")),
                )
            )
        except ValueError:
            # Ignore malformed text-layer fragments rather than failing a
            # whole run because of an invalid date in a product description.
            continue
    return dates


def choose_newsletter_dates(page_dates: list[set[date]]) -> tuple[date, date]:
    """Choose the newest and previous newsletter dates from repeated labels."""

    counts = Counter(date_value for dates in page_dates for date_value in dates)
    first_page: dict[date, int] = {}
    for page_number, dates in enumerate(page_dates):
        for date_value in dates:
            first_page.setdefault(date_value, page_number)

    # A newsletter date is printed on multiple pages.  Requiring repetition
    # filters out one-off dates that may appear in editorial/product text.
    repeated = [
        date_value for date_value, count in counts.items() if count >= 2
    ]
    if len(repeated) < 2:
        details = ", ".join(
            f"{value.isoformat()} ({counts[value]} pages)"
            for value in counts.most_common()
        )
        raise RuntimeError(
            "Could not find two repeated newsletter dates in the PDF. "
            f"Detected: {details or 'none'}"
        )

    selected = sorted(
        repeated,
        key=lambda value: (-counts[value], first_page[value]),
    )[:2]
    newest, previous = sorted(selected, key=lambda value: first_page[value])
    return newest, previous


def page_fingerprint(page) -> str:
    """Create a stable comparison key for an archive page.

    The text layer is sufficient for these newsletters and also works when a
    page is mostly an image, as long as it has the same extracted text.  The
    surrounding whitespace is ignored because pypdf can reflow it slightly
    after writing a split PDF.
    """

    return " ".join((page.extract_text() or "").split())


def find_boundary_from_archive(
    reader: PdfReader,
    archive_dir: Path,
    input_path: Path,
) -> tuple[int, Path] | None:
    """Find the combined PDF's suffix by matching a saved weekly PDF.

    This is the page-count strategy: every candidate's page count is compared
    with the tail of the downloaded PDF, then page text fingerprints confirm
    that the candidate really is the previous newsletter rather than merely a
    PDF with the same number of pages.
    """

    input_resolved = input_path.resolve()
    total_pages = len(reader.pages)
    matches: list[tuple[int, Path]] = []
    for candidate_path in sorted(archive_dir.glob("*.pdf")):
        if candidate_path.resolve() == input_resolved:
            continue
        try:
            candidate = PdfReader(str(candidate_path))
        except Exception:
            continue
        candidate_pages = len(candidate.pages)
        if candidate_pages == 0 or candidate_pages >= total_pages:
            continue

        start = total_pages - candidate_pages
        if all(
            page_fingerprint(reader.pages[start + offset])
            == page_fingerprint(candidate.pages[offset])
            for offset in range(candidate_pages)
        ):
            matches.append((start, candidate_path))

    if not matches:
        return None
    if len(matches) > 1:
        paths = ", ".join(str(path) for _, path in matches)
        raise RuntimeError(
            "More than one archived PDF matches the downloaded PDF suffix: "
            f"{paths}"
        )
    return matches[0]


def write_page_range(
    reader: PdfReader,
    start: int,
    end: int,
    output_path: Path,
) -> None:
    """Write a page range atomically, preserving source PDF metadata."""

    writer = PdfWriter()
    for page in reader.pages[start:end]:
        writer.add_page(page)

    metadata = {
        str(key): str(value)
        for key, value in (reader.metadata or {}).items()
        if value is not None
    }
    if metadata:
        writer.add_metadata(metadata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{output_path.stem}.",
        suffix=".tmp",
        dir=output_path.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)

    try:
        with temporary_path.open("wb") as stream:
            writer.write(stream)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def split_pdf(
    input_path: Path,
    output_dir: Path,
    archive_dir: Path | None = None,
) -> tuple[Path, Path, int, str]:
    reader = PdfReader(str(input_path))
    if len(reader.pages) < 2:
        raise RuntimeError("The downloaded PDF contains fewer than two pages.")

    page_dates = [page_newsletter_dates(page.extract_text() or "") for page in reader.pages]
    newest_date, previous_date = choose_newsletter_dates(page_dates)

    date_boundary = next(
        (
            page_number
            for page_number, dates in enumerate(page_dates)
            if previous_date in dates
        ),
        None,
    )

    archive_match = None
    if archive_dir is not None and archive_dir.exists():
        archive_match = find_boundary_from_archive(reader, archive_dir, input_path)

    if archive_match is not None:
        previous_start, matched_archive = archive_match
        if date_boundary is not None and date_boundary != previous_start:
            print(
                "Date marker starts at zero-based page "
                f"{date_boundary}, while the archived PDF suffix starts at "
                f"{previous_start}; using the archived page-count boundary. "
                "The first page of a newsletter may be a date-free feature image."
            )
        boundary_source = (
            f"archived page count from {matched_archive.name}"
        )
    elif date_boundary is not None:
        previous_start = date_boundary
        boundary_source = "repeated newsletter date markers"
    else:
        raise RuntimeError(
            "Could not find the previous newsletter boundary from either an "
            "archived PDF page count or repeated date markers."
        )

    if previous_start == 0 or not any(
        newest_date in dates for dates in page_dates[:previous_start]
    ):
        raise RuntimeError(
            "The detected date order is not newest-then-previous; refusing to "
            "write potentially mis-split PDFs."
        )

    newest_path = output_dir / f"{newest_date:%Y%m%d}.pdf"
    previous_path = output_dir / f"{previous_date:%Y%m%d}.pdf"
    write_page_range(reader, 0, previous_start, newest_path)
    write_page_range(reader, previous_start, len(reader.pages), previous_path)
    return newest_path, previous_path, previous_start, boundary_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Combined source PDF")
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for YYYYMMDD.pdf outputs",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Optional file receiving the two generated relative paths",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        help="Optional directory containing previously split PDFs for page-count matching",
    )
    args = parser.parse_args()

    newest_path, previous_path, split_page, boundary_source = split_pdf(
        args.input, args.output_dir, args.archive_dir
    )
    total_pages = len(PdfReader(str(args.input)).pages)
    print(f"Boundary: {boundary_source}")
    print(f"Newest newsletter: {newest_path} (pages 1-{split_page})")
    print(
        f"Previous newsletter: {previous_path} "
        f"(pages {split_page + 1}-{total_pages})"
    )

    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            f"{newest_path.as_posix()}\n{previous_path.as_posix()}\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
