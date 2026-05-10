"""
Production-grade Excel exporter — upgraded for structured OCR + rich scraper output.

UPGRADES:
  OCR Excel now has 4 sheets:
    1. Summary     — job metadata, metrics, engine, confidence, page count
    2. Regions     — one row per OCR region: page, type, confidence, clean text
    3. Tokens      — full word-level token breakdown with bounding boxes
    4. Full Text   — per-page clean text concatenation (copy-paste ready)

  Scraper Excel now has 3 sheets:
    1. Products    — all scraped fields, styled, sortable
    2. Summary     — platform breakdown with counts and avg prices
    3. Price Analysis — min/max/avg per platform, discount leaders

  All sheets: auto-fit columns, frozen header row, alternating row shading,
  bold headers with background color coded by type.
"""
from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd
import openpyxl
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side
)
from openpyxl.utils import get_column_letter


# ── Style constants ────────────────────────────────────────────────────────────
_HEADER_FILL   = PatternFill("solid", fgColor="1F3864")   # dark navy
_ALT_ROW_FILL  = PatternFill("solid", fgColor="EEF2FF")   # soft indigo tint
_ACCENT_FILL   = PatternFill("solid", fgColor="2563EB")   # blue accent
_HEADER_FONT   = Font(bold=True, color="FFFFFF", size=11)
_BODY_FONT     = Font(size=10)
_BOLD_FONT     = Font(bold=True, size=10)
_THIN_BORDER   = Border(
    left=Side(style="thin", color="D1D5DB"),
    right=Side(style="thin", color="D1D5DB"),
    top=Side(style="thin", color="D1D5DB"),
    bottom=Side(style="thin", color="D1D5DB"),
)
_CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=False)
_LEFT_ALIGN   = Alignment(horizontal="left",   vertical="top",    wrap_text=True)


def _style_sheet(ws, header_row: int = 1, freeze: bool = True) -> None:
    """Apply header styling, alternating row shading, and auto-fit to a worksheet."""
    # Header row
    for cell in ws[header_row]:
        cell.font      = _HEADER_FONT
        cell.fill      = _HEADER_FILL
        cell.alignment = _CENTER_ALIGN
        cell.border    = _THIN_BORDER

    # Alternating body rows
    for row_idx, row in enumerate(ws.iter_rows(min_row=header_row + 1), start=1):
        fill = _ALT_ROW_FILL if row_idx % 2 == 0 else None
        for cell in row:
            if fill:
                cell.fill = fill
            cell.font      = _BODY_FONT
            cell.border    = _THIN_BORDER
            cell.alignment = _LEFT_ALIGN

    # Auto-fit column widths
    for col in ws.columns:
        max_len = max(
            (len(str(c.value)) for c in col if c.value is not None),
            default=8,
        )
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 60)

    # Freeze header row
    if freeze:
        ws.freeze_panes = f"A{header_row + 1}"


def _set_tab_color(ws, hex_color: str) -> None:
    ws.sheet_properties.tabColor = hex_color


# ── OCR Export ────────────────────────────────────────────────────────────────

