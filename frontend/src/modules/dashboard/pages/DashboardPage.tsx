import { useNavigate } from 'react-router-dom'
import { FileText, CreditCard, ScanLine, ShoppingCart, FlaskConical, MessageSquare } from 'lucide-react'

const FEATURES = [
  { to: '/invoice',        label: 'Invoice Extraction',     desc: 'Extract structured data from any invoice PDF/image', icon: FileText,      tag: 'Task #11', color: 'border-amber-500/30 hover:border-amber-500/60' },
  { to: '/bank-statement', label: 'Bank Statement',         desc: 'Extract transactions from all major Indian banks',    icon: CreditCard,    tag: 'Task #5',  color: 'border-blue-500/30 hover:border-blue-500/60' },
  { to: '/ocr',            label: 'OCR & YOLO Pipeline',    desc: 'Multi-engine OCR with YOLO layout detection',        icon: ScanLine,      tag: 'Task #4,7', color: 'border-violet-500/30 hover:border-violet-500/60' },
  { to: '/scraper',        label: 'Web Scraper',            desc: 'Amazon, Flipkart, Swiggy, Zomato & manual brands',   icon: ShoppingCart,  tag: 'Task #1-3', color: 'border-emerald-500/30 hover:border-emerald-500/60' },
  { to: '/classification', label: 'Doc Classification',     desc: 'ML + DistilBERT document type detection',            icon: FlaskConical,  tag: 'Task #10', color: 'border-pink-500/30 hover:border-pink-500/60' },
  { to: '/chatbot',        label: 'AI Chatbot (RAG)',        desc: 'LangChain chatbot with document retrieval',          icon: MessageSquare, tag: 'Task #8,9', color: 'border-cyan-500/30 hover:border-cyan-500/60' },
]

export default function DashboardPage() {
  const navigate = useNavigate()

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">AI Document Intelligence — 11 Tasks across 6 modules</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {FEATURES.map(({ to, label, desc, icon: Icon, tag, color }) => (
          <button
            key={to}
            onClick={() => navigate(to)}
            className={`text-left p-5 rounded-xl border bg-white/2 transition-all hover:bg-white/5 active:scale-[0.98] ${color}`}
          >
            <Icon className="w-6 h-6 text-gray-400 mb-3" />
            <p className="text-sm font-semibold text-white">{label}</p>
            <p className="text-xs text-gray-500 mt-1 leading-relaxed">{desc}</p>
            <p className="text-[10px] text-gray-700 mt-2 font-mono">{tag}</p>
          </button>
        ))}
      </div>
    </div>
  )
}