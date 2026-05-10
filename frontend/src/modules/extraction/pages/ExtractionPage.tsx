import { useState } from 'react'
import { FileDropzone } from '@components/ui/FileDropZone'
import { useExtraction } from '../hooks'
import { DownloadExcelButton } from '@components/ui/DownloadExcelButton'
import type { Job } from '@/types/domain.types'

export default function ExtractionPage() {
  const [jobId, setJobId] = useState<string | null>(null)
  const extract = useExtraction()

  return (
    <div>
      <FileDropzone
        onFiles={async (f) => {
          const res = await extract.mutateAsync(f[0]!)
          setJobId((res as Job).id)
        }}
      />

      {jobId && <DownloadExcelButton jobId={jobId} jobType="extraction" />}
    </div>
  )
}