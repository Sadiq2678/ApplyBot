import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Play } from 'lucide-react'
import { Button } from './ui'
import { useStartRun, useStats } from '../hooks'

const OPTIONS = [
  { label: 'Daily run', hint: 'Scan new jobs, tailor resumes, save Gmail drafts', options: {} },
  { label: 'Dry run', hint: 'Same, but preview letters instead of saving drafts', options: { dry_run: true } },
  { label: 'Scan for new jobs', hint: 'Find and score new jobs only', options: { drafts: false } },
  { label: 'Resumes & drafts', hint: 'Prepare applications for existing matches', options: { scan: false } },
  { label: 'Full scan', hint: 'Check every listing page, not just new ones', options: { drafts: false, full_scan: true } },
  { label: 'Re-score all jobs', hint: 'Re-evaluate everything (slow, uses many LLM calls)', options: { drafts: false, full_scan: true, rescore: true } },
]

export default function RunMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const start = useStartRun()
  const { data: stats } = useStats()
  const busy = !!stats?.active_run

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  return (
    <div ref={ref} className="relative inline-flex">
      <Button
        variant="primary"
        className="rounded-r-none"
        icon={<Play className="size-4" />}
        loading={start.isPending}
        disabled={busy}
        title={busy ? 'A run is already in progress' : undefined}
        onClick={() => start.mutate({ kind: 'pipeline' })}
      >
        {busy ? 'Running…' : 'Run now'}
      </Button>
      <Button
        variant="primary"
        className="rounded-l-none border-l border-indigo-400/50 px-2"
        disabled={busy}
        aria-label="More run options"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <ChevronDown className="size-4" />
      </Button>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-30 mt-1 w-80 overflow-hidden rounded-lg border border-zinc-200 bg-white py-1 shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
          {OPTIONS.map((o) => (
            <button
              key={o.label}
              role="menuitem"
              className="block w-full px-3 py-2 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800"
              onClick={() => {
                setOpen(false)
                start.mutate({ kind: 'pipeline', options: o.options })
              }}
            >
              <span className="block text-sm font-medium">{o.label}</span>
              <span className="block text-xs text-zinc-500 dark:text-zinc-400">{o.hint}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
