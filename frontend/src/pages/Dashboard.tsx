import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Briefcase, CheckCircle2, Circle, Inbox, Mail, MousePointerClick, Send, Sparkles } from 'lucide-react'
import clsx from 'clsx'
import { api, runLabel, type JobSummary } from '../api'
import { useRuns, useStats } from '../hooks'
import RunMenu from '../components/RunMenu'
import { Badge, Card, CardHeader, EmptyState, PageHeader, RUN_STATUS, ScoreBadge, Spinner, formatDate, timeAgo } from '../components/ui'

const SETUP_STEPS = [
  { key: 'resume', label: 'Add your resume', hint: 'Plain-text resume used to score every job', to: '/settings/profile' },
  { key: 'llm', label: 'Connect an AI provider', hint: 'Free Gemini or Groq keys work fine', to: '/settings/ai' },
  { key: 'attachment', label: 'Add a resume to attach', hint: 'A LaTeX resume to tailor, or a PDF to send as-is', to: '/settings/profile' },
  { key: 'gmail', label: 'Connect Gmail', hint: 'Applications are saved as drafts, never sent', to: '/settings/gmail' },
] as const

function Stat({ label, value, icon, to, hint }: { label: string; value: number | undefined; icon: React.ReactNode; to: string; hint?: string }) {
  return (
    <Link to={to} className="group">
      <Card className="p-5 transition-shadow group-hover:shadow-md">
        <div className="flex items-center justify-between text-zinc-500 dark:text-zinc-400">
          <span className="text-sm font-medium">{label}</span>
          {icon}
        </div>
        <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums">{value ?? '–'}</p>
        {hint && <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>}
      </Card>
    </Link>
  )
}

export default function Dashboard() {
  const { data: stats } = useStats()
  const { data: runs } = useRuns(6)
  const { data: top, isLoading } = useQuery({
    queryKey: ['jobs', 'top', stats?.total],
    queryFn: () => api.get<{ items: JobSummary[] }>('/jobs?status=match&limit=6'),
  })
  const setup = stats?.setup
  const setupDone = setup ? Object.values(setup).filter(Boolean).length : 0
  const setupComplete = setupDone === SETUP_STEPS.length

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={stats ? `${stats.total} jobs tracked · last new job ${timeAgo(stats.last_new)}` : ' '}
        actions={<RunMenu />}
      />

      {setup && !setupComplete && (
        <Card className="mb-6">
          <CardHeader
            title="Finish setting up"
            description={`${setupDone} of ${SETUP_STEPS.length} done. Everything stays on this machine.`}
          />
          <ul className="grid gap-px bg-zinc-200 sm:grid-cols-2 lg:grid-cols-4 dark:bg-zinc-800">
            {SETUP_STEPS.map((s) => {
              const done = setup[s.key]
              return (
                <li key={s.key} className="bg-white dark:bg-zinc-900">
                  <Link to={s.to} className="flex h-full gap-3 p-4 hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                    {done ? (
                      <CheckCircle2 className="size-5 shrink-0 text-emerald-600" />
                    ) : (
                      <Circle className="size-5 shrink-0 text-zinc-300 dark:text-zinc-600" />
                    )}
                    <div>
                      <p className={clsx('text-sm font-medium', done && 'text-zinc-500 line-through')}>{s.label}</p>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">{s.hint}</p>
                    </div>
                  </Link>
                </li>
              )
            })}
          </ul>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Open matches" value={stats?.matches} icon={<Sparkles className="size-4" />} to="/jobs?status=match" hint={`Score ≥ ${stats?.min_score ?? 60}`} />
        <Stat label="Apply on site" value={stats?.manual} icon={<MousePointerClick className="size-4" />} to="/jobs?status=match" hint="Matches with no email" />
        <Stat label="Drafts ready" value={stats?.drafted} icon={<Mail className="size-4" />} to="/jobs?status=drafted" hint="Review & send in Gmail" />
        <Stat label="Applied" value={stats?.applied} icon={<Send className="size-4" />} to="/jobs?status=applied&open_only=false" />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Top matches"
            action={
              <Link to="/jobs" className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-400">
                All jobs <ArrowRight className="size-4" />
              </Link>
            }
          />
          {isLoading ? (
            <div className="flex justify-center p-10"><Spinner /></div>
          ) : !top?.items.length ? (
            <EmptyState icon={<Briefcase className="size-5" />} title="No open matches yet" description="Start a run to scan Technopark and Infopark for jobs that fit your resume." />
          ) : (
            <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {top.items.map((j) => (
                <li key={j.id}>
                  <Link to={`/jobs/${j.id}?status=match`} className="flex items-center gap-4 px-5 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                    <ScoreBadge score={j.score} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{j.title}</p>
                      <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">{j.company}</p>
                    </div>
                    <span className="hidden text-xs text-zinc-500 sm:block">closes {formatDate(j.closing_date)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Recent runs"
            action={
              <Link to="/runs" className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-400">
                History <ArrowRight className="size-4" />
              </Link>
            }
          />
          {!runs?.length ? (
            <EmptyState icon={<Inbox className="size-5" />} title="No runs yet" />
          ) : (
            <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {runs.map((r) => (
                <li key={r.id}>
                  <Link to={`/runs/${r.id}`} className="block px-5 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{runLabel(r)}</span>
                      <Badge tone={RUN_STATUS[r.status].tone}>{RUN_STATUS[r.status].label}</Badge>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-zinc-500 dark:text-zinc-400">
                      {timeAgo(r.started_at)}
                      {r.summary && ` · ${r.summary}`}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  )
}