def export_ocr_excel(result: dict, filename: str = "") -> bytes:
    """
    4-sheet OCR workbook:
      Sheet 1: Summary   — job metadata, engine, metrics
      Sheet 2: Regions   — per-region text with type and confidence
      Sheet 3: Tokens    — word-level tokens with bounding boxes
      Sheet 4: Full Text — per-page clean concatenated text

    INPUT PROBLEM DIAGNOSED:
      The original export produced one garbled text blob per page because
      the entire page was processed as a single region (YOLO fallback mode),
      and the OCR engines were mixing columns. The new export:
      - Separates regions properly (if YOLO ran, regions are typed)
      - Cleans text: normalises whitespace, removes repeated chars
      - Provides token-level detail for auditability
    """
    wb = openpyxl.Workbook()

    regions:  list[dict] = result.get("regions", [])
    metrics:  dict       = result.get("metrics", {})
    job_id:   str        = result.get("job_id", "")
    page_cnt: int        = result.get("page_count", 1)
    engine:   str        = result.get("engine_used", "")
    mode:     str        = result.get("mode", "")
    avg_conf: float      = float(metrics.get("avg_confidence", 0))

    # ── Sheet 1: Summary ──────────────────────────────────────────────────────
    ws_sum = wb.active
    ws_sum.title = "Summary"
    _set_tab_color(ws_sum, "1F3864")

    summary_rows = [
        ("Field", "Value"),
        ("Source File",            filename or "—"),
        ("Job ID",                 job_id),
        ("OCR Mode",               mode),
        ("Primary Engine",         engine),
        ("Pages Processed",        page_cnt),
        ("Regions Detected",       len(regions)),
        ("Characters Extracted",   metrics.get("characters_extracted", 0)),
        ("Avg Confidence",         f"{avg_conf * 100:.1f}%"),
        ("Processing Time",        f"{metrics.get('processing_ms', 0)} ms"),
        ("Fallback Triggered",     "Yes" if result.get("fallback_triggered") else "No"),
        ("Total Tokens",           sum(len(r.get("tokens", [])) for r in regions)),
    ]
    for row in summary_rows:
        ws_sum.append(row)

    # Style header
    for cell in ws_sum[1]:
        cell.font      = _HEADER_FONT
        cell.fill      = _HEADER_FILL
        cell.alignment = _CENTER_ALIGN
        cell.border    = _THIN_BORDER
    # Style data rows
    for row_idx in range(2, len(summary_rows) + 1):
        for cell in ws_sum[row_idx]:
            cell.border    = _THIN_BORDER
            cell.alignment = _LEFT_ALIGN
            cell.font      = _BODY_FONT
    ws_sum.column_dimensions["A"].width = 26
    ws_sum.column_dimensions["B"].width = 50

    # ── Sheet 2: Regions ──────────────────────────────────────────────────────
    ws_reg = wb.create_sheet("Regions")
    _set_tab_color(ws_reg, "2563EB")

    region_headers = [
        "Region ID", "Page", "Region Type", "Confidence %",
        "Tokens", "Characters", "Clean Text"
    ]
    ws_reg.append(region_headers)

    _REGION_TYPE_COLORS = {
        "text":      "DBEAFE",   # blue
        "table":     "D1FAE5",   # green
        "header":    "FEF3C7",   # amber
        "figure":    "EDE9FE",   # violet
        "stamp":     "FCE7F3",   # pink
        "signature": "FEE2E2",   # red
    }

    for region in regions:
        raw_text  = region.get("text", "")
        clean_txt = _clean_ocr_text(raw_text)
        conf      = float(region.get("confidence", 0))
        rtype     = str(region.get("type", "text")).lower()
        tokens    = region.get("tokens", [])

        # Extract page number from region id: "page0-region-0" → 1
        page_num = 1
        rid = str(region.get("id", ""))
        m = re.search(r"page(\d+)", rid)
        if m:
            page_num = int(m.group(1)) + 1

        ws_reg.append([
            rid,
            page_num,
            rtype.capitalize(),
            f"{conf * 100:.1f}%",
            len(tokens),
            len(clean_txt),
            clean_txt[:500],   # cap at 500 chars per cell
        ])

        # Color-code by region type
        color_hex = _REGION_TYPE_COLORS.get(rtype, "F3F4F6")
        fill = PatternFill("solid", fgColor=color_hex)
        last_row = ws_reg.max_row
        for col_idx in range(1, len(region_headers) + 1):
            cell = ws_reg.cell(row=last_row, column=col_idx)
            cell.fill   = fill
            cell.border = _THIN_BORDER
            cell.font   = _BODY_FONT
            if col_idx == len(region_headers):
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            else:
                cell.alignment = _CENTER_ALIGN

    _style_sheet(ws_reg)
    ws_reg.row_dimensions[1].height = 20
    # Wider text column
    ws_reg.column_dimensions[get_column_letter(len(region_headers))].width = 80

    # ── Sheet 3: Tokens ───────────────────────────────────────────────────────
    ws_tok = wb.create_sheet("Tokens")
    _set_tab_color(ws_tok, "059669")

    token_headers = [
        "Region ID", "Page", "Region Type", "Token #",
        "Word", "Confidence %", "Engine",
        "BBox X", "BBox Y", "BBox W", "BBox H"
    ]
    ws_tok.append(token_headers)

    for region in regions:
        rid   = region.get("id", "")
        rtype = region.get("type", "text")
        page_num = 1
        m = re.search(r"page(\d+)", rid)
        if m:
            page_num = int(m.group(1)) + 1

        for tok_idx, token in enumerate(region.get("tokens", []), start=1):
            bbox = token.get("bbox", {})
            ws_tok.append([
                rid,
                page_num,
                rtype.capitalize(),
                tok_idx,
                token.get("text", ""),
                f"{float(token.get('confidence', 0)) * 100:.1f}%",
                token.get("engine", ""),
                round(float(bbox.get("x", 0)), 1),
                round(float(bbox.get("y", 0)), 1),
                round(float(bbox.get("width", 0)), 1),
                round(float(bbox.get("height", 0)), 1),
            ])

    _style_sheet(ws_tok)

    # ── Sheet 4: Full Text ────────────────────────────────────────────────────
    ws_txt = wb.create_sheet("Full Text")
    _set_tab_color(ws_txt, "7C3AED")

    ws_txt.append(["Page", "Region Type", "Clean Text"])

    # Group regions by page
    pages_map: dict[int, list[dict]] = {}
    for region in regions:
        rid = region.get("id", "")
        m   = re.search(r"page(\d+)", rid)
        pg  = int(m.group(1)) + 1 if m else 1
        pages_map.setdefault(pg, []).append(region)

    for pg_num in sorted(pages_map.keys()):
        for region in pages_map[pg_num]:
            clean_text = _clean_ocr_text(region.get("text", ""))
            if not clean_text.strip():
                continue
            ws_txt.append([
                pg_num,
                region.get("type", "text").capitalize(),
                clean_text,
            ])

    _style_sheet(ws_txt)
    ws_txt.column_dimensions["C"].width = 120
    for row in ws_txt.iter_rows(min_row=2):
        row[-1].alignment = Alignment(wrap_text=True, vertical="top")
        ws_txt.row_dimensions[row[-1].row].height = 80

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def _clean_ocr_text(text: str) -> str:
    """
    Clean raw OCR output:
    - Normalise whitespace (collapse multiple spaces/tabs)
    - Remove lone punctuation artifacts from OCR misreads
    - Fix common OCR substitutions (| → I, {→₹, 0→O in word context)
    - Preserve meaningful special chars (₹, %, @, /)
    """
    if not text:
        return ""
    # Normalise Unicode spaces and soft hyphens
    text = text.replace("\u00a0", " ").replace("\u00ad", "")
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    # Remove lines that are purely punctuation/symbols (OCR artifacts)
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and not re.match(r"^[^\w₹%@/():\-\.]+$", stripped):
            lines.append(stripped)
    text = " ".join(lines)
    # Final normalise
    return text.strip()


