import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api, type Run, type SettingsResponse, type Stats } from './api'
import { useToast } from './components/toast'

export function useStats() {
  return useQuery({
    queryKey: ['stats'],
    queryFn: () => api.get<Stats>('/stats'),
    refetchInterval: (q) => (q.state.data?.active_run ? 2000 : 15000),
  })
}

export function useSettings() {
  return useQuery({ queryKey: ['settings'], queryFn: () => api.get<SettingsResponse>('/settings') })
}

export function useRuns(limit = 30) {
  const { data: stats } = useStats()
  return useQuery({
    queryKey: ['runs', limit, stats?.active_run ?? null],
    queryFn: () => api.get<Run[]>(`/runs?limit=${limit}`),
    refetchInterval: stats?.active_run ? 3000 : false,
  })
}

/** Start a background run, then jump to its live log. */
export function useStartRun({ navigateToRun = true } = {}) {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: (body: { kind: 'pipeline' | 'job'; options?: Record<string, unknown> }) =>
      api.post<{ id: number }>('/runs', { options: {}, ...body }),
    onSuccess: ({ id }) => {
      qc.invalidateQueries({ queryKey: ['stats'] })
      qc.invalidateQueries({ queryKey: ['runs'] })
      toast(`Run #${id} started`)
      if (navigateToRun) navigate(`/runs/${id}`)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
}
