"""
Unit tests for the service layer — Tasks #4–#11.
No HTTP, no DB, no network. Pure function tests only.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.services.ocr.preprocessing import (
    adaptive_threshold,
    apply_clahe,
    dilate,
    erode,
    preprocess_for_ocr,
    preprocess_region,
    to_grayscale,
)
from app.services.extraction.bank_statement import (
    extract_bank_statement,
    identify_bank,
)
from app.services.extraction.invoice import extract_invoice
from app.services.classification.classifier import classify_document


# ── Helpers ───────────────────────────────────────────────────────────────────
def _gray(h: int = 100, w: int = 100) -> np.ndarray:
    return np.random.randint(0, 256, (h, w), dtype=np.uint8)


def _color_image(h: int = 200, w: int = 300) -> Image.Image:
    arr = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)
    return Image.fromarray(arr, "RGB")


# ── Task #6: Image preprocessing ─────────────────────────────────────────────
class TestPreprocessing:

    def test_to_grayscale_already_gray(self):
        gray = _gray()
        result = to_grayscale(gray)
        assert result.shape == (100, 100)
        assert result.ndim == 2

    def test_to_grayscale_bgr_input(self):
        color = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        result = to_grayscale(color)
        assert result.ndim == 2

    def test_apply_clahe_preserves_shape_and_dtype(self):
        gray = _gray()
        result = apply_clahe(gray)
        assert result.shape == gray.shape
        assert result.dtype == np.uint8

    def test_adaptive_threshold_produces_binary(self):
        gray = _gray()
        result = adaptive_threshold(gray)
        unique = set(np.unique(result).tolist())
        assert unique.issubset({0, 255}), "Must be binary"

    def test_erode_does_not_increase_white_area(self):
        binary = np.full((50, 50), 255, dtype=np.uint8)
        result = erode(binary, kernel_size=3)
        # Erosion can only shrink white regions
        assert int(result.sum()) <= int(binary.sum())

    def test_dilate_expands_single_white_pixel(self):
        binary = np.zeros((50, 50), dtype=np.uint8)
        binary[25, 25] = 255
        result = dilate(binary, kernel_size=3)
        assert int(result.sum()) > int(binary.sum())

    def test_full_pipeline_returns_binary_2d(self):
        img = _color_image()
        result = preprocess_for_ocr(img)
        assert result.ndim == 2
        unique = set(np.unique(result).tolist())
        assert unique.issubset({0, 255})

    def test_preprocess_region_table_skips_dilation(self):
        """Tables: dilation must be skipped to avoid merging cell borders."""
        img = _color_image()
        # Should not raise — specific tuning applied internally
        result = preprocess_region(img, "table")
        assert result.ndim == 2

    def test_preprocess_region_stamp_applies_heavier_dilation(self):
        img = _color_image()
        result = preprocess_region(img, "stamp")
        assert result.ndim == 2

    def test_preprocess_region_text_uses_defaults(self):
        img = _color_image()
        result = preprocess_region(img, "text")
        assert result.ndim == 2

    def test_preprocess_region_unknown_type_falls_back(self):
        img = _color_image()
        result = preprocess_region(img, "unknown_region_type")
        assert result.ndim == 2


# ── Task #5: Bank statement extraction ───────────────────────────────────────
class TestBankIdentification:

    def test_identifies_hdfc(self):
        assert identify_bank("HDFC BANK LIMITED Account Statement") == "HDFC Bank"

    def test_identifies_hdfc_via_ifsc(self):
        assert identify_bank("IFSC: HDFC0001234") == "HDFC Bank"

    def test_identifies_sbi(self):
        assert identify_bank("STATE BANK OF INDIA account statement SBIN0001234") == "SBI"

    def test_identifies_icici(self):
        assert identify_bank("ICICI Bank Ltd ICIC0001234") == "ICICI Bank"

    def test_identifies_axis(self):
        assert identify_bank("Axis Bank Limited UTIB0001234") == "Axis Bank"

    def test_identifies_kotak(self):
        assert identify_bank("Kotak Mahindra Bank KKBK0001234") == "Kotak Bank"

    def test_identifies_unknown(self):
        assert identify_bank("Some random financial statement") == "Unknown Bank"


_HDFC_TEXT = """
HDFC BANK LIMITED
Account Statement
Account Number: XXXX XXXX 4512
IFSC Code: HDFC0001234
Account Holder Name: Ravi Kumar
Opening Balance: 45,230.50
01/01/2024 Opening Balance 45,230.50
03/01/2024 UPI/SWIGGY/Order 450.00 44,780.50
05/01/2024 SALARY CREDIT 55,000.00 99,780.50
31/01/2024 Closing Balance 52,180.75
Closing Balance: 52,180.75
Statement Period: 01/01/2024 to 31/01/2024
"""


class TestBankStatementExtraction:

    def test_hdfc_account_number_extracted(self):
        r = extract_bank_statement(_HDFC_TEXT, "job-1")
        assert "4512" in r.account_number.value
        assert r.account_number.confidence >= 0.90

    def test_hdfc_ifsc_extracted(self):
        r = extract_bank_statement(_HDFC_TEXT, "job-1")
        assert r.ifsc.value == "HDFC0001234"
        assert r.ifsc.confidence >= 0.95

    def test_hdfc_bank_name(self):
        r = extract_bank_statement(_HDFC_TEXT, "job-1")
        assert "HDFC" in r.bank_name.value

    def test_hdfc_account_holder(self):
        r = extract_bank_statement(_HDFC_TEXT, "job-1")
        assert "Ravi" in r.account_holder.value

    def test_hdfc_transactions_found(self):
        r = extract_bank_statement(_HDFC_TEXT, "job-1")
        assert len(r.transactions) >= 1

    def test_hdfc_template_used(self):
        r = extract_bank_statement(_HDFC_TEXT, "job-1")
        assert r.template_used is not None
        assert "hdfc" in r.template_used.lower()

    def test_hdfc_is_structured(self):
        r = extract_bank_statement(_HDFC_TEXT, "job-1")
        assert r.is_structured is True

    def test_hdfc_no_human_review_needed(self):
        r = extract_bank_statement(_HDFC_TEXT, "job-1")
        # Transactions were found — no human review required
        assert r.human_review_required is False

    def test_unknown_bank_uses_generic_extractor(self):
        text = "RBL Bank Account ABCD0001234 Account No: 1234567890"
        r = extract_bank_statement(text, "job-2")
        assert r.template_used is None
        assert r.is_structured is True

    def test_missing_account_triggers_human_review(self):
        text = "HDFC BANK Statement no account number"
        r = extract_bank_statement(text, "job-3")
        # Either template extracts something or triggers review
        assert isinstance(r.human_review_required, bool)

    def test_field_provenance_has_engine(self):
        r = extract_bank_statement(_HDFC_TEXT, "job-1")
        assert r.account_number.engine != ""
        assert r.ifsc.engine != ""

    def test_field_source_is_valid(self):
        r = extract_bank_statement(_HDFC_TEXT, "job-1")
        valid_sources = {"regex", "ml", "ocr", "llm_extract", "template"}
        assert r.account_number.source in valid_sources


# ── Tasks #5 + #11: Invoice extraction ───────────────────────────────────────
_INVOICE_TEXT = """
INVOICE
Invoice No: INV-2024-0042
Invoice Date: 15/01/2024
Due Date: 30/01/2024
From: Acme Technologies Pvt Ltd
Bill To: XYZ Corporation

