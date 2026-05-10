import { useEffect, useRef } from 'react'

export function useSSE(url: string | null, onMessage: (data: unknown) => void) {
  const retryRef = useRef(1000)

  useEffect(() => {
    if (!url) return

    let es: EventSource | null = null
    let timeout: ReturnType<typeof setTimeout>

    const connect = () => {
      es = new EventSource(url)

      es.onopen = () => {
        retryRef.current = 1000
      }

      es.onmessage = (e) => {
        try {
          onMessage(JSON.parse(e.data))
        } catch {}
      }

      es.onerror = () => {
        es?.close()
        timeout = setTimeout(connect, retryRef.current)
        retryRef.current = Math.min(retryRef.current * 2, 30000)
      }
    }

    connect()

    return () => {
      es?.close()
      clearTimeout(timeout)
    }
  }, [url, onMessage])
}