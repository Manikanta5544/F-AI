import { useState } from 'react'
import { api } from '@lib/api'
import { useJobPoller } from '@hooks/useJobPoller'
import { FileDropzone, Button, JobStatusBadge, ProgressBar, Card, SectionHeader, ErrorAlert, ConfidencePill, Badge, EmptyState } from '@components/ui'
import { DownloadExcelButton } from '@components/ui/DownloadExcelButton'
import type { Job, OCRResult, OCRRegion } from '@/types/domain.types'
import { CheckCircle2, ChevronDown, ChevronUp, Zap, Layers } from 'lucide-react'
import { cn } from '@lib/utils'

const REGION_COLORS: Record<string, string> = {
  text:      'bg-blue-500/15 text-blue-300 border-blue-500/30',
  table:     'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  figure:    'bg-violet-500/15 text-violet-300 border-violet-500/30',
  header:    'bg-amber-500/15 text-amber-300 border-amber-500/30',
  stamp:     'bg-pink-500/15 text-pink-300 border-pink-500/30',
  signature: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
}

function RegionCard({ region }: { region: OCRRegion }) {
  const [open, setOpen] = useState(false)
  const colorClass = REGION_COLORS[region.type] ?? REGION_COLORS.text
  return (
    <div className="rounded-lg border border-white/8 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-3 p-3 hover:bg-white/3 transition-colors text-left"
      >
        <span className={cn('text-xs px-2 py-0.5 rounded-full border font-medium shrink-0', colorClass)}>{region.type}</span>
        <span className="flex-1 text-xs text-gray-400 truncate">{region.text.slice(0, 100)}</span>
        <ConfidencePill value={region.confidence} />
        {open ? <ChevronUp className="w-3.5 h-3.5 text-gray-600 shrink-0" /> : <ChevronDown className="w-3.5 h-3.5 text-gray-600 shrink-0" />}
      </button>
      {open && (
        <div className="px-3 pb-3 border-t border-white/6">
          <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap leading-relaxed bg-black/20 rounded-lg p-3 mt-2 max-h-40 overflow-auto">{region.text}</pre>
          <div className="flex gap-4 mt-2 text-[10px] text-gray-700">
            <span>Tokens: {region.tokens.length}</span>
            <span>Engine: {region.tokens[0]?.engine ?? '—'}</span>
            <span>BBox: {Math.round(region.bbox.x)},{Math.round(region.bbox.y)} {Math.round(region.bbox.width)}×{Math.round(region.bbox.height)}</span>
          </div>
        </div>
      )}
    </div>
  )
}

function OCRResultView({ result, jobId }: { result: OCRResult; jobId: string }) {
  return (
    <div className="space-y-5 animate-in fade-in duration-300">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <h2 className="text-base font-semibold text-white">OCR Complete</h2>
          {result.fallback_triggered && <Badge variant="amber">Fallback engine used</Badge>}
        </div>
        <DownloadExcelButton jobId={jobId} jobType="ocr" />
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Pages',      value: result.page_count.toString() },
          { label: 'Regions',    value: result.regions.length.toString() },
          { label: 'Chars',      value: result.metrics.characters_extracted.toLocaleString() },
          { label: 'Avg Conf',   value: `${Math.round(result.metrics.avg_confidence * 100)}%` },
        ].map(({ label, value }) => (
          <Card key={label}>
            <p className="text-xs text-gray-500">{label}</p>
            <p className="text-lg font-bold text-white mt-0.5 font-mono">{value}</p>
          </Card>
        ))}
      </div>

      <div className="flex items-center gap-3 text-sm text-gray-500">
        <span>Engine: <span className="text-gray-300 font-mono">{result.engine_used}</span></span>
        <span>·</span>
        <span>Mode: <span className="text-gray-300">{result.mode}</span></span>
        <span>·</span>
        <span>Time: <span className="text-gray-300">{(result.metrics.processing_ms / 1000).toFixed(1)}s</span></span>
      </div>

      {/* Regions */}
      <Card>
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Detected Regions ({result.regions.length})
        </p>
        {result.regions.length === 0
          ? <EmptyState title="No regions detected" />
          : <div className="space-y-1.5">{result.regions.map(r => <RegionCard key={r.id} region={r} />)}</div>
        }
      </Card>
    </div>
  )
}

export default function OCRPage() {
  const [jobId, setJobId] = useState<string | null>(null)
  const [mode, setMode] = useState<'full' | 'fast'>('full')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const { data: job } = useJobPoller(jobId)
  const result = job?.status === 'success' && job.result ? job.result as unknown as OCRResult : null

  const handleFile = async (files: File[]) => {
    const file = files[0]
    if (!file) return
    setUploading(true); setUploadError(null); setJobId(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('mode', mode)
      const submitted = await api.upload<Job>('/api/v1/ocr/submit', form)
      setJobId(submitted.id)
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const reset = () => { setJobId(null); setUploadError(null) }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <SectionHeader
        title="OCR & YOLO Pipeline"
        subtitle="Multi-engine OCR (PaddleOCR, EasyOCR, Tesseract, TrOCR) with YOLOv8 layout detection"
        action={jobId && <Button variant="ghost" size="sm" onClick={reset}>New document</Button>}
      />

      {!jobId && (
        <div className="space-y-5">
          {/* Mode selector */}
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Pipeline mode</p>
            <div className="grid grid-cols-2 gap-2">
              {([
                { id: 'full' as const, label: 'Full Pipeline', desc: 'YOLO layout + OCR ensemble. Best accuracy.', icon: Layers },
                { id: 'fast' as const, label: 'Fast Mode',     desc: 'PaddleOCR only. 4× faster, great for clean scans.', icon: Zap },
              ]).map(({ id, label, desc, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setMode(id)}
                  className={cn(
                    'flex items-start gap-3 p-3.5 rounded-xl border text-left transition-all',
                    mode === id ? 'border-violet-500/60 bg-violet-500/10' : 'border-white/8 bg-white/2 hover:border-white/15',
                  )}
                >
                  <div className={cn('w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5', mode === id ? 'bg-violet-500/30 text-violet-300' : 'bg-white/8 text-gray-500')}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <div>
                    <p className={cn('text-sm font-medium', mode === id ? 'text-violet-300' : 'text-gray-300')}>{label}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <FileDropzone
            onFiles={files => void handleFile(files)}
            accept="application/pdf,image/png,image/jpeg,image/jpg,image/tiff"
            maxMB={50}
            label="Drop document for OCR processing"
            hint="PDF, PNG, JPEG, TIFF — up to 50 MB"
            disabled={uploading}
          />
          {uploadError && <ErrorAlert message={uploadError} />}
        </div>
      )}

      {job && !['success', 'failed'].includes(job.status) && (
        <Card className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-gray-300">
              {mode === 'full' ? 'Running YOLO → preprocessing → OCR ensemble…' : 'Running PaddleOCR fast pipeline…'}
            </p>
            <JobStatusBadge status={job.status} />
          </div>
          <ProgressBar value={job.progress} />
          <p className="text-xs text-gray-600">{job.progress}%</p>
        </Card>
      )}

      {job?.status === 'failed' && (
        <div className="space-y-3">
          <ErrorAlert message={job.error ?? 'OCR failed'} />
          <Button variant="secondary" size="sm" onClick={reset}>Try again</Button>
        </div>
      )}

      {result && <OCRResultView result={result} jobId={job!.id} />}
    </div>
  )
}