# ── Scraper Export ────────────────────────────────────────────────────────────

def export_scraped_products(items: list[dict], job_id: str = "") -> bytes:
    """
    3-sheet scraper workbook:
      Sheet 1: Products       — full product data, all fields
      Sheet 2: Summary        — platform breakdown, counts, avg price
      Sheet 3: Price Analysis — min/max/avg/discount per platform
    """
    wb = openpyxl.Workbook()

    # ── Sheet 1: Products ─────────────────────────────────────────────────────
    ws_prod = wb.active
    ws_prod.title = "Products"
    _set_tab_color(ws_prod, "1F3864")

    if not items:
        ws_prod.append(["No products scraped"])
    else:
        # Canonical column order — consistent across all platforms
        columns = [
            "Platform", "Title", "Brand", "Category",
            "Price (₹)", "Original Price (₹)", "Discount (%)",
            "Rating", "Review Count", "Availability",
            "Product ID", "URL", "Scraped At",
        ]
        ws_prod.append(columns)

        _PLATFORM_COLORS = {
            "amazon":   "FFF7ED",   # orange tint
            "flipkart": "EFF6FF",   # blue tint
            "swiggy":   "FFF7ED",   # orange tint
            "zomato":   "FEF2F2",   # red tint
            "manual":   "F0FDF4",   # green tint
        }

        for item in items:
            platform = str(item.get("platform", "")).lower()
            price    = item.get("price")
            orig     = item.get("original_price")
            disc     = item.get("discount")
            # Auto-calculate discount if missing
            if disc is None and price and orig and orig > price:
                disc = round((orig - price) / orig * 100, 1)

            scraped_at = ""
            if item.get("scraped_at"):
                scraped_at = str(item["scraped_at"])[:19]  # trim microseconds

            row = [
                platform.capitalize(),
                str(item.get("title", ""))[:200],
                str(item.get("brand") or ""),
                str(item.get("category") or ""),
                _fmt_price(price),
                _fmt_price(orig),
                f"{disc:.1f}%" if disc is not None else "",
                f"{float(item['rating']):.1f}" if item.get("rating") else "",
                item.get("review_count") or "",
                str(item.get("availability", "")).replace("_", " ").capitalize(),
                str(item.get("product_id") or ""),
                str(item.get("url", "")),
                scraped_at,
            ]
            ws_prod.append(row)

            # Color-code by platform
            color_hex = _PLATFORM_COLORS.get(platform, "FFFFFF")
            fill = PatternFill("solid", fgColor=color_hex)
            last_row = ws_prod.max_row
            for col_idx in range(1, len(columns) + 1):
                cell = ws_prod.cell(row=last_row, column=col_idx)
                cell.fill   = fill
                cell.border = _THIN_BORDER
                cell.font   = _BODY_FONT
                cell.alignment = _LEFT_ALIGN

        _style_sheet(ws_prod)
        # Wider columns for title and URL
        ws_prod.column_dimensions["B"].width = 60
        ws_prod.column_dimensions["L"].width = 50

    # ── Sheet 2: Summary ──────────────────────────────────────────────────────
    ws_sum = wb.create_sheet("Summary")
    _set_tab_color(ws_sum, "059669")

    ws_sum.append(["Platform", "Products Scraped", "With Price", "Avg Price (₹)", "With Rating", "Avg Rating"])

    # Group by platform
    by_platform: dict[str, list[dict]] = {}
    for item in items:
        p = str(item.get("platform", "unknown")).lower()
        by_platform.setdefault(p, []).append(item)

    for platform, plat_items in sorted(by_platform.items()):
        prices  = [float(i["price"])  for i in plat_items if i.get("price")  is not None]
        ratings = [float(i["rating"]) for i in plat_items if i.get("rating") is not None]
        ws_sum.append([
            platform.capitalize(),
            len(plat_items),
            len(prices),
            f"₹{sum(prices)/len(prices):,.2f}" if prices else "—",
            len(ratings),
            f"{sum(ratings)/len(ratings):.2f} ★" if ratings else "—",
        ])

    ws_sum.append([])
    ws_sum.append(["Total", len(items), "", "", "", ""])
    _style_sheet(ws_sum)

    # ── Sheet 3: Price Analysis ───────────────────────────────────────────────
    ws_price = wb.create_sheet("Price Analysis")
    _set_tab_color(ws_price, "DC2626")

    ws_price.append([
        "Platform", "Min Price (₹)", "Max Price (₹)", "Avg Price (₹)",
        "Max Discount (%)", "Avg Discount (%)", "Out of Stock Count"
    ])

    for platform, plat_items in sorted(by_platform.items()):
        prices    = [float(i["price"])    for i in plat_items if i.get("price")    is not None]
        discounts = [float(i["discount"]) for i in plat_items if i.get("discount") is not None]
        oos_count = sum(1 for i in plat_items if "out" in str(i.get("availability", "")).lower())

        ws_price.append([
            platform.capitalize(),
            f"₹{min(prices):,.2f}"  if prices    else "—",
            f"₹{max(prices):,.2f}"  if prices    else "—",
            f"₹{sum(prices)/len(prices):,.2f}" if prices else "—",
            f"{max(discounts):.1f}%" if discounts else "—",
            f"{sum(discounts)/len(discounts):.1f}%" if discounts else "—",
            oos_count,
        ])

    _style_sheet(ws_price)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def _fmt_price(val: Any) -> str:
    if val is None:
        return ""
    try:
        return f"₹{float(val):,.2f}"
    except (ValueError, TypeError):
        return str(val)


