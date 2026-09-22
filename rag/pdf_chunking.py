
# -*- coding: utf-8 -*-
"""Extraction and chunking pipeline for a genuine (non-scanned) datasheet PDF.

Why this file exists as something separate from chunking.py (the Markdown
chunker):

Markdown carries its own structure as literal text ('## ', '### '). A PDF
extracted with pdfplumber gives back a flat stream of text per page with no
such markers -- headings only exist as larger/bold font in the original
layout, which pdfplumber can expose via character-level font-size data, but
that is noisy to rely on for a document assembled from Platypus flowables.
Two problems are handled here that never occur with the Markdown source:

1. Repeating running header/footer text (present on every single page)
   would otherwise be re-injected into the extracted text of every page and
   pollute every chunk built from that page. It is detected by frequency
   (a line appearing on most pages is boilerplate, not content) and
   stripped before any chunking happens.

2. There is no explicit heading syntax, so section/product boundaries are
   recovered with a regex tuned to this document's one reliable, literal
   structural marker: the line "Product Code: <CODE> | Manufacturer: <n>"
   that appears once per product. That line is a much more reliable anchor
   than font-size heuristics, which break across PDF generators.

3. Tables are extracted separately (pdfplumber.extract_tables) and
   linearized into natural-language "Attribute: Value" sentences rather than
   kept as a pipe-delimited grid, because a raw table grid embeds poorly and
   retrieves poorly against natural-language questions.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

import pdfplumber


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)


PRODUCT_HEADER_RE = re.compile(
    r"Product Code:\s*(?P<code>[A-Z0-9\-]+)\s*\|\s*Manufacturer:\s*(?P<mfr>.+)"
)
COMPLIANCE_RE = re.compile(
    r"Compliance cross-reference:\s*(?P<refs>.+?)\s*of the (?P<doc>.+)\.?\s*$"
)


def _bbox_overlaps(top: float, bottom: float, table_bboxes: list) -> bool:
    for (x0, ttop, x1, tbottom) in table_bboxes:
        if not (bottom < ttop - 1 or top > tbottom + 1):
            return True
    return False


def _extract_pages(path: str):
    """Return a list of page records, each with:
    - 'lines': body text lines OUTSIDE any table region, as (text, avg_font_size, top)
    - 'tables': list of (top, grid) for tables found on the page, in document order

    Words are excluded from 'lines' when their vertical position falls inside
    a table's bounding box, so table content is never duplicated into the
    surrounding description text (pdfplumber's plain extract_text() does not
    make this distinction, which is what produced the duplicated table text
    in the first pass).
    """
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            found_tables = page.find_tables()
            table_bboxes = [t.bbox for t in found_tables]
            tables = [(t.bbox[1], t.extract()) for t in found_tables]

            # Fixed running header/footer bands, in points from the top of
            # the page. Derived from the known layout margins used when the
            # PDF was generated (header ~12 mm below the top edge, footer
            # ~11-15 mm above the bottom edge), with a safety margin. This
            # catches header/footer content by POSITION, which is reliable
            # even when the footer's left-hand boilerplate text and the
            # right-hand page number sit on the same visual line and get
            # merged into a single string that changes every page (and so
            # would otherwise slip past the frequency-based boilerplate
            # detector below).
            header_band = 45
            footer_band = page.height - 45

            words = page.extract_words(extra_attrs=["size"])
            # Group words into visual lines by rounding the 'top' coordinate.
            line_buckets = {}
            for w in words:
                if _bbox_overlaps(w["top"], w["bottom"], table_bboxes):
                    continue
                if w["top"] < header_band or w["top"] > footer_band:
                    continue
                key = round(w["top"] / 3) * 3
                line_buckets.setdefault(key, []).append(w)

            lines = []
            for key in sorted(line_buckets):
                ws = sorted(line_buckets[key], key=lambda w: w["x0"])
                text = " ".join(w["text"] for w in ws).strip()
                if not text:
                    continue
                avg_size = sum(w["size"] for w in ws) / len(ws)
                lines.append((text, round(avg_size, 1), key))

            pages.append({"page_no": i, "lines": lines, "tables": tables})
    return pages


def _detect_boilerplate(pages, min_page_fraction: float = 0.6) -> set:
    """Lines repeated on most pages are running headers/footers, not content."""
    counts = Counter()
    total_pages = len(pages)
    for rec in pages:
        for text, _, _ in set(rec["lines"]):
            counts[text] += 1
    threshold = max(2, int(total_pages * min_page_fraction))
    boilerplate = {ln for ln, c in counts.items() if c >= threshold}
    return boilerplate


def _linearize_table(table: list) -> str:
    """Turn a pdfplumber table (list of rows) into natural-language sentences."""
    if not table or len(table) < 2:
        return ""
    header = table[0]
    sentences = []
    for row in table[1:]:
        if len(row) < 2 or not row[0]:
            continue
        attr = (row[0] or "").replace("\n", " ").strip()
        val = (row[1] or "").replace("\n", " ").strip()
        if attr and val:
            sentences.append(f"{attr}: {val}.")
    return " ".join(sentences)


# Font-size bands measured from this document's own generation styles
# (CategoryHeading=16pt, ProductName=12.5pt, everything else ~9-9.5pt).
# A real pipeline would calibrate these from a histogram of sizes actually
# found in the file rather than hard-coding them; the thresholds below are
# deliberately set with margin (>=14 / >=11) so small rendering variation
# does not misclassify a line.
CATEGORY_SIZE_MIN = 14.0
PRODUCT_NAME_SIZE_MIN = 11.0


def _classify(size: float) -> str:
    if size >= CATEGORY_SIZE_MIN:
        return "category"
    if size >= PRODUCT_NAME_SIZE_MIN:
        return "product_name"
    return "body"


def _build_event_stream(pages, boilerplate):
    """One ordered list of events across the whole document: each event is
    either ('line', kind, text, page_no) or ('table', grid, page_no),
    interleaved in true top-to-bottom, page-to-page reading order."""
    events = []
    for rec in pages:
        page_no = rec["page_no"]
        merged = [("line", size, text, top) for (text, size, top) in rec["lines"]]
        merged += [("table", None, grid, top) for (top, grid) in rec["tables"]]
        merged.sort(key=lambda e: e[3])
        for kind, size, payload, _top in merged:
            if kind == "line":
                if payload in boilerplate or re.fullmatch(r"Page\s+\d+", payload):
                    continue
                events.append(("line", _classify(size), payload, page_no))
            else:
                events.append(("table", None, payload, page_no))
    return events


def load_and_chunk(path: str) -> list[Chunk]:
    pages = _extract_pages(path)
    boilerplate = _detect_boilerplate(pages)
    events = _build_event_stream(pages, boilerplate)

    chunks: list[Chunk] = []
    current_category = ""
    i, n = 0, len(events)

    while i < n:
        kind, subkind, payload, page_no = events[i]

        if kind == "line" and subkind == "category":
            current_category = payload
            i += 1
            continue

        if kind == "line" and subkind == "product_name":
            product_name = payload
            i += 1
            # Next event must be the "Product Code: ... | Manufacturer: ..." line.
            if i >= n or events[i][0] != "line":
                continue
            m = PRODUCT_HEADER_RE.search(events[i][2])
            if not m:
                continue
            code, manufacturer = m.group("code"), m.group("mfr").strip()
            i += 1

            desc_parts, table_text, compliance_text = [], "", ""
            while i < n:
                ekind, esub, epayload, _pg = events[i]
                if ekind == "table":
                    table_text = _linearize_table(epayload)
                    i += 1
                    continue
                if ekind == "line" and esub in ("category", "product_name"):
                    break
                cm = COMPLIANCE_RE.search(epayload)
                if cm:
                    compliance_text = f"Complies with {cm.group('refs')} of {cm.group('doc')}."
                    i += 1
                    break
                desc_parts.append(epayload)
                i += 1

            description = " ".join(desc_parts).strip()
            body = (
                f"Product: {product_name} (Code: {code}). "
                f"Category: {current_category}. Manufacturer: {manufacturer}. "
                f"{description} "
                f"Technical specifications - {table_text} "
                f"{compliance_text}"
            ).strip()
            body = re.sub(r"\s+", " ", body)

            chunks.append(Chunk(
                text=f"[{current_category}] {body}",
                metadata={
                    "source": path,
                    "category": current_category,
                    "product_name": product_name,  # ADDED -- needed by rag/migrate_to_chroma.py::sync_materials_register() to populate section_title without re-parsing chunk.text with a regex
                    "product_code": code,
                    "manufacturer": manufacturer,
                    "page": page_no,
                },
            ))
            continue

        i += 1

    return chunks


if __name__ == "__main__":
    from materials_data import CATEGORIES

    cs = load_and_chunk("/mnt/user-data/outputs/approved_materials_register.pdf")

    # Regression guard: if a future change to the extraction logic silently
    # drops or duplicates a product (exactly the failure mode found during
    # development -- a merged footer/page-number line swallowed one
    # product), this fails loudly instead of shipping a silently incomplete
    # index.
    expected_codes = {p["code"] for cat in CATEGORIES for p in cat["products"]}
    found_codes = {c.metadata["product_code"] for c in cs}
    assert found_codes == expected_codes, (
        f"Product count/identity mismatch: missing={expected_codes - found_codes}, "
        f"unexpected={found_codes - expected_codes}"
    )
    assert len(cs) == len(expected_codes), "Duplicate chunk for at least one product code"

    print("chunks:", len(cs), "-- OK, matches source data exactly")
    lens = [len(c.text) for c in cs]
    print("chars min/median/max:", min(lens), sorted(lens)[len(lens)//2], max(lens))
    print()
    for c in cs[:2]:
        print("-" * 70)
        print(c.metadata)
        print(c.text)
        print()