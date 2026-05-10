import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { cn } from '@lib/utils'
import { useAuthStore } from '@store/auth.store'
import {
  FileText, CreditCard, ScanLine, ShoppingCart,
  FlaskConical, MessageSquare, LayoutDashboard,
  LogOut, ChevronLeft, ChevronRight, User,
} from 'lucide-react'
import type { ReactNode } from 'react'

const NAV = [
  { to: '/dashboard',       label: 'Dashboard',       icon: LayoutDashboard, tag: '' },
  { to: '/invoice',         label: 'Invoice',          icon: FileText,        tag: '#11' },
  { to: '/bank-statement',  label: 'Bank Statement',   icon: CreditCard,      tag: '#5'  },
  { to: '/ocr',             label: 'OCR / YOLO',       icon: ScanLine,        tag: '#4,7' },
  { to: '/scraper',         label: 'Scraper',          icon: ShoppingCart,    tag: '#1-3' },
  { to: '/classification',  label: 'Classification',   icon: FlaskConical,    tag: '#10' },
  { to: '/chatbot',         label: 'AI Chatbot',       icon: MessageSquare,   tag: '#8,9' },
]

export function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const { user, logout } = useAuthStore()
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      {/* Sidebar */}
      <aside className={cn(
        'flex flex-col border-r border-white/8 bg-gray-900/60 transition-all duration-200 shrink-0',
        collapsed ? 'w-16' : 'w-56',
      )}>
        {/* Logo + toggle */}
        <div className="flex items-center justify-between px-3 h-14 border-b border-white/8">
          {!collapsed && (
            <span className="font-bold text-sm text-white tracking-tight">AI Platform</span>
          )}
          <button onClick={() => setCollapsed(v => !v)} className="p-1.5 rounded-lg hover:bg-white/8 text-gray-500 hover:text-gray-300 ml-auto">
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>

        {/* Nav items */}
        <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
          {NAV.map(({ to, label, icon: Icon, tag }) => {
            const active = pathname === to || (to !== '/dashboard' && pathname.startsWith(to))
            return (
              <Link
                key={to}
                to={to}
                title={collapsed ? label : undefined}
                className={cn(
                  'flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm transition-colors relative group',
                  active ? 'bg-violet-500/20 text-violet-300' : 'text-gray-400 hover:bg-white/6 hover:text-gray-200',
                )}
              >
                <Icon className="w-4 h-4 shrink-0" />
                {!collapsed && (
                  <>
                    <span className="flex-1 truncate">{label}</span>
                    {tag && <span className="text-[10px] text-gray-600 font-mono">{tag}</span>}
                  </>
                )}
                {active && <span className="absolute right-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-violet-400 rounded-l" />}
              </Link>
            )
          })}
        </nav>

        {/* Footer: user + logout */}
        <div className="border-t border-white/8 p-2">
          {collapsed ? (
            <button onClick={() => void logout()} className="w-full flex justify-center p-2 text-gray-600 hover:text-gray-300" title="Logout">
              <LogOut className="w-4 h-4" />
            </button>
          ) : (
            <div className="flex items-center gap-2 px-2 py-1.5">
              <div className="w-7 h-7 rounded-full bg-violet-600 flex items-center justify-center text-xs font-bold shrink-0">
                {user?.name?.charAt(0)?.toUpperCase() ?? 'U'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-gray-300 truncate">{user?.name ?? 'User'}</p>
                <p className="text-[10px] text-gray-600 truncate">{user?.email}</p>
              </div>
              <button onClick={() => void logout()} className="text-gray-600 hover:text-gray-300 p-1">
                <LogOut className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  )
}