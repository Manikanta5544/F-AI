import { useRef, useState } from 'react'
import { api } from '@lib/api'

export function useUpload() {
  const controller = useRef<AbortController | null>(null)
  const [progress, setProgress] = useState(0)

  const upload = async (file: File, endpoint: string) => {
    controller.current = new AbortController()
    const form = new FormData()
    form.append('file', file)

    return api.upload(endpoint, form, setProgress, controller.current.signal)
  }

  const cancel = () => controller.current?.abort()

  return { upload, cancel, progress }
}