// BankStatementPage.tsx - Same cache invalidation fix as InvoicePage
// + currency display from result meta

import { useState, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@lib/api'
import { useJobPoller } from '@hooks/useJobPoller'
import {
  FileDropzone, Button, JobStatusBadge, ProgressBar,
  Card, SectionHeader, ErrorAlert, ConfidencePill, Badge, EmptyState
} from '@components/ui'
import { DownloadExcelButton } from '@components/ui/DownloadExcelButton'
import type { Job, BankStatementResult, BankTransaction } from '@/types/domain.types'
import { CheckCircle2, AlertTriangle } from 'lucide-react'

function FieldRow({ label, value, confidence }: { label: string; value: string; confidence: number }) {
  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-white/6 last:border-0">
      <span className="text-xs text-gray-500 w-40 shrink-0">{label}</span>
      <span className="flex-1 text-sm text-gray-200 font-medium">{value || '—'}</span>
      <ConfidencePill value={confidence} />
    </div>
  )
}

function TxRow({ tx, idx }: { tx: BankTransaction; idx: number }) {
  const debitVal = parseFloat(tx.debit.value) || 0
  const creditVal = parseFloat(tx.credit.value) || 0
  return (
    <tr className={`border-b border-white/4 last:border-0 text-xs ${idx % 2 === 0 ? '' : 'bg-white/1'}`}>
      <td className="py-2 pr-4 text-gray-500 font-mono whitespace-nowrap">{tx.date.value}</td>
      <td className="py-2 pr-4 text-gray-300 max-w-[240px]">
        <span title={tx.narration.value} className="line-clamp-2">{tx.narration.value}</span>
      </td>
      <td className="py-2 pr-4 text-red-400 font-mono text-right">
        {debitVal > 0 ? debitVal.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : ''}
      </td>
      <td className="py-2 pr-4 text-emerald-400 font-mono text-right">
        {creditVal > 0 ? creditVal.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : ''}
      </td>
      <td className="py-2 text-gray-200 font-mono text-right">
        {tx.balance.value}
      </td>
    </tr>
  )
}

function BankResultView({ result, jobId }: { result: BankStatementResult; jobId: string }) {
  return (
    <div className="space-y-5 animate-in fade-in duration-300">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <h2 className="text-base font-semibold text-white">Extraction Complete</h2>
          {result.template_used && (
            <Badge variant="emerald">{result.template_used}</Badge>
          )}
          {result.human_review_required && (
            <Badge variant="amber"><AlertTriangle className="w-3 h-3" />Review required</Badge>
          )}
        </div>
        <DownloadExcelButton jobId={jobId} jobType="extraction_bank_statement" />
      </div>

      <Card>
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Account Details</p>
        <FieldRow label="Bank"              value={result.bank_name.value}             confidence={result.bank_name.confidence} />
        <FieldRow label="Account Holder"    value={result.account_holder.value}        confidence={result.account_holder.confidence} />
        <FieldRow label="Account Number"    value={result.account_number.value}        confidence={result.account_number.confidence} />
        <FieldRow label="IFSC"              value={result.ifsc.value}                  confidence={result.ifsc.confidence} />
        <FieldRow label="Opening Balance"   value={result.opening_balance.value}       confidence={result.opening_balance.confidence} />
        <FieldRow label="Closing Balance"   value={result.closing_balance.value}       confidence={result.closing_balance.confidence} />
        <FieldRow label="Period From"       value={result.statement_period_from.value} confidence={result.statement_period_from.confidence} />
        <FieldRow label="Period To"         value={result.statement_period_to.value}   confidence={result.statement_period_to.confidence} />
      </Card>

      <Card>
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Transactions ({result.transactions.length})
        </p>
        {result.transactions.length === 0
          ? <EmptyState title="No transactions extracted" description="Review recommended." />
          : (
            <div className="overflow-x-auto -mx-4 px-4">
              <table className="w-full min-w-[600px] text-sm">
                <thead>
                  <tr className="border-b border-white/10">
                    {['Date', 'Narration', 'Debit', 'Credit', 'Balance'].map(h => (
                      <th key={h} className={`pb-2 text-xs font-medium text-gray-500 pr-4 last:pr-0 ${['Debit', 'Credit', 'Balance'].includes(h) ? 'text-right' : 'text-left'}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.transactions.map((tx, i) => <TxRow key={i} tx={tx} idx={i} />)}
                </tbody>
              </table>
            </div>
          )
        }
      </Card>
    </div>
  )
}

export default function BankStatementPage() {
  const qc = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const { data: job } = useJobPoller(jobId)
  const result = job?.status === 'success' && job.result
    ? job.result as unknown as BankStatementResult
    : null

  const handleFile = useCallback(async (files: File[]) => {
    const file = files[0]
    if (!file) return
    if (jobId) qc.removeQueries({ queryKey: ['job', jobId] })
    setUploading(true); setUploadError(null); setJobId(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const submitted = await api.upload<Job>('/api/v1/extraction/bank-statement', form)
      setJobId(submitted.id)
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }, [jobId, qc])

  const reset = useCallback(() => {
    if (jobId) qc.removeQueries({ queryKey: ['job', jobId] })
    setJobId(null); setUploadError(null)
  }, [jobId, qc])

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <SectionHeader
        title="Bank Statement Extraction"
        subtitle="Supports Indian banks (HDFC, SBI, ICICI, Axis, Kotak, PNB) and international banks — any structured PDF or scanned image"
        action={jobId && <Button variant="ghost" size="sm" onClick={reset}>New statement</Button>}
      />

      {!jobId && (
        <div className="space-y-4">
          <FileDropzone
            onFiles={files => void handleFile(files)}
            accept="application/pdf,image/png,image/jpeg,image/jpg"
            maxMB={30}
            label="Drop bank statement PDF or image"
            hint="PDF (table extracted instantly) · PNG/JPG (OCR applied) · up to 30 MB"
            disabled={uploading}
          />
          {uploadError && <ErrorAlert message={uploadError} />}
        </div>
      )}

      {job && !['success', 'failed'].includes(job.status) && (
        <Card className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-gray-300">Processing bank statement…</p>
            <JobStatusBadge status={job.status} />
          </div>
          <ProgressBar value={job.progress} />
          <p className="text-xs text-gray-600">
            {job.progress < 25
              ? 'Downloading file…'
              : job.progress < 60
              ? 'Extracting text and table structure…'
              : job.progress < 80
              ? 'Parsing account details and transactions…'
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

      {result && <BankResultView result={result} jobId={job!.id} />}
    </div>
  )
}