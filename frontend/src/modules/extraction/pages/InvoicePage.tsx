import { useState, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@lib/api'
import { useJobPoller } from '@hooks/useJobPoller'
import {
  FileDropzone, Button, JobStatusBadge, ProgressBar,
  Card, SectionHeader, ErrorAlert, ConfidencePill, Badge, EmptyState
} from '@components/ui'
import { DownloadExcelButton } from '@components/ui/DownloadExcelButton'
import type { Job, InvoiceResult } from '@/types/domain.types'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'

function FieldRow({
  label, value, confidence, source
}: { label: string; value: string; confidence: number; source: string }) {
  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-white/6 last:border-0">
      <span className="text-xs text-gray-500 w-36 shrink-0">{label}</span>
      <span className="flex-1 text-sm text-gray-200 font-medium">{value || '—'}</span>
      <ConfidencePill value={confidence} />
      <span className="text-[10px] text-gray-700 font-mono w-20 text-right">{source}</span>
    </div>
  )
}

function InvoiceResultView({ result, jobId }: { result: InvoiceResult; jobId: string }) {
  return (
    <div className="space-y-5 animate-in fade-in duration-300">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <h2 className="text-base font-semibold text-white">Extraction Complete</h2>
          {result.human_review_required && (
            <Badge variant="amber"><AlertTriangle className="w-3 h-3" />Review required</Badge>
          )}
        </div>
        <DownloadExcelButton jobId={jobId} jobType="extraction_invoice" />
      </div>

      <Card>
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Invoice Details</p>
        <FieldRow label="Invoice Number" value={result.invoice_number.value} confidence={result.invoice_number.confidence} source={result.invoice_number.engine} />
        <FieldRow label="Invoice Date"   value={result.invoice_date.value}   confidence={result.invoice_date.confidence}   source={result.invoice_date.engine} />
        <FieldRow label="Due Date"       value={result.due_date.value}       confidence={result.due_date.confidence}       source={result.due_date.engine} />
        <FieldRow label="Vendor / From"  value={result.vendor.value}         confidence={result.vendor.confidence}         source={result.vendor.engine} />
        <FieldRow label="Buyer / To"     value={result.buyer.value}          confidence={result.buyer.confidence}          source={result.buyer.engine} />
        <FieldRow label="Subtotal"       value={result.subtotal.value}       confidence={result.subtotal.confidence}       source={result.subtotal.engine} />
        <FieldRow label="Tax / GST"      value={result.tax.value}            confidence={result.tax.confidence}            source={result.tax.engine} />
        <FieldRow label="Grand Total"    value={result.total.value}          confidence={result.total.confidence}          source={result.total.engine} />
      </Card>

      {result.line_items.length > 0 && (
        <Card>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Line Items ({result.line_items.length})
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/8">
                  {['#', 'Description', 'Qty', 'Unit Price', 'Total'].map(h => (
                    <th key={h} className="text-left pb-2 text-gray-500 font-medium pr-4 last:pr-0">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.line_items.map((item, i) => (
                  <tr key={i} className="border-b border-white/4 last:border-0">
                    <td className="py-2 pr-4 text-gray-600">{i + 1}</td>
                    <td className="py-2 pr-4 text-gray-300">{item.description.value}</td>
                    <td className="py-2 pr-4 text-gray-300">{item.quantity.value}</td>
                    <td className="py-2 pr-4 text-gray-300">{item.unit_price.value}</td>
                    <td className="py-2 text-gray-200 font-medium">{item.total.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}

export default function InvoicePage() {
  const qc = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const { data: job } = useJobPoller(jobId)

  const result = job?.status === 'success' && job.result
    ? job.result as unknown as InvoiceResult
    : null

  const handleFile = useCallback(async (files: File[]) => {
    const file = files[0]
    if (!file) return

    // FIX: Reset state + invalidate old query cache before new upload
    // This prevents the UI from briefly showing the previous result
    if (jobId) {
      qc.removeQueries({ queryKey: ['job', jobId] })
    }
    setUploading(true)
    setUploadError(null)
    setJobId(null)   // Clear old job immediately so UI shows upload state

    try {
      const form = new FormData()
      form.append('file', file)
      const submitted = await api.upload<Job>('/api/v1/extraction/invoice', form)
      setJobId(submitted.id)
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }, [jobId, qc])

  const reset = useCallback(() => {
    if (jobId) qc.removeQueries({ queryKey: ['job', jobId] })
    setJobId(null)
    setUploadError(null)
  }, [jobId, qc])

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <SectionHeader
        title="Invoice Extraction"
        subtitle="Extract structured data from invoice PDFs and images — Amazon, Flipkart, Zepto, Blinkit, and any GST invoice"
        action={jobId && <Button variant="ghost" size="sm" onClick={reset}>New invoice</Button>}
      />

      {!jobId && (
        <div className="space-y-4">
          <FileDropzone
            onFiles={files => void handleFile(files)}
            accept="application/pdf,image/png,image/jpeg,image/jpg"
            maxMB={30}
            label="Drop invoice PDF or image"
            hint="PDF (digital text extracted instantly) · PNG/JPG (OCR applied) · up to 30 MB"
            disabled={uploading}
          />
          {uploadError && <ErrorAlert message={uploadError} />}
          {uploading && <p className="text-sm text-gray-500 text-center">Uploading…</p>}
        </div>
      )}

      {job && !['success', 'failed'].includes(job.status) && (
        <Card className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-gray-300">Processing invoice…</p>
            <JobStatusBadge status={job.status} />
          </div>
          <ProgressBar value={job.progress} />
          <p className="text-xs text-gray-600">
            {job.progress < 25
              ? 'Downloading file…'
              : job.progress < 60
              ? 'Extracting text (direct PDF read or OCR)…'
              : job.progress < 80
              ? 'Parsing invoice fields…'
              : 'Generating Excel export…'}
          </p>
        </Card>
      )}

      {job?.status === 'failed' && (
        <div className="space-y-3">
          <ErrorAlert message={job.error ?? 'Extraction failed'} />
          <Button variant="secondary" size="sm" onClick={reset}>Try again</Button>
        </div>
      )}

      {result && <InvoiceResultView result={result} jobId={job!.id} />}
    </div>
  )
}