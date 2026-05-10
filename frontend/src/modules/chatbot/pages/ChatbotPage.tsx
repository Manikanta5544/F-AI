import { useState, useRef, useEffect, useCallback } from 'react'
import { api } from '@lib/api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, EmptyState, ErrorAlert } from '@components/ui'
import { Send, Plus, Bot, User, ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@lib/utils'
import { ENV } from '@/config/env'

interface ChatSource { document_id: string; filename: string; page_number: number; chunk_text: string; similarity: number }
interface ChatMessage { id: string; role: string; content: string; created_at: string; sources?: ChatSource[]; isStreaming?: boolean }
interface ChatSession { id: string; title: string; rag_enabled: boolean; created_at: string; messages: ChatMessage[] }

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const [srcOpen, setSrcOpen] = useState(false)
  const isUser = msg.role === 'user'
  return (
    <div className={cn('flex gap-2.5', isUser && 'flex-row-reverse')}>
      <div className={cn('w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5', isUser ? 'bg-violet-600' : 'bg-white/10')}>
        {isUser ? <User className="w-3.5 h-3.5 text-white" /> : <Bot className="w-3.5 h-3.5 text-gray-400" />}
      </div>
      <div className={cn('flex flex-col gap-1.5 max-w-[75%]', isUser && 'items-end')}>
        <div className={cn('px-4 py-3 rounded-2xl text-sm leading-relaxed', isUser ? 'bg-violet-600 text-white rounded-tr-sm' : 'bg-white/6 border border-white/8 text-gray-200 rounded-tl-sm')}>
          <p className="whitespace-pre-wrap">{msg.content}</p>
          {msg.isStreaming && <span className="inline-block w-1.5 h-4 bg-gray-400 ml-0.5 animate-pulse rounded-sm" />}
        </div>
        {msg.sources && msg.sources.length > 0 && (
          <div>
            <button onClick={() => setSrcOpen(v => !v)} className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400 transition-colors">
              {srcOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {msg.sources.length} source{msg.sources.length > 1 ? 's' : ''}
            </button>
            {srcOpen && (
              <div className="mt-1.5 space-y-1.5">
                {msg.sources.map((src, i) => (
                  <div key={i} className="px-3 py-2 rounded-lg bg-white/3 border border-white/8 text-xs">
                    <p className="text-gray-400 font-medium">{src.filename} · p.{src.page_number} · {Math.round(src.similarity * 100)}% match</p>
                    <p className="text-gray-600 mt-0.5 line-clamp-2">{src.chunk_text}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {msg.created_at && <time className="text-[10px] text-gray-700">{new Date(msg.created_at).toLocaleTimeString()}</time>}
      </div>
    </div>
  )
}

export default function ChatbotPage() {
  const qc = useQueryClient()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState('')
  const [streamError, setStreamError] = useState<string | null>(null)
  const [ragEnabled, setRagEnabled] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [streamContent, sessionId])
  useEffect(() => () => { esRef.current?.close() }, [])

  const { data: sessions = [] } = useQuery<ChatSession[]>({ queryKey: ['chatbot-sessions'], queryFn: () => api.get('/api/v1/chat/sessions'), staleTime: 5_000 })
  const { data: session } = useQuery<ChatSession>({ queryKey: ['chatbot-session', sessionId], queryFn: () => api.get(`/api/v1/chat/sessions/${sessionId}`), enabled: !!sessionId, staleTime: 0 })
  const createSession = useMutation({
    mutationFn: () => api.post<ChatSession>('/api/v1/chat/sessions', { rag_enabled: ragEnabled }),
    onSuccess: (s) => { setSessionId(s.id); void qc.invalidateQueries({ queryKey: ['chatbot-sessions'] }) },
  })

  const sendMessage = useCallback(() => {
    if (!input.trim() || !sessionId || streaming) return
    const msg = input.trim(); setInput(''); setStreaming(true); setStreamContent(''); setStreamError(null)
    const token = sessionStorage.getItem('access_token') ?? ''
    const url = `${ENV.API_URL}/api/v1/chat/sessions/${sessionId}/stream?message=${encodeURIComponent(msg)}&token=${encodeURIComponent(token)}`
    esRef.current?.close()
    const es = new EventSource(url); esRef.current = es
    es.addEventListener('token', (e) => { setStreamContent(prev => prev + (e as MessageEvent<string>).data) })
    es.addEventListener('done', () => {
      es.close(); esRef.current = null; setStreaming(false); setStreamContent('')
      void qc.invalidateQueries({ queryKey: ['chatbot-session', sessionId] })
      void qc.invalidateQueries({ queryKey: ['chatbot-sessions'] })
    })
    es.addEventListener('error', () => { es.close(); esRef.current = null; setStreaming(false); setStreamContent(''); setStreamError('Stream error — please try again') })
  }, [input, sessionId, streaming, qc])

  return (
    <div className="flex h-screen overflow-hidden">
      <div className="w-52 border-r border-white/8 flex flex-col bg-gray-900/40 shrink-0">
        <div className="p-3 border-b border-white/8">
          <Button size="sm" variant="secondary" className="w-full" onClick={() => createSession.mutate()} loading={createSession.isPending}>
            <Plus className="w-3.5 h-3.5" />New chat
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {sessions.map(s => (
            <button key={s.id} onClick={() => setSessionId(s.id)}
              className={cn('w-full text-left px-2.5 py-2 rounded-lg text-xs truncate transition-colors', s.id === sessionId ? 'bg-violet-500/20 text-violet-300' : 'text-gray-400 hover:bg-white/5 hover:text-gray-300')}>
              {s.title || 'Untitled'}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-5 py-3 border-b border-white/8 flex items-center justify-between shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-white">{session?.title ?? 'AI Chatbot'}</h2>
            <p className="text-xs text-gray-600">LangChain · {ragEnabled ? 'RAG mode' : 'Direct LLM'}</p>
          </div>
          <button onClick={() => setRagEnabled(v => !v)}
            className={cn('text-xs px-2.5 py-1.5 rounded-lg border transition-all', ragEnabled ? 'border-violet-500/40 text-violet-300 bg-violet-500/10' : 'border-white/10 text-gray-500 hover:text-gray-300')}>
            RAG {ragEnabled ? 'ON' : 'OFF'}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {!sessionId && <EmptyState icon={<Bot className="w-10 h-10" />} title="Start a new chat" description="Create a session and ask questions about your documents." />}
          {(session?.messages ?? []).map(m => <MessageBubble key={m.id} msg={m} />)}
          {streaming && streamContent && <MessageBubble msg={{ id: '__stream__', role: 'assistant', content: streamContent, created_at: '', isStreaming: true }} />}
          {streamError && <ErrorAlert message={streamError} />}
          <div ref={bottomRef} />
        </div>
        <div className="px-5 pb-5 pt-3 border-t border-white/8 shrink-0">
          <div className="flex gap-2 items-end">
            <textarea value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
              placeholder={sessionId ? 'Message… (Enter to send)' : 'Create a session first'}
              disabled={!sessionId || streaming} rows={1}
              className="flex-1 resize-none rounded-xl bg-white/5 border border-white/10 px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-violet-500/50 disabled:opacity-50 max-h-32 overflow-y-auto" />
            <Button onClick={sendMessage} disabled={!input.trim() || !sessionId} loading={streaming} className="h-10 w-10 p-0 shrink-0">
              <Send className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}