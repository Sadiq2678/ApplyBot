import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Briefcase, ChevronLeft, ChevronRight, ExternalLink, FileText, Mail, RefreshCw, Search, Send, Undo2, Wand2, X } from 'lucide-react'
import clsx from 'clsx'
import { api, type Job, type JobSummary } from '../api'
import { useStartRun, useStats } from '../hooks'
import { useToast } from '../components/toast'
import { Badge, Button, Card, EmptyState, Input, JOB_STATUS, PageHeader, ScoreBadge, Select, Spinner, formatDate } from '../components/ui'

const TABS = [
  { value: 'match', label: 'Matches' },
  { value: 'drafted', label: 'Drafted' },
  { value: 'applied', label: 'Applied' },
  { value: 'not_fit', label: 'Not a fit' },
  { value: 'screened_out', label: 'Screened out' },
  { value: 'all', label: 'All' },
]
const PAGE = 50

/** Refetch job data when a background run finishes. */
function useRefreshAfterRun() {
  const qc = useQueryClient()
  const { data: stats } = useStats()
  const prev = useRef<number | null>(null)
  useEffect(() => {
    const active = stats?.active_run ?? null
    if (prev.current && !active) qc.invalidateQueries({ queryKey: ['jobs'] })
    prev.current = active
  }, [stats?.active_run, qc])
}

