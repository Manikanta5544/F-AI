import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@store/auth.store'
import { Button, ErrorAlert } from '@components/ui'

export default function LoginPage() {
  const navigate = useNavigate()
  const { login, isLoading, error, clearError } = useAuthStore()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await login(email, password)
      navigate('/dashboard')
    } catch { /* error shown via store */ }
  }

  const inputClass = 'w-full px-4 py-2.5 rounded-lg bg-white/6 border border-white/10 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-violet-500/60 transition-colors'

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="w-12 h-12 rounded-2xl bg-violet-600 flex items-center justify-center mx-auto mb-4">
            <span className="text-xl font-bold text-white">AI</span>
          </div>
          <h1 className="text-xl font-bold text-white">F-AI Platform</h1>
          <p className="text-sm text-gray-500 mt-1">Document Intelligence Platform</p>
        </div>

        <div className="bg-gray-900/60 border border-white/8 rounded-2xl p-6">
          <h2 className="text-base font-semibold text-white mb-1">Sign in</h2>
          <p className="text-sm text-gray-500 mb-5">Enter your credentials to continue</p>

          <form onSubmit={e => { void handleSubmit(e) }} className="space-y-4">
            {error && <ErrorAlert message={error} />}

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-gray-500">Email</label>
              <input type="email" required value={email} onChange={e => { clearError(); setEmail(e.target.value) }} placeholder="you@example.com" className={inputClass} />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-gray-500">Password</label>
              <input type="password" required value={password} onChange={e => { clearError(); setPassword(e.target.value) }} placeholder="••••••••" className={inputClass} />
            </div>

            <Button type="submit" loading={isLoading} className="w-full mt-2" size="lg">
              Sign in
            </Button>
          </form>
        </div>
      </div>
    </div>
  )
}