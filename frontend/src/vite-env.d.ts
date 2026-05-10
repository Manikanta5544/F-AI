/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  readonly VITE_ENABLE_YOLO?: string
  readonly VITE_ENABLE_OCR_ENSEMBLE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
