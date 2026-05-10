/**
 * scraper/api.ts
 */
import { api } from '@lib/api'
import type { Job, ScrapeResults, Platform } from '@/types/domain.types'

export interface ScrapeSubmitBody {
  platform:     Platform
  urls:         string[]
  brand_filter?: string[]
}

export const scraperApi = {
  /**
   * Submit a scrape job.
   */
  submit: (body: ScrapeSubmitBody): Promise<Job> =>
    api.post<Job>('/api/v1/scraper/submit', body),

  /**
   * @deprecated Use scraperApi.submit() — kept for any legacy callers.
   * Redirects to the correct endpoint so nothing breaks silently.
   */
  start: (urls: string[]): Promise<Job> =>
    api.post<Job>('/api/v1/scraper/submit', {
      platform: 'amazon',   // safe default for legacy callers
      urls,
    }),

  /** Fetch paginated scrape results for a completed job. */
  getResults: (jobId: string, page = 1, perPage = 50): Promise<ScrapeResults> =>
    api.get<ScrapeResults>(
      `/api/v1/scraper/results/${jobId}?page=${page}&per_page=${perPage}`,
    ),
}