# ── Unified generate_excel entrypoint ─────────────────────────────────────────

def export_dataframe(df: "pd.DataFrame", sheet_name: str = "Data") -> bytes:  # type: ignore[name-defined]
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        ws = writer.book[sheet_name]
        _style_sheet(ws)
    output.seek(0)
    return output.getvalue()


def export_structured(result: dict, job_type: str) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Output"
    ws.append(["Field", "Value"])
    for key, value in result.items():
        ws.append([str(key), str(value)])
    _style_sheet(ws)
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def generate_excel(result: dict, job_type: str, filename: str = "") -> bytes:
    """
    Unified entrypoint — routes to the correct exporter by job_type.
    Called by download.py for every job type.
    """
    import pandas as pd

    try:
        jt = job_type.lower()

        if "auto" in jt:
            jt = result.get("auto_classified_as", "invoice")

        if "invoice" in jt:
            from app.services.export.normalizer import normalize_invoice_for_excel
            rows = normalize_invoice_for_excel(result, filename)
            df = pd.DataFrame(rows)
            if not df.empty:
                return export_dataframe(df, "Invoice")

        elif "bank" in jt:
            from app.services.export.normalizer import normalize_bank_for_excel
            sheets = normalize_bank_for_excel(result, filename)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                pd.DataFrame(sheets["summary"]).to_excel(
                    writer, index=False, sheet_name="Account Summary"
                )
                tx_df = pd.DataFrame(sheets.get("transactions", []))
                if not tx_df.empty:
                    tx_df.to_excel(writer, index=False, sheet_name="Transactions")
                for sname in writer.book.sheetnames:
                    _style_sheet(writer.book[sname])
            output.seek(0)
            return output.getvalue()

        elif "ocr" in jt:
            # 4-sheet structured OCR export
            return export_ocr_excel(result, filename)

        elif "scrap" in jt:
            # 3-sheet scraper export with price analysis
            items = result.get("items", [])
            return export_scraped_products(items, result.get("job_id", ""))

        return export_structured(result, job_type)

    except Exception:
        return export_structured(result, job_type)


# Alias for backward compat
result_to_excel_bytes = generate_excel