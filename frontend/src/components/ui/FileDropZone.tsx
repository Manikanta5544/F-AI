import { useRef } from 'react'

export function FileDropzone({
  onFiles,
  accept = 'application/pdf,image/png,image/jpeg',
}: {
  onFiles: (f: File[]) => void
  accept?: string
}) {
  const ref = useRef<HTMLInputElement>(null)

  return (
    <div
      onClick={() => ref.current?.click()}
      className="border p-6 cursor-pointer hover:bg-gray-800"
    >
      Upload file
      <input
        ref={ref}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files || [])
          const MAX_SIZE_MB = 10

          const valid = files.filter((f) => {
            if (f.size > MAX_SIZE_MB * 1024 * 1024) {
              console.warn('File too large:', f.name)
              return false
            }
            return true
          })

          onFiles(valid)
        }}
      />
    </div>
  )
}