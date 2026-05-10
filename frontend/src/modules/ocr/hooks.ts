import { useMutation, useQuery } from '@tanstack/react-query'
import { ocrApi } from './api'

export function useSubmitOCR() {
  return useMutation({
    mutationFn: (file: File) => ocrApi.submit(file),
  })
}

export function useOCRResult(jobId: string | null) {
  return useQuery({
    queryKey: ['ocr', jobId],
    queryFn: () => ocrApi.get(jobId!),
    enabled: !!jobId,
  })
}