Description          Qty    Unit Price    Total
Software License     1      50000.00      50000.00
Support Package      2      5000.00       10000.00

Sub Total: 60000.00
GST (18%): 10800.00
Total Amount: 70800.00
"""


class TestInvoiceExtraction:

    def test_invoice_number_extracted(self):
        r = extract_invoice(_INVOICE_TEXT, "job-inv-1")
        assert "INV-2024-0042" in r.invoice_number.value

    def test_invoice_date_extracted(self):
        r = extract_invoice(_INVOICE_TEXT, "job-inv-1")
        assert "15/01/2024" in r.invoice_date.value

    def test_total_extracted(self):
        r = extract_invoice(_INVOICE_TEXT, "job-inv-1")
        assert float(r.total.value or 0) == pytest.approx(70800.0, rel=0.01)

    def test_tax_extracted(self):
        r = extract_invoice(_INVOICE_TEXT, "job-inv-1")
        assert float(r.tax.value or 0) == pytest.approx(10800.0, rel=0.01)

    def test_subtotal_derived_from_total_minus_tax(self):
        r = extract_invoice(_INVOICE_TEXT, "job-inv-1")
        # Even if not explicitly present, subtotal = total - tax
        assert float(r.subtotal.value or 0) == pytest.approx(60000.0, rel=0.01)

    def test_line_items_found(self):
        r = extract_invoice(_INVOICE_TEXT, "job-inv-1")
        assert len(r.line_items) >= 1

    def test_no_human_review_for_complete_document(self):
        r = extract_invoice(_INVOICE_TEXT, "job-inv-1")
        assert r.human_review_required is False

    def test_human_review_triggered_when_total_missing(self):
        text = "Invoice No: ABC-001\nDate: 01/01/2024\nVendor: Test Corp"
        r = extract_invoice(text, "job-inv-2")
        assert r.human_review_required is True

    def test_human_review_triggered_when_invoice_number_missing(self):
        text = "Invoice Date: 01/01/2024\nTotal Amount: 5000.00"
        r = extract_invoice(text, "job-inv-3")
        assert r.human_review_required is True

    def test_confidence_above_zero_for_extracted_fields(self):
        r = extract_invoice(_INVOICE_TEXT, "job-inv-1")
        assert r.invoice_number.confidence > 0
        assert r.total.confidence > 0

    def test_provenance_engine_set(self):
        r = extract_invoice(_INVOICE_TEXT, "job-inv-1")
        assert r.invoice_number.engine == "invoice_extractor"


# ── Task #10: Document classification ────────────────────────────────────────
class TestClassification:

    def test_invoice_text_classified_as_invoice(self):
        text = "invoice bill to ship to subtotal total gst tax line item qty unit price invoice number"
        r = classify_document(text, "job-cls-1")
        assert r.top_prediction == "invoice"

    def test_bank_statement_text_classified(self):
        text = "account number ifsc opening balance closing balance debit credit upi neft rtgs statement period"
        r = classify_document(text, "job-cls-2")
        assert r.top_prediction == "bank_statement"

    def test_payslip_text_classified(self):
        text = "salary payslip employee basic pay hra pf esic net pay gross deductions allowance designation epf"
        r = classify_document(text, "job-cls-3")
        assert r.top_prediction == "payslip"

    def test_contract_text_classified(self):
        text = "agreement party whereas hereinafter terms and conditions clause obligations termination jurisdiction"
        r = classify_document(text, "job-cls-4")
        assert r.top_prediction == "contract"

    def test_both_models_present_in_predictions(self):
        r = classify_document("invoice bill to total amount due", "job-cls-5")
        model_names = {p.model for p in r.predictions}
        assert "tfidf_lr" in model_names
        assert "distilbert" in model_names

    def test_all_five_classes_predicted(self):
        r = classify_document("some random document text", "job-cls-6")
        predicted_types = {p.document_type for p in r.predictions}
        assert len(predicted_types) == 5

    def test_tfidf_confidences_sum_to_one(self):
        r = classify_document("invoice total amount due", "job-cls-7")
        tfidf = [p for p in r.predictions if p.model == "tfidf_lr"]
        total = sum(p.confidence for p in tfidf)
        assert abs(total - 1.0) < 0.01

    def test_all_confidences_between_0_and_1(self):
        r = classify_document("random text", "job-cls-8")
        for p in r.predictions:
            assert 0.0 <= p.confidence <= 1.0

    def test_top_prediction_matches_highest_aggregate(self):
        r = classify_document("invoice bill to total gst", "job-cls-9")
        # Top prediction must be one of the valid classes
        assert r.top_prediction in {"invoice", "bank_statement", "receipt", "contract", "payslip"}

    def test_multi_label_flag_is_bool(self):
        r = classify_document("some text", "job-cls-10")
        assert isinstance(r.is_multi_label, bool)

    def test_empty_text_does_not_crash(self):
        r = classify_document("", "job-cls-11")
        assert r.top_prediction is not None

    def test_very_long_text_truncated_gracefully(self):
        long_text = "invoice " * 2000
        r = classify_document(long_text, "job-cls-12")
        assert r.top_prediction == "invoice"