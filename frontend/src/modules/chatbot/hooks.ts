import { useMutation } from '@tanstack/react-query'
import { chatbotApi } from './api'

export function useChatbot() {
  return useMutation({
    mutationFn: (query: string) => chatbotApi.ask(query),
  })
}