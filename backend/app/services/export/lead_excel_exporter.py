"""
app/services/export/lead_excel_exporter.py

B2B Lead Intelligence Excel export.
One sheet per ImexBay segment + Summary + High Priority.
Columns: Company Name | City | Phone | Email | Website | Address | Description | Services | Source | Confidence%

Called from:
  1. lead_scraper_tasks.py  → after scraping completes (rows = list of dicts)
  2. download.py via generate_excel() → for user download (result = job.result dict)
     In case 2, rows come from DB via the route handler, NOT from job.result directly.
"""
from __future__ import annotations

import io
from collections import defaultdict

import re
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def _safe_sheet_name(name: str) -> str:
    if not name:
        return "Sheet"

    name = re.sub(r'[\\/*?:\[\]]', '', name)
    name = name.replace("&", "and")
    name = " ".join(name.split())
    return name[:31] or "Sheet"

def _fill(h: str) -> PatternFill:
    return PatternFill(fill_type="solid", fgColor=h)

def _border() -> Border:
    s = Side(style="thin", color="E2E8F0")
    return Border(left=s, right=s, top=s, bottom=s)

H_FONT = Font(bold=True, color="FFFFFF", size=10, name="Calibri")
BODY   = Font(size=10, name="Calibri")
BOLD   = Font(bold=True, size=10, name="Calibri")
THIN   = _border()
CTR    = Alignment(horizontal="center", vertical="center")
LFT    = Alignment(horizontal="left", vertical="top", wrap_text=True)
WRAP   = Alignment(horizontal="left", vertical="center", wrap_text=True)
NAVY   = _fill("1F3864")
GREEN  = _fill("059669")
RED    = _fill("DC2626")
PURP   = _fill("7C3AED")

_SEG_COLORS = {
    "importer":           _fill("FEE2E2"), "exporter":           _fill("FFF1F2"),
    "manufacturer":       _fill("F0FDF4"), "trader":             _fill("FFFBEB"),
    "freight_forwarder":  _fill("F0FDFA"), "customs_broker":     _fill("FAFAFA"),
    "insurer":            _fill("EFF6FF"), "bank_trade_finance":  _fill("F0F9FF"),
    "ca_firm":            _fill("D1FAE5"), "virtual_cfo":        _fill("DBEAFE"),
    "accounting":         _fill("FEF3C7"), "logistics":          _fill("F0F9FF"),
    "fintech":            _fill("FDF4FF"), "startup_sme":        _fill("F5F3FF"),
    "ecommerce":          _fill("FFF7ED"), "marketing_sales":    _fill("FDF2F8"),
    "operations":         _fill("F0FDF4"),
}

_SEG_LABELS = {
    "importer":          "Importers",
    "exporter":          "Exporters",
    "manufacturer":      "Manufacturers",
    "trader":            "Traders",
    "freight_forwarder": "Freight Forwarders",
    "customs_broker":    "Customs Brokers",
    "insurer":           "Insurers",
    "bank_trade_finance":"Banks / Trade Finance",
    "ca_firm":           "CA Firms",
    "virtual_cfo":       "Virtual CFOs",
    "accounting":        "Accounting",
    "logistics":         "Logistics",
    "fintech":           "Fintech",
    "startup_sme":       "Startups / SMEs",
    "ecommerce":         "E-commerce",
    "marketing_sales":   "Marketing & Sales",
    "operations":        "Operations / Tech",
}

_COLS   = ["#","Company Name","City","Phone","Email","Website",
           "Address","Description","Services","Source","Conf%","Founded"]
_WIDTHS = [4, 36, 14, 20, 30, 36, 30, 45, 30, 14, 8, 10]


