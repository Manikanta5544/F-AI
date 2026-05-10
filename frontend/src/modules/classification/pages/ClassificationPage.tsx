import { useState } from 'react'
import { api } from '@lib/api'
import { useJobPoller } from '@hooks/useJobPoller'
import { FileDropzone, Button, JobStatusBadge, ProgressBar, Card, SectionHeader, ErrorAlert, Badge } from '@components/ui'
import type { Job, ClassificationResult } from '@/types/domain.types'
import { Brain, Cpu, CheckCircle2 } from 'lucide-react'
import { cn } from '@lib/utils'

const DOC_LABELS: Record<string, { label: string; color: string }> = {
  invoice:        { label: 'Invoice',        color: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
  bank_statement: { label: 'Bank Statement', color: 'bg-blue-500/20 text-blue-300 border-blue-500/30' },
  receipt:        { label: 'Receipt',        color: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
  contract:       { label: 'Contract',       color: 'bg-violet-500/20 text-violet-300 border-violet-500/30' },
  payslip:        { label: 'Payslip',        color: 'bg-pink-500/20 text-pink-300 border-pink-500/30' },
}

export default function ClassificationPage() {
  const [jobId, setJobId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const { data: job } = useJobPoller(jobId)
  const result = job?.status === 'success' && job.result ? job.result as unknown as ClassificationResult : null

  const handleFile = async (files: File[]) => {
    const file = files[0]; if (!file) return
    setUploading(true); setUploadError(null); setJobId(null)
    try {
      const form = new FormData(); form.append('file', file)
      const submitted = await api.upload<Job>('/api/v1/classification/submit', form)
      setJobId(submitted.id)
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed')
    } finally { setUploading(false) }
  }

  const reset = () => { setJobId(null); setUploadError(null) }

  const mlPreds = result?.predictions.filter(p => p.model === 'tfidf_lr') ?? []
  const dlPreds = result?.predictions.filter(p => p.model === 'distilbert') ?? []

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <SectionHeader
        title="Document Classification"
        subtitle="TF-IDF + Logistic Regression (ML) and DistilBERT (DL) predictions shown side-by-side"
        action={jobId && <Button variant="ghost" size="sm" onClick={reset}>New document</Button>}
      />

      {!jobId && (
        <div className="space-y-4">
          <FileDropzone onFiles={files => void handleFile(files)} accept="application/pdf,image/png,image/jpeg" maxMB={20} label="Drop document to classify" disabled={uploading} />
          {uploadError && <ErrorAlert message={uploadError} />}
        </div>
      )}

      {job && !['success', 'failed'].includes(job.status) && (
        <Card className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-gray-300">Classifying document…</p>
            <JobStatusBadge status={job.status} />
          </div>
          <ProgressBar value={job.progress} />
        </Card>
      )}

      {job?.status === 'failed' && (
        <div className="space-y-3">
          <ErrorAlert message={job.error ?? 'Classification failed'} />
          <Button variant="secondary" size="sm" onClick={reset}>Try again</Button>
        </div>
      )}

      {result && (
        <div className="space-y-5 animate-in fade-in duration-300">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            <h2 className="text-base font-semibold text-white">Classification Complete</h2>
          </div>

          {/* Top prediction */}
          <Card>
            <p className="text-xs text-gray-500 mb-2">Top prediction (averaged across both models)</p>
            <div className="flex items-center gap-3">
              <span className={cn('px-3 py-1.5 rounded-lg text-sm font-semibold border', DOC_LABELS[result.top_prediction]?.color ?? 'bg-gray-500/20 text-gray-300 border-gray-500/30')}>
                {DOC_LABELS[result.top_prediction]?.label ?? result.top_prediction}
              </span>
              {result.is_multi_label && <Badge variant="amber">Multi-label detected</Badge>}
            </div>
          </Card>

          {/* Side-by-side model comparison */}
          <div className="grid grid-cols-2 gap-4">
            {[
              { icon: Cpu,   label: 'TF-IDF + Logistic Regression', preds: mlPreds, model: 'tfidf_lr' as const },
              { icon: Brain, label: 'DistilBERT (DL)',               preds: dlPreds, model: 'distilbert' as const },
            ].map(({ icon: Icon, label, preds }) => (
              <Card key={label}>
                <div className="flex items-center gap-2 mb-3">
                  <Icon className="w-4 h-4 text-gray-400" />
                  <p className="text-xs font-semibold text-gray-300">{label}</p>
                </div>
                <div className="space-y-2">
                  {preds.sort((a, b) => b.confidence - a.confidence).map(pred => {
                    const pct = Math.round(pred.confidence * 100)
                    const info = DOC_LABELS[pred.document_type]
                    return (
                      <div key={pred.document_type} className="space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-gray-400">{info?.label ?? pred.document_type}</span>
                          <span className={cn('font-mono font-bold', pct >= 50 ? 'text-violet-300' : 'text-gray-600')}>{pct}%</span>
                        </div>
                        <div className="h-1 bg-white/6 rounded-full overflow-hidden">
                          <div className={cn('h-full rounded-full', pct >= 50 ? 'bg-violet-500' : 'bg-white/15')} style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}