import { useEffect, useRef } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock, ScrollText, Square } from 'lucide-react'
import clsx from 'clsx'
import { api, runLabel, type Run } from '../api'
import { useRuns } from '../hooks'
import { useToast } from '../components/toast'
import RunMenu from '../components/RunMenu'
import { Badge, Button, Card, EmptyState, PageHeader, RUN_STATUS, Spinner, duration, formatDate, timeAgo } from '../components/ui'

export default function Runs() {
  const { runId } = useParams()
  const { data: runs, isLoading } = useRuns(50)
  const selected = runId ? Number(runId) : runs?.[0]?.id

  return (
    <>
      <PageHeader title="Runs" description="Every scan and application run, with its full log." actions={<RunMenu />} />
      {isLoading ? (
        <div className="flex justify-center p-16"><Spinner /></div>
      ) : !runs?.length ? (
        <Card>
          <EmptyState icon={<ScrollText className="size-5" />} title="No runs yet" description="Start a run to scan for jobs. Its live log shows up here." />
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
          <Card className="h-fit overflow-hidden">
            <ul className="max-h-[70vh] divide-y divide-zinc-200 overflow-y-auto dark:divide-zinc-800">
              {runs.map((r) => (
                <li key={r.id}>
                  <Link
                    to={`/runs/${r.id}`}
                    className={clsx('block px-4 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/50', r.id === selected && 'bg-indigo-50/60 dark:bg-indigo-950/40')}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">#{r.id} {runLabel(r)}</span>
                      <Badge tone={RUN_STATUS[r.status].tone}>{RUN_STATUS[r.status].label}</Badge>
                    </div>
                    <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                      {timeAgo(r.started_at)}
                      {r.trigger === 'schedule' && ' · scheduled'}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
          {selected && <RunDetail id={selected} />}
        </div>
      )}
    </>
  )
}

function RunDetail({ id }: { id: number }) {
  const qc = useQueryClient()
  const toast = useToast()
  const logRef = useRef<HTMLPreElement>(null)
  const stick = useRef(true)
  const { data: run } = useQuery({
    queryKey: ['run', id],
    queryFn: () => api.get<Run>(`/runs/${id}`),
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 1500 : false),
  })
  const cancel = useMutation({
    mutationFn: () => api.post(`/runs/${id}/cancel`),
    onSuccess: () => {
      toast('Cancelling…')
      qc.invalidateQueries({ queryKey: ['run', id] })
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  useEffect(() => {
    if (run && run.status !== 'running') {
      qc.invalidateQueries({ queryKey: ['stats'] })
      qc.invalidateQueries({ queryKey: ['runs'] })
    }
  }, [run?.status, qc, run])

  useEffect(() => {
    const el = logRef.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [run?.log])

  if (!run) return <Card className="flex justify-center p-16"><Spinner /></Card>
  const s = RUN_STATUS[run.status]

  return (
    <Card className="flex min-w-0 flex-col overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-zinc-200 px-5 py-4 dark:border-zinc-800">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold">#{run.id} {runLabel(run)}</h2>
            <Badge tone={s.tone}>{s.label}</Badge>
          </div>
          <p className="mt-1 flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            <Clock className="size-3.5" />
            {formatDate(run.started_at, true)} · {duration(run.started_at, run.finished_at)}
            {run.trigger === 'schedule' && ' · scheduled'}
          </p>
          {run.summary && <p className={clsx('mt-2 text-sm', run.status === 'failed' && 'text-red-600 dark:text-red-400')}>{run.summary}</p>}
        </div>
        {run.status === 'running' && (
          <Button variant="danger" size="sm" icon={<Square className="size-3.5" />} loading={cancel.isPending} onClick={() => cancel.mutate()}>
            Cancel
          </Button>
        )}
      </div>
      <pre
        ref={logRef}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        }}
        className="h-[60vh] overflow-auto bg-zinc-950 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap text-zinc-200"
      >
        {run.log || (run.status === 'running' ? 'Starting…' : 'No output.')}
        {run.status === 'running' && <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-zinc-400 align-middle" />}
      </pre>
    </Card>
  )
}
