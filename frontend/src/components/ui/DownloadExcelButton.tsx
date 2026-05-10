/**
 * DownloadExcelButton
 * A reusable button component for downloading Celery job results as Excel files.
 *
 * Props:
 *   jobId        — Celery job ID whose result should be exported
 *   jobType      — Used to build a meaningful default filename hint
 *   disabled     — Disable while job is still processing
 *   size         — Button size token
 *
 * Example:
 *   <DownloadExcelButton jobId={job.id} jobType="bank_statement" />
 */
import { FileSpreadsheet, Loader2, AlertCircle } from 'lucide-react'
import { useDownloadExcel } from '@hooks/useDownloadExcel'
import { cn } from '@lib/utils'

interface DownloadExcelButtonProps {
  jobId:      string
  jobType?:   string
  disabled?:  boolean
  size?:      'sm' | 'md' | 'lg'
  className?: string
}

const SIZE_CLASSES = {
  sm: 'text-xs px-3 py-1.5 h-7 gap-1.5',
  md: 'text-sm px-4 py-2 h-9 gap-2',
  lg: 'text-sm px-5 py-2.5 h-11 gap-2',
}

export function DownloadExcelButton({
  jobId,
  jobType = 'result',
  disabled = false,
  size    = 'md',
  className,
}: DownloadExcelButtonProps) {
  const { download, isDownloading, error } = useDownloadExcel()

  const handleClick = () => {
    void download(jobId, jobType)
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled || isDownloading}
        className={cn(
          'inline-flex items-center justify-center rounded-lg font-medium',
          'transition-all duration-150',
          'bg-emerald-600/80 text-white hover:bg-emerald-500 border border-emerald-500/50',
          'disabled:opacity-50 disabled:pointer-events-none',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500',
          SIZE_CLASSES[size],
          className,
        )}
      >
        {isDownloading ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <FileSpreadsheet className="w-3.5 h-3.5" />
        )}
        {isDownloading ? 'Preparing…' : 'Download Excel'}
      </button>

      {error !== null && (
        <span className="flex items-center gap-1 text-xs text-red-400">
          <AlertCircle className="w-3 h-3" />
          {error}
        </span>
      )}
    </div>
  )
}