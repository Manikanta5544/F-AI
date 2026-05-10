import { api } from '@lib/api'
import type { Job } from '@/types/domain.types'

export const ocrApi = {
  submit: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.upload<Job>('/api/v1/ocr', form)
  },

  get: (jobId: string) =>
    api.get(`/api/v1/ocr/${jobId}`),
}