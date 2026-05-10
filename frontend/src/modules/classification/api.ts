import { api } from '@lib/api'

export const classificationApi = {
  classify: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.upload('/api/v1/classification', form)
  },
}