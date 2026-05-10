import React from 'react'
import { Loader2, AlertCircle, CheckCircle2, Clock, XCircle, RefreshCw } from 'lucide-react'
import { cn } from '@lib/utils'
import type { JobStatus } from '@/types/domain.types'

// ── Button ────────────────────────────────────────────────────────────────────
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
}

export function Button({
  variant = 'primary', size = 'md', loading, children, className, disabled, ...props
}: ButtonProps) {
  const base = 'inline-flex items-center justify-center gap-2 font-medium rounded-lg transition-all duration-150 disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-violet-500'
  const variants = {
    primary:   'bg-violet-600 text-white hover:bg-violet-500 focus-visible:ring-offset-gray-950',
    secondary: 'bg-white/10 text-gray-200 hover:bg-white/15 border border-white/10',
    ghost:     'text-gray-400 hover:text-gray-200 hover:bg-white/8',
    danger:    'bg-red-600/80 text-white hover:bg-red-500 border border-red-500/50',
    success:   'bg-emerald-600/80 text-white hover:bg-emerald-500 border border-emerald-500/50',
  }
  const sizes = { sm: 'text-xs px-3 py-1.5 h-7', md: 'text-sm px-4 py-2 h-9', lg: 'text-sm px-5 py-2.5 h-11' }
  return (
    <button className={cn(base, variants[variant], sizes[size], className)} disabled={disabled || loading} {...props}>
      {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
      {children}
    </button>
  )
}

// ── Badge ─────────────────────────────────────────────────────────────────────
interface BadgeProps { children: React.ReactNode; variant?: 'violet' | 'emerald' | 'amber' | 'red' | 'gray' | 'blue'; className?: string }
export function Badge({ children, variant = 'gray', className }: BadgeProps) {
  const variants = {
    violet:  'bg-violet-500/20 text-violet-300 border-violet-500/30',
    emerald: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    amber:   'bg-amber-500/20 text-amber-300 border-amber-500/30',
    red:     'bg-red-500/20 text-red-300 border-red-500/30',
    gray:    'bg-white/8 text-gray-400 border-white/10',
    blue:    'bg-blue-500/20 text-blue-300 border-blue-500/30',
  }
  return <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border font-medium', variants[variant], className)}>{children}</span>
}

// ── ConfidencePill ────────────────────────────────────────────────────────────
export function ConfidencePill({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 90 ? 'text-emerald-400' : pct >= 75 ? 'text-amber-400' : 'text-red-400'
  return <span className={cn('text-xs font-mono font-semibold', color)}>{pct}%</span>
}

// ── JobStatusBadge ────────────────────────────────────────────────────────────
const STATUS_MAP: Record<JobStatus, { label: string; icon: React.FC<{ className?: string }>; color: BadgeProps['variant'] }> = {
  pending:    { label: 'Pending',    icon: Clock,         color: 'gray' },
  processing: { label: 'Processing', icon: RefreshCw,     color: 'amber' },
  retrying:   { label: 'Retrying',   icon: RefreshCw,     color: 'amber' },
  success:    { label: 'Complete',   icon: CheckCircle2,  color: 'emerald' },
  failed:     { label: 'Failed',     icon: XCircle,       color: 'red' },
}
export function JobStatusBadge({ status }: { status: JobStatus }) {
  const cfg = STATUS_MAP[status]
  const Icon = cfg.icon
  return (
    <Badge variant={cfg.color}>
      <Icon className={cn('w-3 h-3', status === 'processing' || status === 'retrying' ? 'animate-spin' : '')} />
      {cfg.label}
    </Badge>
  )
}

// ── Progress bar ──────────────────────────────────────────────────────────────
export function ProgressBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn('h-1.5 bg-white/8 rounded-full overflow-hidden', className)}>
      <div className="h-full bg-violet-500 rounded-full transition-all duration-300" style={{ width: `${value}%` }} />
    </div>
  )
}

// ── Spinner ───────────────────────────────────────────────────────────────────
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('animate-spin text-violet-400', className ?? 'w-6 h-6')} />
}

// ── Card ──────────────────────────────────────────────────────────────────────
export function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('rounded-xl border border-white/8 bg-white/3 p-4', className)}>{children}</div>
}

// ── SectionHeader ─────────────────────────────────────────────────────────────
export function SectionHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h1 className="text-lg font-semibold text-white">{title}</h1>
        {subtitle && <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

// ── ErrorAlert ────────────────────────────────────────────────────────────────
export function ErrorAlert({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
      <AlertCircle className="w-4 h-4 shrink-0" />
      {message}
    </div>
  )
}

// ── EmptyState ────────────────────────────────────────────────────────────────
export function EmptyState({ icon, title, description }: { icon?: React.ReactNode; title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      {icon && <div className="mb-4 text-gray-600">{icon}</div>}
      <p className="text-sm font-medium text-gray-400">{title}</p>
      {description && <p className="text-xs text-gray-600 mt-1 max-w-xs">{description}</p>}
    </div>
  )
}

// ── FileDropzone ──────────────────────────────────────────────────────────────
interface FileDropzoneProps {
  onFiles: (files: File[]) => void
  accept?: string
  maxMB?: number
  label?: string
  hint?: string
  disabled?: boolean
}
export function FileDropzone({ onFiles, accept = 'application/pdf,image/png,image/jpeg', maxMB = 50, label = 'Drop file here or click to browse', hint, disabled }: FileDropzoneProps) {
  const ref = React.useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const validate = (files: File[]): File[] => {
    const valid = files.filter(f => {
      const types = accept.split(',').map(t => t.trim())
      if (!types.includes(f.type)) { setError(`Unsupported type: ${f.type}`); return false }
      if (f.size > maxMB * 1024 * 1024) { setError(`File exceeds ${maxMB}MB`); return false }
      return true
    })
    if (valid.length) setError(null)
    return valid
  }

  return (
    <div className="space-y-2">
      <div
        onClick={() => !disabled && ref.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); const v = validate(Array.from(e.dataTransfer.files)); if (v.length) onFiles(v) }}
        className={cn(
          'flex flex-col items-center justify-center gap-2 p-8 rounded-xl border-2 border-dashed transition-all cursor-pointer select-none',
          dragOver ? 'border-violet-500 bg-violet-500/8' : 'border-white/12 bg-white/2 hover:border-white/20',
          disabled && 'opacity-50 cursor-not-allowed',
        )}
      >
        <div className="w-10 h-10 rounded-xl bg-white/8 flex items-center justify-center">
          <svg className="w-5 h-5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" /></svg>
        </div>
        <p className="text-sm text-gray-300">{label}</p>
        <p className="text-xs text-gray-600">{hint ?? `${accept.replace(/application\//g, '').replace(/image\//g, '').toUpperCase()} up to ${maxMB}MB`}</p>
        <input ref={ref} type="file" accept={accept} className="hidden" onChange={(e) => { const v = validate(Array.from(e.target.files ?? [])); if (v.length) onFiles(v); e.target.value = '' }} disabled={disabled} />
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  )
}