def _write_header(ws: openpyxl.worksheet.worksheet.Worksheet,
                  hdr_fill: PatternFill | None = None) -> None:
    ws.append(_COLS)
    fill = hdr_fill or NAVY
    for c in ws[1]:
        c.font = H_FONT; c.fill = fill; c.alignment = CTR; c.border = THIN
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 20
    for i, w in enumerate(_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _write_lead_row(ws: openpyxl.worksheet.worksheet.Worksheet,
                    row_num: int, idx: int, lead: dict,
                    base_fill: PatternFill) -> None:
    conf = float(lead.get("confidence_score", 0))
    ws.append([
        idx,
        lead.get("company_name", ""),
        lead.get("city", ""),
        lead.get("phone", ""),
        lead.get("email", ""),
        lead.get("website", ""),
        lead.get("address", ""),
        str(lead.get("description", ""))[:200],
        lead.get("services", ""),
        lead.get("source_platform", "").replace("_", " ").title(),
        f"{int(conf * 100)}%",
        lead.get("founded_year", ""),
    ])
    row_fill = base_fill if idx % 2 == 0 else _fill("FFFFFF")
    for ci in range(1, len(_COLS) + 1):
        c = ws.cell(row_num, ci)
        c.fill = row_fill; c.border = THIN
        if ci == 4 and lead.get("phone"):
            c.font = Font(bold=True, size=10, color="065F46", name="Calibri")
            c.alignment = CTR
        elif ci in (5, 6):
            c.font = Font(size=10, color="1D4ED8", name="Calibri"); c.alignment = LFT
        elif ci == 11:
            color = "065F46" if conf >= 0.7 else ("92400E" if conf >= 0.4 else "991B1B")
            c.font = Font(bold=True, size=10, color=color, name="Calibri"); c.alignment = CTR
        elif ci == 8:
            c.font = BODY; c.alignment = WRAP; ws.row_dimensions[row_num].height = 30
        else:
            c.font = BODY; c.alignment = LFT


def export_leads_excel(leads: list[dict], job_id: str = "") -> bytes:
    """
    Generate segment-per-sheet Excel workbook from B2B lead dicts.

    Expected keys (all optional except company_name + category):
      company_name, category, city, phone, email, website,
      address, description, services, source_platform,
      source_url, confidence_score, founded_year, employee_count
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default empty sheet

    # Group by category
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for lead in leads:
        by_cat[str(lead.get("category", "other")).lower()].append(lead)

    # ── One sheet per segment ─────────────────────────────────────────────────
    for seg_key in _SEG_LABELS:
        cat_leads = by_cat.get(seg_key, [])
        if not cat_leads:
            continue
        label    = _SEG_LABELS[seg_key]
        seg_fill = _SEG_COLORS.get(seg_key, _fill("F8FAFC"))
        print("Creating sheet:", label)
        try:
            ws = wb.create_sheet(title=_safe_sheet_name(label))
        except Exception as e:
            print("Sheet creation failed:", label, "error:", e)
            ws = wb.create_sheet(title="Sheet_" + str(len(wb.sheetnames)))
        ws.sheet_properties.tabColor = "1F3864"
        _write_header(ws)
        for idx, lead in enumerate(cat_leads, 1):
            _write_lead_row(ws, idx + 1, idx, lead, seg_fill)
        ws.auto_filter.ref = f"A1:{get_column_letter(len(_COLS))}{ws.max_row}"

    # Catch any un-labelled categories
    for cat_key, cat_leads in by_cat.items():
        if cat_key in _SEG_LABELS or not cat_leads:
            continue
        ws = wb.create_sheet(title=_safe_sheet_name(cat_key))
        _write_header(ws)
        for idx, lead in enumerate(cat_leads, 1):
            _write_lead_row(ws, idx + 1, idx, lead, _fill("F8FAFC"))

    # ── Summary sheet ─────────────────────────────────────────────────────────
    ws_sum = wb.create_sheet(_safe_sheet_name("Summary"))
    ws_sum.sheet_properties.tabColor = "059669"
    ws_sum.append(["Segment","Leads","With Phone","With Email",
                   "With Website","Cities","Avg Conf%"])
    _write_header(ws_sum, GREEN)

    all_seg_keys = list(_SEG_LABELS.keys()) + [k for k in by_cat if k not in _SEG_LABELS]
    for ri, seg in enumerate(all_seg_keys, 2):
        sl = by_cat.get(seg, [])
        if not sl:
            continue
        cities = {l.get("city", "") for l in sl if l.get("city")}
        confs  = [float(l.get("confidence_score", 0)) for l in sl]
        ws_sum.append([
            _SEG_LABELS.get(seg, seg.replace("_", " ").title()),
            len(sl),
            sum(1 for l in sl if l.get("phone")),
            sum(1 for l in sl if l.get("email")),
            sum(1 for l in sl if l.get("website")),
            len(cities),
            f"{sum(confs)/len(confs)*100:.0f}%" if confs else "—",
        ])
        fill = _SEG_COLORS.get(seg, _fill("F8FAFC")) if ri % 2 == 0 else _fill("FFFFFF")
        for ci in range(1, 8):
            c = ws_sum.cell(ri, ci)
            c.fill = fill; c.border = THIN; c.font = BODY
            c.alignment = LFT if ci == 1 else CTR

    # Totals row
    total_leads = len(leads)
    ws_sum.append([
        "TOTAL", total_leads,
        sum(1 for l in leads if l.get("phone")),
        sum(1 for l in leads if l.get("email")),
        sum(1 for l in leads if l.get("website")),
        len({l.get("city","") for l in leads if l.get("city")}),
        ""
    ])
    for ci in range(1, 8):
        c = ws_sum.cell(ws_sum.max_row, ci)
        c.fill = NAVY; c.border = THIN
        c.font = Font(bold=True, color="FFFFFF", size=10, name="Calibri"); c.alignment = CTR

    for col in ws_sum.columns:
        ws_sum.column_dimensions[col[0].column_letter].width = min(
            max((len(str(c.value)) for c in col if c.value), default=8) + 3, 32)

    # ── High Priority (phone + email or website) ──────────────────────────────
    ws_hot = wb.create_sheet(_safe_sheet_name("High Priority"))
    ws_hot.sheet_properties.tabColor = "DC2626"
    _write_header(ws_hot, RED)

    hot = sorted(
        [l for l in leads if l.get("phone") and (l.get("email") or l.get("website"))],
        key=lambda x: float(x.get("confidence_score", 0)),
        reverse=True,
    )
    if not hot:
        hot = sorted(leads, key=lambda x: float(x.get("confidence_score", 0)), reverse=True)[:50]

    for idx, lead in enumerate(hot, 1):
        _write_lead_row(ws_hot, idx + 1, idx, lead,
                        _fill("D1FAE5") if idx % 2 == 0 else _fill("FFFFFF"))
    ws_hot.auto_filter.ref = f"A1:{get_column_letter(len(_COLS))}{ws_hot.max_row}"

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()