export default function Jobs() {
  const [params, setParams] = useSearchParams()
  const { jobId } = useParams()
  const navigate = useNavigate()
  useRefreshAfterRun()

  const status = params.get('status') ?? 'match'
  const source = params.get('source') ?? ''
  const sort = params.get('sort') ?? 'score'
  const openOnly = params.get('open_only') !== 'false'
  const page = Number(params.get('page') ?? 0)
  const [q, setQ] = useState(params.get('q') ?? '')

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === '') next.delete(k)
      else next.set(k, v)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next, { replace: true })
  }

  useEffect(() => {
    const t = setTimeout(() => {
      if ((params.get('q') ?? '') !== q) update({ q })
    }, 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  const qs = new URLSearchParams({ status, sort, open_only: String(openOnly), limit: String(PAGE), offset: String(page * PAGE) })
  if (source) qs.set('source', source)
  if (params.get('q')) qs.set('q', params.get('q')!)
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['jobs', 'list', qs.toString()],
    queryFn: () => api.get<{ items: JobSummary[]; total: number }>(`/jobs?${qs}`),
    placeholderData: keepPreviousData,
  })
  const total = data?.total ?? 0
  const search = params.toString() ? `?${params}` : ''

  return (
    <>
      <PageHeader title="Jobs" description="Every job found on Technopark and Infopark, scored against your resume." />

      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-zinc-200 dark:border-zinc-800" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.value}
            role="tab"
            aria-selected={status === t.value}
            onClick={() => update({ status: t.value })}
            className={clsx(
              '-mb-px border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors',
              status === t.value
                ? 'border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400'
                : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title or company" className="pl-9" aria-label="Search jobs" />
        </div>
        <Select value={source} onChange={(e) => update({ source: e.target.value })} className="w-auto" aria-label="Source">
          <option value="">All sources</option>
          <option value="technopark">Technopark</option>
          <option value="infopark">Infopark</option>
        </Select>
        <Select value={sort} onChange={(e) => update({ sort: e.target.value })} className="w-auto" aria-label="Sort">
          <option value="score">Best score</option>
          <option value="newest">Newest</option>
          <option value="closing">Closing soon</option>
        </Select>
        <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
          <input type="checkbox" checked={openOnly} onChange={(e) => update({ open_only: e.target.checked ? null : 'false' })} className="size-4 rounded border-zinc-300 accent-indigo-600" />
          Open only
        </label>
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="flex justify-center p-16"><Spinner /></div>
        ) : !data?.items.length ? (
          <EmptyState icon={<Briefcase className="size-5" />} title="No jobs here" description={status === 'match' ? 'Run a scan to find jobs that fit your resume, or lower the minimum score in Settings.' : 'Try another tab or clear the filters.'} />
        ) : (
          <div className={clsx('overflow-x-auto transition-opacity', isFetching && 'opacity-70')}>
            <table className="w-full text-sm">
              <thead className="border-b border-zinc-200 bg-zinc-50 text-left text-xs font-medium text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-400">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Score</th>
                  <th className="px-4 py-2.5 font-medium">Role</th>
                  <th className="hidden px-4 py-2.5 font-medium md:table-cell">Source</th>
                  <th className="hidden px-4 py-2.5 font-medium sm:table-cell">Closes</th>
                  <th className="hidden px-4 py-2.5 font-medium lg:table-cell">Apply via</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {data.items.map((j) => (
                  <tr
                    key={j.id}
                    onClick={() => navigate(`/jobs/${j.id}${search}`)}
                    className={clsx('cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/50', String(j.id) === jobId && 'bg-indigo-50/60 dark:bg-indigo-950/40')}
                  >
                    <td className="px-4 py-3"><ScoreBadge score={j.score} /></td>
                    <td className="max-w-md px-4 py-3">
                      <Link to={`/jobs/${j.id}${search}`} className="block truncate font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                        {j.title}
                      </Link>
                      <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">{j.company}</p>
                    </td>
                    <td className="hidden px-4 py-3 capitalize text-zinc-600 md:table-cell dark:text-zinc-400">{j.source}</td>
                    <td className={clsx('hidden px-4 py-3 whitespace-nowrap sm:table-cell', !j.is_open ? 'text-zinc-400 line-through' : 'text-zinc-600 dark:text-zinc-400')}>{formatDate(j.closing_date)}</td>
                    <td className="hidden max-w-56 truncate px-4 py-3 text-zinc-600 lg:table-cell dark:text-zinc-400">{j.contact_email || <span className="text-amber-700 dark:text-amber-400">Website</span>}</td>
                    <td className="px-4 py-3"><Badge tone={JOB_STATUS[j.status].tone}>{JOB_STATUS[j.status].label}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > PAGE && (
          <div className="flex items-center justify-between border-t border-zinc-200 px-4 py-3 text-sm dark:border-zinc-800">
            <span className="text-zinc-500">{page * PAGE + 1}–{Math.min(total, (page + 1) * PAGE)} of {total}</span>
            <div className="flex gap-2">
              <Button size="sm" icon={<ChevronLeft className="size-4" />} disabled={page === 0} onClick={() => update({ page: String(page - 1) })}>Previous</Button>
              <Button size="sm" disabled={(page + 1) * PAGE >= total} onClick={() => update({ page: String(page + 1) })}>Next <ChevronRight className="size-4" /></Button>
            </div>
          </div>
        )}
      </Card>

      {jobId && <JobDrawer jobId={Number(jobId)} onClose={() => navigate(`/jobs${search}`)} />}
    </>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">{title}</h3>
      {children}
    </section>
  )
}

function JobDrawer({ jobId, onClose }: { jobId: number; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const start = useStartRun({ navigateToRun: false })
  const { data: stats } = useStats()
  const busy = !!stats?.active_run
  const { data: job, isLoading, error } = useQuery({
    queryKey: ['jobs', 'detail', jobId],
    queryFn: () => api.get<Job>(`/jobs/${jobId}`),
  })
  const patch = useMutation({
    mutationFn: (body: Partial<Job>) => api.patch<Job>(`/jobs/${jobId}`, body),
    onSuccess: (j) => {
      qc.setQueryData(['jobs', 'detail', jobId], j)
      qc.invalidateQueries({ queryKey: ['jobs', 'list'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
      toast(j.email_sent ? 'Marked as applied' : 'Updated')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const action = (name: 'evaluate' | 'resume' | 'draft') => start.mutate({ kind: 'job', options: { job_id: jobId, action: name } })

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label="Job details">
      <div className="absolute inset-0 bg-zinc-900/30 dark:bg-black/50" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl dark:bg-zinc-900">
        <div className="flex items-start justify-between gap-4 border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
          {job ? (
            <div className="min-w-0">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <Badge tone={JOB_STATUS[job.status].tone}>{JOB_STATUS[job.status].label}</Badge>
                <Badge className="capitalize">{job.source}</Badge>
                {job.is_walk_in && <Badge tone="amber">Walk-in</Badge>}
                {!job.is_open && <Badge tone="red">Closed</Badge>}
              </div>
              <h2 className="text-lg font-semibold">{job.title}</h2>
              <p className="text-sm text-zinc-500 dark:text-zinc-400">{job.company}</p>
            </div>
          ) : (
            <div />
          )}
          <button onClick={onClose} className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>

        {isLoading ? (
          <div className="flex flex-1 items-center justify-center"><Spinner /></div>
        ) : error || !job ? (
          <p className="p-6 text-sm text-red-600">{(error as Error)?.message ?? 'Not found'}</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2 border-b border-zinc-200 px-6 py-3 dark:border-zinc-800">
              <a href={job.url} target="_blank" rel="noreferrer">
                <Button size="sm" icon={<ExternalLink className="size-3.5" />}>Posting</Button>
              </a>
              {job.resume_pdf && (
                <a href={`/api/jobs/${job.id}/resume.pdf`} target="_blank" rel="noreferrer">
                  <Button size="sm" icon={<FileText className="size-3.5" />}>Resume PDF</Button>
                </a>
              )}
              <Button size="sm" icon={<Wand2 className="size-3.5" />} disabled={busy} onClick={() => action('resume')}>
                {job.resume_pdf ? 'Re-tailor resume' : 'Tailor resume'}
              </Button>
              {job.contact_email && (
                <Button size="sm" icon={<Mail className="size-3.5" />} disabled={busy} onClick={() => action('draft')}>
                  {job.email_drafted ? 'Draft again' : 'Create Gmail draft'}
                </Button>
              )}
              {job.description && (
                <Button size="sm" icon={<RefreshCw className="size-3.5" />} disabled={busy} onClick={() => action('evaluate')}>Re-evaluate</Button>
              )}
              <div className="ml-auto">
                {job.email_sent ? (
                  <Button size="sm" variant="ghost" icon={<Undo2 className="size-3.5" />} loading={patch.isPending} onClick={() => patch.mutate({ email_sent: false })}>Not applied</Button>
                ) : (
                  <Button size="sm" variant="primary" icon={<Send className="size-3.5" />} loading={patch.isPending} onClick={() => patch.mutate({ email_sent: true })}>Mark applied</Button>
                )}
              </div>
              {busy && <p className="w-full text-xs text-zinc-500">A run is in progress. Actions are available when it finishes.</p>}
            </div>

            <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
                {[
                  ['Posted', formatDate(job.posted_date)],
                  ['Closes', formatDate(job.closing_date)],
                  ['Experience', job.experience_required || '–'],
                  ['Apply to', job.contact_email || 'Company website'],
                  ['Drafted', job.drafted_at ? formatDate(job.drafted_at, true) : '–'],
                  ['Found', formatDate(job.created_at)],
                ].map(([k, v]) => (
                  <div key={k} className="min-w-0">
                    <dt className="text-xs text-zinc-500 dark:text-zinc-400">{k}</dt>
                    <dd className="truncate font-medium" title={v}>{v}</dd>
                  </div>
                ))}
              </dl>

              {job.applicable !== null ? (
                <Section title="Fit">
                  <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
                    <div className="mb-2 flex items-center gap-3">
                      <ScoreBadge score={job.score} />
                      <span className="text-sm font-medium">{job.applicable ? 'Worth applying' : 'Not a good fit'}</span>
                    </div>
                    {job.reason && <p className="text-sm text-zinc-700 dark:text-zinc-300">{job.reason}</p>}
                    {!!job.matching_skills?.length && (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {job.matching_skills.map((s) => <Badge key={s} tone="green">{s}</Badge>)}
                      </div>
                    )}
                    {!!job.missing_skills?.length && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {job.missing_skills.map((s) => <Badge key={s} tone="red">{s}</Badge>)}
                      </div>
                    )}
                  </div>
                </Section>
              ) : (
                <p className="rounded-lg bg-zinc-50 p-4 text-sm text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-400">
                  {job.status === 'screened_out' ? 'Skipped by its title, so the full posting was never fetched or scored.' : 'Not evaluated yet.'}
                </p>
              )}

              {job.walk_in_address && (
                <Section title="Walk-in">
                  <p className="text-sm whitespace-pre-line">{job.walk_in_address}</p>
                </Section>
              )}
              {job.description && (
                <Section title="Description">
                  <p className="text-sm leading-relaxed whitespace-pre-line text-zinc-700 dark:text-zinc-300">{job.description}</p>
                </Section>
              )}
              {job.skills && (
                <Section title="Skills">
                  <p className="text-sm leading-relaxed whitespace-pre-line text-zinc-700 dark:text-zinc-300">{job.skills}</p>
                </Section>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
