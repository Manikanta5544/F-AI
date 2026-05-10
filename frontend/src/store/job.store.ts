import { create } from 'zustand'
import type { Job } from '@/types/domain.types'

interface JobState {
  jobs: Record<string, Job>
  upsert: (job: Job) => void
}

export const useJobStore = create<JobState>((set) => ({
  jobs: {},
  upsert: (job) =>
    set((s) => ({ jobs: { ...s.jobs, [job.id]: job } })),
}))