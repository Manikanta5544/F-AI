"""
Production-grade data normalizers.
Converts extracted JSON -> Excel-ready flat rows.
Preserves VALUE + CONFIDENCE + SOURCE. Never crashes on missing fields.
"""
from __future__ import annotations
from typing import Any, Dict, List
import re


def _safe_field(field: Any) -> Dict[str, Any]:
    if not field:
        return {"value": "", "confidence": None, "source": ""}
    if isinstance(field, dict):
        return {
            "value": field.get("value", ""),
            "confidence": field.get("confidence"),
            "source": field.get("engine") or field.get("source", ""),
        }
    return {"value": str(field), "confidence": None, "source": ""}


def _value(field: Any) -> str:
    v = _safe_field(field)["value"]
    return str(v) if v is not None else ""


def _confidence(field: Any) -> str:
    c = _safe_field(field)["confidence"]
    if c is None: return ""
    try: return f"{float(c) * 100:.0f}%"
    except Exception: return ""


def _source(field: Any) -> str:
    return str(_safe_field(field)["source"] or "")


def normalize_invoice_for_excel(result: Dict[str, Any], filename: str = "") -> List[Dict[str, Any]]:
    """
    Invoice -> flat Excel rows. One row per line item.
    Includes: Invoice#, Date, Vendor, Buyer, Subtotal, Tax, Tax%, Total, line items.
    """
    # Parse tax% out of the tax display string e.g. "₹0.76 (18%) [IGST 18%: ₹0.76]"
    tax_raw = _value(result.get("tax"))
    tax_pct = ""
    m_pct = re.search(r"\((\d+(?:\.\d+)?%)\)", tax_raw)
    if m_pct:
        tax_pct = m_pct.group(1)

    # Separate CGST/SGST from the display
    cgst_display = ""
    sgst_display = ""
    m_cgst = re.search(r"CGST:\s*(₹[\d,.]+)", tax_raw, re.I)
    m_sgst = re.search(r"SGST:\s*(₹[\d,.]+)", tax_raw, re.I)
    if m_cgst: cgst_display = m_cgst.group(1)
    if m_sgst: sgst_display = m_sgst.group(1)

    # Clean tax amount (remove parenthetical)
    tax_amount = re.sub(r"\s*\[.*?\]", "", re.sub(r"\s*\(.*?\)", "", tax_raw)).strip()

    header = {
        "Source File":            filename,
        "Invoice Number":         _value(result.get("invoice_number")),
        "Invoice # Confidence":   _confidence(result.get("invoice_number")),
        "Invoice # Engine":       _source(result.get("invoice_number")),
        "Invoice Date":           _value(result.get("invoice_date")),
        "Due Date":               _value(result.get("due_date")),
        "Vendor / Seller":        _value(result.get("vendor")),
        "Vendor Confidence":      _confidence(result.get("vendor")),
        "Buyer / Bill To":        _value(result.get("buyer")),
        "Subtotal (Before Tax)":  _value(result.get("subtotal")),
        "Tax Amount":             tax_amount,
        "Tax %":                  tax_pct,
        "CGST Amount":            cgst_display,
        "SGST Amount":            sgst_display,
        "Grand Total":            _value(result.get("total")),
        "Total Confidence":       _confidence(result.get("total")),
        "Human Review Required":  "Yes" if result.get("human_review_required") else "No",
    }

    line_items = result.get("line_items", [])

    if line_items:
        rows: List[Dict[str, Any]] = []
        for idx, item in enumerate(line_items, start=1):
            row = dict(header) if idx == 1 else {k: "" for k in header}
            row.update({
                "Item #":       idx,
                "Description":  _value(item.get("description")),
                "Qty":          _value(item.get("quantity")),
                "Unit Price":   _value(item.get("unit_price")),
                "Line Total":   _value(item.get("total")),
            })
            rows.append(row)
    else:
        rows = [{
            **header,
            "Item #": "", "Description": "No line items detected",
            "Qty": "", "Unit Price": "", "Line Total": "",
        }]

    return rows


def normalize_bank_for_excel(result: Dict[str, Any], filename: str = "") -> Dict[str, List[Dict[str, Any]]]:
    """
    Bank statement -> multi-sheet format: Account Summary + Transactions.
    """
    summary_fields = [
        ("Source File",           filename, "", ""),
        ("Bank Name",             _value(result.get("bank_name")),             _confidence(result.get("bank_name")),             _source(result.get("bank_name"))),
        ("Account Holder",        _value(result.get("account_holder")),        _confidence(result.get("account_holder")),        _source(result.get("account_holder"))),
        ("Account Number",        _value(result.get("account_number")),        _confidence(result.get("account_number")),        _source(result.get("account_number"))),
        ("IFSC Code",             _value(result.get("ifsc")),                  _confidence(result.get("ifsc")),                  _source(result.get("ifsc"))),
        ("Opening Balance",       _value(result.get("opening_balance")),       _confidence(result.get("opening_balance")),       _source(result.get("opening_balance"))),
        ("Closing Balance",       _value(result.get("closing_balance")),       _confidence(result.get("closing_balance")),       _source(result.get("closing_balance"))),
        ("Statement From",        _value(result.get("statement_period_from")), _confidence(result.get("statement_period_from")), ""),
        ("Statement To",          _value(result.get("statement_period_to")),   _confidence(result.get("statement_period_to")),   ""),
        ("Template Used",         result.get("template_used") or "Generic",   "", ""),
        ("Is Structured",         "Yes" if result.get("is_structured") else "No", "", ""),
        ("Human Review Required", "Yes" if result.get("human_review_required") else "No", "", ""),
    ]

    summary = [
        {"Field": label, "Value": value, "Confidence": conf, "Source / Engine": src}
        for label, value, conf, src in summary_fields
    ]

    transactions: List[Dict[str, Any]] = []
    for idx, tx in enumerate(result.get("transactions", []), start=1):
        transactions.append({
            "Sl No":       idx,
            "Source File": filename,
            "Date":        _value(tx.get("date")),
            "Narration":   _value(tx.get("narration")),
            "Debit (₹)":   _value(tx.get("debit")),
            "Credit (₹)":  _value(tx.get("credit")),
            "Balance (₹)": _value(tx.get("balance")),
        })

    if not transactions:
        transactions.append({
            "Sl No": "", "Source File": filename, "Date": "",
            "Narration": "No transactions extracted",
            "Debit (₹)": "", "Credit (₹)": "", "Balance (₹)": "",
        })

    return {"summary": summary, "transactions": transactions}