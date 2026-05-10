import { create } from 'zustand'
import { api } from '@lib/api'
import type { AuthUser, TokenResponse } from '@/types/domain.types'

interface AuthState {
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  clearError: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: (() => {
    try {
      const raw = sessionStorage.getItem('auth_user')
      return raw ? (JSON.parse(raw) as AuthUser) : null
    } catch { return null }
  })(),
  isAuthenticated: !!sessionStorage.getItem('access_token'),
  isLoading: false,
  error: null,

  login: async (email, password) => {
    set({ isLoading: true, error: null })
    try {
      const tokens = await api.post<TokenResponse>('/api/v1/auth/login', { email, password })
      sessionStorage.setItem('access_token', tokens.access_token)
      const user = await api.get<AuthUser>('/api/v1/auth/me')
      sessionStorage.setItem('auth_user', JSON.stringify(user))
      set({ user, isAuthenticated: true, isLoading: false })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Login failed'
      set({ error: msg, isLoading: false })
      throw e
    }
  },

  logout: async () => {
    try { await api.post('/api/v1/auth/logout') } catch { /* best effort */ }
    sessionStorage.removeItem('access_token')
    sessionStorage.removeItem('auth_user')
    set({ user: null, isAuthenticated: false })
  },

  clearError: () => set({ error: null }),
}))