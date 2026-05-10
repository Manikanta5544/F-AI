/**
 * scraper/hooks.ts
 *
 * React hooks for scraper-related operations, such as submitting scrape jobs.
 */
import { useMutation } from '@tanstack/react-query'
import { scraperApi, type ScrapeSubmitBody } from './api'

/**
 * Submit a scrape job — wraps POST /api/v1/scraper/submit.
 *
 * Usage (in ScraperPage):
 *   const submitScrape = useSubmitScraper()
 *   submitScrape.mutateAsync({ platform: 'amazon', urls: [...] })
 */
export function useSubmitScraper() {
  return useMutation({
    mutationFn: (body: ScrapeSubmitBody) => scraperApi.submit(body),
  })
}

/**
 * @deprecated Use useSubmitScraper — this is kept only so old import sites
 * don't hard-crash. It now routes through the correct endpoint internally.
 */
export function useStartScraper() {
  return useMutation({
    mutationFn: (urls: string[]) => scraperApi.start(urls),
  })
}