import { useMutation } from '@tanstack/react-query'
import { classificationApi } from './api'

export function useClassification() {
  return useMutation({
    mutationFn: (file: File) => classificationApi.classify(file),
  })
}