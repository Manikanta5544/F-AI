/**
 * useDownloadExcel
 *
 * Downloads a completed job result as an Excel file.
 * Triggers a native browser "Save As" dialog — no third-party library needed.
 *
 * Usage:
 *   const { download, isDownloading } = useDownloadExcel()
 *   <button onClick={() => download(job.id, 'invoice_results')}>Download Excel</button>
 */
import { useCallback, useState } from 'react'
import { axiosInstance } from '@lib/api'

interface UseDownloadExcelReturn {
  download:      (jobId: string, filenameHint?: string) => Promise<void>
  isDownloading: boolean
  error:         string | null
}

export function useDownloadExcel(): UseDownloadExcelReturn {
  const [isDownloading, setIsDownloading] = useState(false)
  const [error, setError]                 = useState<string | null>(null)

  const download = useCallback(async (jobId: string, filenameHint = 'result') => {
    setIsDownloading(true)
    setError(null)

    try {
      // ✅ FIX: axiosInstance already has baseURL = ENV.API_URL, so we only
      // need the path. The interceptor will attach the Bearer token automatically.
      const response = await axiosInstance.get(`/api/v1/download/${jobId}`, {
        responseType: 'blob',
        // withCredentials is already set as a default on axiosInstance,
        // but being explicit here is fine and harmless.
        withCredentials: true,
      })

      const contentType = response.headers['content-type'] as string | undefined
      if (!contentType || !contentType.includes('application/vnd.openxmlformats')) {
        throw new Error('Invalid file response — server did not return an Excel file')
      }

      const disposition = response.headers['content-disposition'] as string | undefined
      let filename = `${filenameHint}_${jobId.slice(0, 8)}.xlsx`

      if (disposition) {
        const utf8Match  = disposition.match(/filename\*=UTF-8''([^;\s]+)/i)
        const plainMatch = disposition.match(/filename="?([^";\s]+)"?/i)
        if (utf8Match?.[1]) {
          filename = decodeURIComponent(utf8Match[1])
        } else if (plainMatch?.[1]) {
          filename = plainMatch[1]
        }
      }

      const blob   = new Blob([response.data as BlobPart], { type: contentType })
      const url    = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href        = url
      anchor.download    = filename
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      URL.revokeObjectURL(url)

    } catch (err) {
      // Axios wraps non-2xx responses as errors; extract a readable message.
      let message = 'Download failed'
      if (err instanceof Error) {
        message = err.message
      }
      setError(message)
    } finally {
      setIsDownloading(false)
    }
  }, [])

  return { download, isDownloading, error }
}