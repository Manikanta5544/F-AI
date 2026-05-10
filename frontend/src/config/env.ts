export const ENV = {
  API_URL: import.meta.env.VITE_API_URL ?? 'http://localhost:8000',

  FEATURES: {
    YOLO: import.meta.env.VITE_ENABLE_YOLO === 'true',
    OCR_ENSEMBLE: import.meta.env.VITE_ENABLE_OCR_ENSEMBLE === 'true',
  },
} as const