import axios, { type AxiosError } from 'axios'
import { ENV } from '@/config/env'
import type { ApiError } from '@/types/domain.types'

// Export raw instance for hooks that need direct access (e.g. useDownloadExcel)
export const axiosInstance = axios.create({
  baseURL: ENV.API_URL,
  withCredentials: true,
  timeout: 60_000,
})

// Attach access token from memory on every request
axiosInstance.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// On 401 → clear token and redirect to login
axiosInstance.interceptors.response.use(
  (r) => r,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      sessionStorage.removeItem('access_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export class ApiClientError extends Error {
  code: string
  status: number
  constructor(error: AxiosError<{ error: ApiError }>) {
    super(error.response?.data?.error?.message ?? error.message ?? 'Unexpected error')
    this.code = error.response?.data?.error?.code ?? 'UNKNOWN'
    this.status = error.response?.status ?? 0
  }
}

function handleError(error: unknown): never {
  if (axios.isAxiosError(error)) throw new ApiClientError(error)
  throw error
}

export const api = {
  get: async <T>(url: string): Promise<T> => {
    try {
      const res = await axiosInstance.get<{ data: T }>(url)
      return res.data.data
    } catch (e) { handleError(e) }
  },

  post: async <T>(url: string, body?: unknown): Promise<T> => {
    try {
      const res = await axiosInstance.post<{ data: T }>(url, body)
      return res.data.data
    } catch (e) { handleError(e) }
  },

  upload: async <T>(
    url: string,
    formData: FormData,
    onProgress?: (p: number) => void,
    signal?: AbortSignal,
  ): Promise<T> => {
    try {
      const res = await axiosInstance.post<{ data: T }>(url, formData, {
        signal,
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e) => {
          if (e.total && onProgress) onProgress(Math.round((e.loaded / e.total) * 100))
        },
      })
      return res.data.data
    } catch (e) { handleError(e) }
  },
}