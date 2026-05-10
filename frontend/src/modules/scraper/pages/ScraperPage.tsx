/**
 * src/modules/scraper/pages/ScraperPage.tsx
 * ImexBay B2B Lead Intelligence — multi-city, 17 segments
 *
 * KEY FIX: Download button uses /api/v1/scraper/download/:jobId
 * (DB-backed endpoint) instead of /api/v1/download/:jobId
 * (generate_excel path which has no lead data in job.result).
 */
import { useState, useCallback } from 'react'
import { api } from '@lib/api'
import { axiosInstance } from '@lib/api'
import { useJobPoller } from '@hooks/useJobPoller'
import { useQuery } from '@tanstack/react-query'
import { Button, JobStatusBadge, ProgressBar, Card, SectionHeader, ErrorAlert, EmptyState } from '@components/ui'
import type { Job } from '@/types/domain.types'
import { Plus, X, CheckCircle2, Phone, Mail, Globe, MapPin, Search, Filter, ChevronDown, ChevronUp, Building2, Download } from 'lucide-react'
import { cn } from '@lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────
interface Cat  { id: string; label: string; icon: string }
interface Src  { id: string; label: string; coverage: string; best_for: string }
interface Lead {
  id: string; company_name: string; category: string; city: string
  phone: string; email: string; website: string; address: string
  description: string; services: string[]; employee_count: string; founded_year: string
  source_platform: string; source_url: string; confidence_score: number
}
interface Results {
  items: Lead[]; total: number; job_id: string
  summary: { total_leads?: number; with_phone?: number; with_email?: number; with_website?: number
             by_category?: Record<string,number>; by_city?: Record<string,number> }
}

const CAT_CLR: Record<string,string> = {
  importer:'border-red-500/40 text-red-300 bg-red-500/10',
  exporter:'border-rose-500/40 text-rose-300 bg-rose-500/10',
  manufacturer:'border-emerald-500/40 text-emerald-300 bg-emerald-500/10',
  trader:'border-amber-500/40 text-amber-300 bg-amber-500/10',
  freight_forwarder:'border-teal-500/40 text-teal-300 bg-teal-500/10',
  customs_broker:'border-gray-500/40 text-gray-300 bg-gray-500/10',
  insurer:'border-blue-500/40 text-blue-300 bg-blue-500/10',
  bank_trade_finance:'border-cyan-500/40 text-cyan-300 bg-cyan-500/10',
  ca_firm:'border-green-500/40 text-green-300 bg-green-500/10',
  virtual_cfo:'border-violet-500/40 text-violet-300 bg-violet-500/10',
  accounting:'border-yellow-500/40 text-yellow-300 bg-yellow-500/10',
  logistics:'border-sky-500/40 text-sky-300 bg-sky-500/10',
  fintech:'border-pink-500/40 text-pink-300 bg-pink-500/10',
  startup_sme:'border-purple-500/40 text-purple-300 bg-purple-500/10',
  ecommerce:'border-orange-500/40 text-orange-300 bg-orange-500/10',
  marketing_sales:'border-fuchsia-500/40 text-fuchsia-300 bg-fuchsia-500/10',
  operations:'border-lime-500/40 text-lime-300 bg-lime-500/10',
}
const SRC_CLR: Record<string,string> = {
  justdial:'bg-orange-500/15 text-orange-300',
  indiamart:'bg-blue-500/15 text-blue-300',
  tradeindia:'bg-violet-500/15 text-violet-300',
  sulekha:'bg-green-500/15 text-green-300',
  yellowpages:'bg-yellow-500/15 text-yellow-300',
}

const CITIES = [
  'Hyderabad','Mumbai','Delhi','Bangalore','Chennai',
  'Pune','Ahmedabad','Kolkata','Surat','Coimbatore',
  'Ludhiana','Kochi','Jaipur','Indore','Noida',
]

const PROG = (p: number) =>
  p < 20 ? 'Initialising scrapers…'
  : p < 40 ? 'Searching JustDial & YellowPages…'
  : p < 60 ? 'Mining IndiaMart & TradeIndia…'
  : p < 75 ? 'Scanning Sulekha…'
  : p < 90 ? 'Deduplicating & scoring…'
  : 'Generating Excel export…'

