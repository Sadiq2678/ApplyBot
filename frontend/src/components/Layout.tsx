import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Briefcase, LayoutDashboard, Loader2, Menu, ScrollText, Settings, X } from 'lucide-react'
import clsx from 'clsx'
import { useStats } from '../hooks'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/jobs', label: 'Jobs', icon: Briefcase },
  { to: '/runs', label: 'Runs', icon: ScrollText },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <img src="/favicon.svg" alt="" className="size-7" />
      <span className="text-base font-semibold tracking-tight">ApplyBot</span>
    </Link>
  )
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const { data: stats } = useStats()
  return (
    <nav className="flex flex-1 flex-col gap-1">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            clsx(
              'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
              isActive
                ? 'bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-white'
                : 'text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/50 dark:hover:text-white',
            )
          }
        >
          <Icon className="size-4" />
          {label}
          {to === '/jobs' && !!stats?.matches && (
            <span className="ml-auto rounded-full bg-indigo-100 px-2 text-xs font-semibold text-indigo-700 tabular-nums dark:bg-indigo-950 dark:text-indigo-300">
              {stats.matches}
            </span>
          )}
        </NavLink>
      ))}
      <div className="mt-auto">
        {stats?.active_run ? (
          <Link
            to={`/runs/${stats.active_run}`}
            onClick={onNavigate}
            className="flex items-center gap-2 rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-xs font-medium text-sky-800 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-300"
          >
            <Loader2 className="size-3.5 animate-spin" />
            Run #{stats.active_run} in progress
          </Link>
        ) : (
          stats?.schedule.enabled && (
            <p className="px-3 text-xs text-zinc-500">Daily run scheduled at {stats.schedule.time}</p>
          )
        )}
      </div>
    </nav>
  )
}

export default function Layout() {
  const [open, setOpen] = useState(false)
  const location = useLocation()

  return (
    <div className="flex min-h-full">
      <aside className="hidden w-60 shrink-0 flex-col gap-6 border-r border-zinc-200 bg-white px-4 py-5 lg:flex dark:border-zinc-800 dark:bg-zinc-900">
        <Logo />
        <Nav />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-zinc-900/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col gap-6 bg-white px-4 py-5 shadow-xl dark:bg-zinc-900">
            <div className="flex items-center justify-between">
              <Logo />
              <button onClick={() => setOpen(false)} aria-label="Close menu" className="p-1 text-zinc-500">
                <X className="size-5" />
              </button>
            </div>
            <Nav onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-zinc-200 bg-white/80 px-4 backdrop-blur lg:hidden dark:border-zinc-800 dark:bg-zinc-900/80">
          <button onClick={() => setOpen(true)} aria-label="Open menu" className="p-1 text-zinc-600 dark:text-zinc-300">
            <Menu className="size-5" />
          </button>
          <Logo />
        </header>
        <main key={location.pathname.split('/')[1]} className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
