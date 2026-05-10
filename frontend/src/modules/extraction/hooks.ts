import { useMutation } from '@tanstack/react-query'
import { extractionApi } from './api'

export function useExtraction() {
  return useMutation({
    mutationFn: (file: File) => extractionApi.upload(file),
  })
}