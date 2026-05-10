// ── Jobs ──────────────────────────────────────────────────────────────────────
export type JobStatus = 'pending' | 'processing' | 'success' | 'failed' | 'retrying'

export interface Job {
  id: string
  status: JobStatus
  progress: number
  job_type: string
  created_at: string
  updated_at: string
  result?: Record<string, unknown> | null
  error?: string | null
  meta: Record<string, unknown>
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export interface AuthUser {
  id: string
  email: string
  name: string
  role: string
}

export interface TokenResponse {
  access_token: string
  expires_in: number
}

// ── OCR ───────────────────────────────────────────────────────────────────────
export type OCREngine = 'paddle' | 'easyocr' | 'tesseract' | 'docling' | 'tr'
export type OCRMode = 'fast' | 'full'

export interface BoundingBox { x: number; y: number; width: number; height: number }

export interface OCRToken {
  text: string
  confidence: number
  bbox: BoundingBox
  engine: OCREngine
}

export interface OCRRegion {
  id: string
  type: 'text' | 'table' | 'figure' | 'header' | 'stamp' | 'signature'
  bbox: BoundingBox
  confidence: number
  tokens: OCRToken[]
  text: string
}

export interface OCRResult {
  job_id: string
  filename: string
  page_count: number
  mode: OCRMode
  regions: OCRRegion[]
  engine_used: OCREngine
  fallback_triggered: boolean
  metrics: {
    processing_ms: number
    characters_extracted: number
    avg_confidence: number
  }
}

// ── Extraction ────────────────────────────────────────────────────────────────
export type FieldSource = 'regex' | 'ml' | 'ocr'

export interface ExtractedField<T = string> {
  value: T
  confidence: number
  source: FieldSource
  engine: string
  bbox: BoundingBox | null
  raw_ocr: string
}

export interface BankTransaction {
  date: ExtractedField
  narration: ExtractedField
  debit: ExtractedField
  credit: ExtractedField
  balance: ExtractedField
}

export interface BankStatementResult {
  job_id: string
  account_number: ExtractedField
  ifsc: ExtractedField
  bank_name: ExtractedField
  account_holder: ExtractedField
  opening_balance: ExtractedField
  closing_balance: ExtractedField
  statement_period_from: ExtractedField
  statement_period_to: ExtractedField
  transactions: BankTransaction[]
  is_structured: boolean
  template_used: string | null
  human_review_required: boolean
  excel_export_key?: string | null
}

export interface InvoiceLineItem {
  description: ExtractedField
  quantity: ExtractedField
  unit_price: ExtractedField
  total: ExtractedField
}

export interface InvoiceResult {
  job_id: string
  invoice_number: ExtractedField
  invoice_date: ExtractedField
  due_date: ExtractedField
  vendor: ExtractedField
  buyer: ExtractedField
  subtotal: ExtractedField
  tax: ExtractedField
  total: ExtractedField
  line_items: InvoiceLineItem[]
  human_review_required: boolean
  excel_export_key?: string | null
}

// ── Scraper ───────────────────────────────────────────────────────────────────
export type Platform = 'amazon' | 'flipkart' | 'swiggy' | 'zomato' | 'manual'

export interface ScrapedProduct {
  id: string
  platform: string
  title: string
  price: number | null
  original_price: number | null
  discount: number | null
  currency: string
  rating: number | null
  review_count: number | null
  availability: string
  brand: string | null
  category: string | null
  url: string
  images: string[]
  created_at: string
}

export interface ScrapeResults {
  items: ScrapedProduct[]
  total: number
  job_id: string
}

// ── Classification ────────────────────────────────────────────────────────────
export interface ClassificationPrediction {
  document_type: string
  confidence: number
  model: 'tfidf_lr' | 'distilbert'
}

export interface ClassificationResult {
  job_id: string
  predictions: ClassificationPrediction[]
  top_prediction: string
  is_multi_label: boolean
}

// ── API ───────────────────────────────────────────────────────────────────────
export interface ApiError {
  code: string
  message: string
  details?: unknown
  requestId: string
}