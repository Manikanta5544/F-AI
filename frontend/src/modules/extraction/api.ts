import { api } from '@lib/api'

export const extractionApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.upload('/api/v1/extraction', form)
  },
}