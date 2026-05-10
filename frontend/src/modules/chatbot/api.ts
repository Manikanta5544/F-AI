import { api } from '@lib/api'

export const chatbotApi = {
  ask: (query: string) =>
    api.post('/api/v1/chat', { query }),
}