const ccol = (s: number) => s >= 0.7 ? 'text-emerald-400' : s >= 0.4 ? 'text-amber-400' : 'text-red-400'

// ── Download button (uses DB-backed endpoint) ─────────────────────────────────
function LeadDownloadButton({ jobId }: { jobId: string }) {
  const [busy, setBusy] = useState(false)

  const download = async () => {
    setBusy(true)
    try {
      // Uses /scraper/download/:id which queries DB directly — not generate_excel
      const response = await axiosInstance.get(`/api/v1/scraper/download/${jobId}`, {
        responseType: 'blob',
      })
      const blob = new Blob([response.data as BlobPart], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `b2b_leads_${jobId.slice(0, 8)}.xlsx`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Download failed', e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Button onClick={() => void download()} loading={busy} variant="secondary" size="sm">
      <Download className="w-4 h-4 mr-1.5" /> Download Excel
    </Button>
  )
}

// ── Lead card ─────────────────────────────────────────────────────────────────
function LeadCard({ lead }: { lead: Lead }) {
  const [open, setOpen] = useState(false)
  const catClr = CAT_CLR[lead.category] ?? 'border-white/10 text-gray-400 bg-white/5'
  const srcClr = SRC_CLR[lead.source_platform] ?? 'bg-white/8 text-gray-400'
  const catLbl = lead.category.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())
  const conf   = Math.round(lead.confidence_score * 100)

  return (
    <div className="rounded-xl border border-white/8 bg-white/2 hover:bg-white/3 transition-all">
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <h3 className="text-sm font-semibold text-white truncate">{lead.company_name}</h3>
              <span className={cn('text-[10px] px-2 py-0.5 rounded-full border font-medium shrink-0', catClr)}>{catLbl}</span>
            </div>
            {lead.city && (
              <div className="flex items-center gap-1 text-xs text-gray-500 mb-2">
                <MapPin className="w-3 h-3 shrink-0"/>{lead.city}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              {lead.phone && (
                <a href={`tel:${lead.phone}`} className="flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300 font-mono font-semibold">
                  <Phone className="w-3 h-3"/>{lead.phone}
                </a>
              )}
              {lead.email && (
                <a href={`mailto:${lead.email}`} className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 truncate max-w-[220px]">
                  <Mail className="w-3 h-3"/><span className="truncate">{lead.email}</span>
                </a>
              )}
              {lead.website && (
                <a href={lead.website} target="_blank" rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 truncate max-w-[200px]">
                  <Globe className="w-3 h-3"/>
                  <span className="truncate">{lead.website.replace(/^https?:\/\//,'')}</span>
                </a>
              )}
            </div>
          </div>
          <div className="flex flex-col items-end gap-2 shrink-0">
            <span className={cn('text-xs font-mono font-bold', ccol(lead.confidence_score))}>{conf}%</span>
            <span className={cn('text-[10px] px-2 py-0.5 rounded-full font-medium', srcClr)}>
              {lead.source_platform}
            </span>
          </div>
        </div>
        {(lead.description || lead.services?.length || lead.address) && (
          <button onClick={()=>setOpen(v=>!v)} className="mt-2 flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400 transition-colors">
            {open ? <ChevronUp className="w-3 h-3"/> : <ChevronDown className="w-3 h-3"/>}
            {open ? 'Less' : 'Details'}
          </button>
        )}
      </div>
      {open && (
        <div className="px-4 pb-4 border-t border-white/6 pt-3 space-y-2">
          {lead.description && <p className="text-xs text-gray-400 leading-relaxed">{lead.description}</p>}
          {lead.address && <p className="text-xs text-gray-600"><span className="text-gray-500">Address: </span>{lead.address}</p>}
          {lead.services?.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {lead.services.slice(0,6).map((s,i)=>(
                <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 border border-white/8 text-gray-400">{s}</span>
              ))}
            </div>
          )}
          {(lead.employee_count || lead.founded_year) && (
            <div className="flex gap-4 text-xs text-gray-600">
              {lead.employee_count && <span><span className="text-gray-500">Employees: </span>{lead.employee_count}</span>}
              {lead.founded_year   && <span><span className="text-gray-500">Founded: </span>{lead.founded_year}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function ScraperPage() {
  const [queries,   setQueries]   = useState<string[]>([''])
  const [selCats,   setSelCats]   = useState<string[]>([])
  const [selSrcs,   setSelSrcs]   = useState<string[]>(['justdial','indiamart','tradeindia'])
  const [locs,      setLocs]      = useState<string[]>(['Hyderabad','Mumbai','Bangalore'])
  const [maxLeads,  setMaxLeads]  = useState(200)
  const [jobId,     setJobId]     = useState<string|null>(null)
  const [busy,      setBusy]      = useState(false)
  const [err,       setErr]       = useState<string|null>(null)
  const [fCat,      setFCat]      = useState('')
  const [fCity,     setFCity]     = useState('')
  const [onlyPhone, setOnlyPhone] = useState(false)
  const [onlyEmail, setOnlyEmail] = useState(false)

  const { data: job } = useJobPoller(jobId)

  const { data: cats = [] } = useQuery<Cat[]>({
    queryKey: ['lead-cats'],
    queryFn: () => api.get('/api/v1/scraper/categories'),
    staleTime: Infinity,
  })
  const { data: srcs = [] } = useQuery<Src[]>({
    queryKey: ['lead-srcs'],
    queryFn: () => api.get('/api/v1/scraper/sources'),
    staleTime: Infinity,
  })
  const { data: results } = useQuery<Results>({
    queryKey: ['leads', jobId, fCat, fCity, onlyPhone, onlyEmail],
    queryFn: () => {
      const p = new URLSearchParams({ per_page: '500' })
      if (fCat)      p.set('category', fCat)
      if (onlyPhone) p.set('has_phone', 'true')
      if (onlyEmail) p.set('has_email', 'true')
      return api.get(`/api/v1/scraper/results/${jobId}?${p}`)
    },
    enabled: job?.status === 'success',
  })

  const toggle = (arr: string[], set: (v:string[])=>void, id: string) =>
    set(arr.includes(id) ? arr.filter(x=>x!==id) : [...arr, id])

  const submit = async () => {
    const q = queries.filter(x=>x.trim())
    if (!q.length) { setErr('Enter at least one query'); return }
    if (!selSrcs.length) { setErr('Select at least one source'); return }
    setBusy(true); setErr(null); setJobId(null)
    try {
      const res = await api.post<Job>('/api/v1/scraper/submit', {
        search_queries: q, categories: selCats,
        locations: locs.filter(Boolean), sources: selSrcs, max_leads: maxLeads,
      })
      setJobId(res.id)
    } catch(e) { setErr(e instanceof Error ? e.message : 'Submission failed') }
    finally { setBusy(false) }
  }

  const reset = useCallback(() => {
    setJobId(null); setErr(null)
    setFCat(''); setFCity(''); setOnlyPhone(false); setOnlyEmail(false)
  }, [])

  const inp = 'w-full px-3 py-2 rounded-lg bg-white/5 border border-white/8 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-violet-500/50 transition-colors'
  const items = (results?.items ?? []).filter(l =>
    !fCity || (l.city||'').toLowerCase().includes(fCity.toLowerCase())
  )

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <SectionHeader
        title="B2B Lead Intelligence"
        subtitle="ImexBay ecosystem: Importers · Exporters · Freight · Customs · CA Firms · CFOs · Startups · Logistics"
        action={jobId && <Button variant="ghost" size="sm" onClick={reset}>New search</Button>}
      />

      {!jobId && (
        <div className="space-y-5">
          {/* Queries */}
          <Card>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-2">
              <Search className="w-3.5 h-3.5"/> Search Queries
            </p>
            <div className="space-y-2">
              {queries.map((q,i)=>(
                <div key={i} className="flex gap-2">
                  <input value={q} onChange={e=>setQueries(qs=>qs.map((x,j)=>j===i?e.target.value:x))}
                    placeholder={['importer exporter Hyderabad','freight forwarding Mumbai','CA firm GST'][i]??'Add query…'}
                    className={cn(inp,'flex-1')}
                    onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();setQueries(q=>[...q,''])}}}
                  />
                  {queries.length > 1 && (
                    <button onClick={()=>setQueries(q=>q.filter((_,j)=>j!==i))}
                      className="p-2 text-gray-600 hover:text-red-400 rounded-lg hover:bg-white/5">
                      <X className="w-4 h-4"/>
                    </button>
                  )}
                </div>
              ))}
            </div>
            <button onClick={()=>setQueries(q=>[...q,''])}
              className="mt-2 flex items-center gap-1.5 text-xs text-gray-500 hover:text-violet-400 transition-colors">
              <Plus className="w-3.5 h-3.5"/> Add query
            </button>
          </Card>

          {/* Segments */}
          <Card>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Segments <span className="text-gray-600 normal-case font-normal">(empty = all {cats.length})</span>
            </p>
            <div className="flex flex-wrap gap-2">
              {cats.map(cat=>(
                <button key={cat.id} onClick={()=>toggle(selCats,setSelCats,cat.id)}
                  className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-all',
                    selCats.includes(cat.id)?(CAT_CLR[cat.id]??'border-violet-500/40 text-violet-300')
                    :'border-white/8 text-gray-500 hover:text-gray-300 hover:border-white/15')}>
                  {cat.icon} {cat.label}
                </button>
              ))}
            </div>
          </Card>

          {/* Cities */}
          <Card>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-2">
              <MapPin className="w-3.5 h-3.5"/> Cities
              <span className="text-gray-600 normal-case font-normal">({locs.length} selected — more = more leads)</span>
            </p>
            <div className="flex flex-wrap gap-2">
              {CITIES.map(city=>(
                <button key={city} onClick={()=>toggle(locs,setLocs,city)}
                  className={cn('px-3 py-1.5 rounded-lg text-xs border transition-all',
                    locs.includes(city)?'border-violet-500/40 text-violet-300 bg-violet-500/10'
                    :'border-white/8 text-gray-500 hover:text-gray-300 hover:border-white/15')}>
                  {city}
                </button>
              ))}
            </div>
          </Card>

          {/* Sources */}
          <Card>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Data Sources</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {srcs.map(src=>(
                <button key={src.id} onClick={()=>toggle(selSrcs,setSelSrcs,src.id)}
                  className={cn('flex flex-col gap-0.5 p-3 rounded-lg border transition-all text-left',
                    selSrcs.includes(src.id)?'border-violet-500/40 bg-violet-500/8'
                    :'border-white/8 bg-white/2 hover:border-white/15')}>
                  <div className="flex items-center gap-2">
                    <span className={cn('text-[10px] px-1.5 py-0.5 rounded font-medium',SRC_CLR[src.id]??'bg-white/8 text-gray-400')}>{src.label}</span>
                    <span className={cn('text-[10px] px-1.5 py-0.5 rounded',
                      src.coverage==='High'?'text-emerald-400 bg-emerald-500/10':'text-amber-400 bg-amber-500/10')}>{src.coverage}</span>
                  </div>
                  <p className="text-[10px] text-gray-600 mt-0.5">{src.best_for}</p>
                </button>
              ))}
            </div>
          </Card>

          {/* Max leads */}
          <div className="flex items-center gap-3">
            <p className="text-xs text-gray-500 shrink-0">Max leads:</p>
            {[100,200,500,1000].map(n=>(
              <button key={n} onClick={()=>setMaxLeads(n)}
                className={cn('px-3 py-1.5 rounded-lg text-xs border transition-all',
                  maxLeads===n?'border-violet-500/40 text-violet-300 bg-violet-500/10'
                  :'border-white/8 text-gray-500 hover:text-gray-300')}>
                {n}
              </button>
            ))}
          </div>

          {err && <ErrorAlert message={err}/>}
          <Button onClick={()=>void submit()} loading={busy} size="lg" className="w-full">
            <Search className="w-4 h-4 mr-2"/>
            Find B2B Leads ({locs.length} cities × {selCats.length||'all'} segments)
          </Button>
        </div>
      )}

      {/* Progress */}
      {job && !['success','failed'].includes(job.status) && (
        <Card className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-white">
                Scraping leads across {(job.meta?.locations as string[]|undefined)?.length ?? 0} cities…
              </p>
              <p className="text-xs text-gray-500 mt-0.5">{PROG(job.progress)}</p>
            </div>
            <JobStatusBadge status={job.status}/>
          </div>
          <ProgressBar value={job.progress}/>
          <p className="text-xs text-gray-600">
            {(job.meta?.locations as string[]|undefined)?.join(' · ')} · Max {job.meta?.max_leads as number ?? 200} leads
          </p>
        </Card>
      )}

      {job?.status==='failed' && (
        <div className="space-y-3">
          <ErrorAlert message={job.error??'Scraping failed'}/>
          <Button variant="secondary" size="sm" onClick={reset}>Retry</Button>
        </div>
      )}

      {/* Results */}
      {results && (
        <div className="space-y-5 animate-in fade-in duration-300">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="w-5 h-5 text-emerald-400"/>
              <div>
                <p className="text-base font-semibold text-white">{results.total} leads found</p>
                <p className="text-xs text-gray-500">
                  {results.summary.with_phone??0} with phone ·{' '}
                  {results.summary.with_email??0} with email ·{' '}
                  {results.summary.with_website??0} with website
                </p>
              </div>
            </div>
            {/* Uses DB-backed download — not generate_excel */}
            <LeadDownloadButton jobId={job!.id}/>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              {label:'Total', val:results.summary.total_leads??results.total, clr:'text-violet-400', Icon:Building2},
              {label:'Phone', val:results.summary.with_phone??0, clr:'text-emerald-400', Icon:Phone},
              {label:'Email', val:results.summary.with_email??0, clr:'text-blue-400', Icon:Mail},
              {label:'Website',val:results.summary.with_website??0, clr:'text-amber-400', Icon:Globe},
            ].map(({label,val,clr,Icon})=>(
              <Card key={label} className="flex items-center gap-3">
                <div className={cn('w-8 h-8 rounded-lg bg-white/8 flex items-center justify-center shrink-0',clr)}>
                  <Icon className="w-4 h-4"/>
                </div>
                <div>
                  <p className="text-xs text-gray-500">{label}</p>
                  <p className="text-lg font-bold text-white font-mono">{val}</p>
                </div>
              </Card>
            ))}
          </div>

          {/* Category pills */}
          {results.summary.by_category && (
            <div className="flex flex-wrap gap-2">
              {Object.entries(results.summary.by_category).sort(([,a],[,b])=>b-a).map(([cat,n])=>(
                <button key={cat} onClick={()=>setFCat(fCat===cat?'':cat)}
                  className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-all',
                    fCat===cat?(CAT_CLR[cat]??'border-violet-500/40 text-violet-300')
                    :'border-white/8 text-gray-500 hover:text-gray-300')}>
                  {cat.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}
                  <span className="font-mono font-bold">{n}</span>
                </button>
              ))}
            </div>
          )}

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <Filter className="w-3.5 h-3.5 text-gray-500"/>
            <input value={fCity} onChange={e=>setFCity(e.target.value)} placeholder="Filter city…"
              className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/8 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-violet-500/50 w-32"/>
            <button onClick={()=>setOnlyPhone(v=>!v)}
              className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-all',
                onlyPhone?'border-emerald-500/40 text-emerald-300 bg-emerald-500/10':'border-white/8 text-gray-500 hover:text-gray-300')}>
              <Phone className="w-3 h-3"/> With phone
            </button>
            <button onClick={()=>setOnlyEmail(v=>!v)}
              className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-all',
                onlyEmail?'border-blue-500/40 text-blue-300 bg-blue-500/10':'border-white/8 text-gray-500 hover:text-gray-300')}>
              <Mail className="w-3 h-3"/> With email
            </button>
            {(fCat||fCity||onlyPhone||onlyEmail) && (
              <button onClick={()=>{setFCat('');setFCity('');setOnlyPhone(false);setOnlyEmail(false)}}
                className="text-xs text-gray-600 hover:text-gray-400">Clear</button>
            )}
          </div>

          {items.length===0
            ? <EmptyState title="No leads match filters" description="Try removing filters."/>
            : <div className="space-y-3">{items.map(l=><LeadCard key={l.id} lead={l}/>)}</div>
          }
        </div>
      )}
    </div>
  )
}