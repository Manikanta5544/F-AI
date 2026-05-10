import { useQuery } from '@tanstack/react-query'
import { api } from '@lib/api'
import type { Job } from '@/types/domain.types'

const TERMINAL: Job['status'][] = ['success', 'failed']

/**
 * Polls /api/v1/jobs/:jobId every 2 s until terminal status.
 * Returns the full Job object including result when done.
 */
export function useJobPoller(jobId: string | null) {
  return useQuery<Job>({
    queryKey: ['job', jobId],
    queryFn: () => api.get<Job>(`/api/v1/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (!status || TERMINAL.includes(status)) return false
      return 2_000
    },
    staleTime: 0,
  })
}