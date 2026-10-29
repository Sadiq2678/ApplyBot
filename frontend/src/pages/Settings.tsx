import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { NavLink, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Bot, CalendarClock, ExternalLink, FileUp, Mail, PlugZap, Trash2, User } from 'lucide-react'
import clsx from 'clsx'
import { ApiError, api, type SettingsResponse, type SettingsValues } from '../api'
import { useSettings } from '../hooks'
import { useToast } from '../components/toast'
import { Button, Card, CardHeader, Field, Input, PageHeader, Spinner, Switch, Textarea } from '../components/ui'

const SECTIONS = [
  { id: 'profile', label: 'Profile & resume', icon: User },
  { id: 'ai', label: 'AI provider', icon: Bot },
  { id: 'gmail', label: 'Gmail', icon: Mail },
  { id: 'automation', label: 'Automation', icon: CalendarClock },
]

const PROVIDERS: Record<string, { label: string; hint: ReactNode }> = {
  gemini: { label: 'Google Gemini', hint: <>Free key at <a className="underline" href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">aistudio.google.com/apikey</a></> },
  groq: { label: 'Groq', hint: <>Free key at <a className="underline" href="https://console.groq.com/keys" target="_blank" rel="noreferrer">console.groq.com/keys</a></> },
  openai: { label: 'OpenAI-compatible', hint: 'OpenAI, OpenRouter, or a local Ollama / LM Studio server' },
}

type Secrets = Partial<Record<keyof SettingsValues, string>>

export default function Settings() {
  const { section = 'profile' } = useParams()
  const { data, isLoading } = useSettings()
  if (isLoading || !data) return <div className="flex justify-center p-16"><Spinner /></div>
  return <SettingsForm data={data} section={section} />
}

function SettingsForm({ data, section }: { data: SettingsResponse; section: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [values, setValues] = useState<SettingsValues>(data.values)
  const [secrets, setSecrets] = useState<Secrets>({})
  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => setValues(data.values), [data.values])

  const changed = useMemo(() => {
    const diff: Partial<SettingsValues> = {}
    for (const k of Object.keys(values) as (keyof SettingsValues)[]) {
      if (k in data.secrets_set) continue
      if (JSON.stringify(values[k]) !== JSON.stringify(data.values[k])) Object.assign(diff, { [k]: values[k] })
    }
    return { ...diff, ...secrets }
  }, [values, secrets, data])
  const dirty = Object.keys(changed).length > 0

  const save = useMutation({
    mutationFn: () => api.put<SettingsResponse>('/settings', changed),
    onSuccess: (res) => {
      qc.setQueryData(['settings'], res)
      qc.invalidateQueries({ queryKey: ['stats'] })
      setSecrets({})
      setErrors({})
      toast('Settings saved')
    },
    onError: (e: Error) => {
      if (e instanceof ApiError && e.errors) setErrors(e.errors)
      toast(e.message, 'error')
    },
  })

  const set = <K extends keyof SettingsValues>(key: K, value: SettingsValues[K]) => setValues((v) => ({ ...v, [key]: value }))
  const props = { values, set, secrets, setSecrets, errors, data, dirty }

  return (
    <>
      <PageHeader title="Settings" description="Stored in your local database. Keys and passwords never leave this machine except to call the service they belong to." />
      <div className="grid gap-6 lg:grid-cols-[13rem_1fr]">
        <nav className="flex gap-1 overflow-x-auto lg:flex-col">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <NavLink
              key={id}
              to={`/settings/${id}`}
              className={clsx(
                'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium whitespace-nowrap',
                section === id ? 'bg-white text-zinc-900 shadow-xs ring-1 ring-zinc-200 dark:bg-zinc-900 dark:text-white dark:ring-zinc-800' : 'text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white',
              )}
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <form
          className="min-w-0 space-y-6 pb-24"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          {section === 'ai' ? <AiSection {...props} /> : section === 'gmail' ? <GmailSection {...props} /> : section === 'automation' ? <AutomationSection {...props} /> : <ProfileSection {...props} />}

          <div className={clsx('fixed inset-x-0 bottom-0 z-30 border-t border-zinc-200 bg-white/90 backdrop-blur transition-transform lg:left-60 dark:border-zinc-800 dark:bg-zinc-900/90', dirty ? 'translate-y-0' : 'translate-y-full')}>
            <div className="mx-auto flex max-w-7xl items-center justify-end gap-3 px-4 py-3 sm:px-6 lg:px-8">
              <span className="mr-auto text-sm text-zinc-600 dark:text-zinc-400">You have unsaved changes</span>
              <Button type="button" variant="ghost" onClick={() => { setValues(data.values); setSecrets({}); setErrors({}) }}>Discard</Button>
              <Button type="submit" variant="primary" loading={save.isPending}>Save changes</Button>
            </div>
          </div>
        </form>
      </div>
    </>
  )
}

interface SectionProps {
  values: SettingsValues
  set: <K extends keyof SettingsValues>(key: K, value: SettingsValues[K]) => void
  secrets: Secrets
  setSecrets: React.Dispatch<React.SetStateAction<Secrets>>
  errors: Record<string, string>
  data: SettingsResponse
  dirty: boolean
}

function SecretInput({ name, label, hint, s }: { name: keyof SettingsValues; label: string; hint?: ReactNode; s: SectionProps }) {
  const isSet = s.data.secrets_set[name]
  const value = s.secrets[name]
  const removing = value === '' && isSet
  return (
    <Field label={label} hint={removing ? 'Will be removed when you save.' : hint} error={s.errors[name]}>
      {(id) => (
        <div className="flex gap-2">
          <Input
            id={id}
            type="password"
            autoComplete="off"
            value={value ?? ''}
            placeholder={isSet && !removing ? '•••••••••••• saved' : 'Not set'}
            onChange={(e) => s.setSecrets((x) => ({ ...x, [name]: e.target.value }))}
          />
          {isSet && !removing && (
            <Button type="button" variant="ghost" aria-label={`Remove ${label}`} icon={<Trash2 className="size-4" />} onClick={() => s.setSecrets((x) => ({ ...x, [name]: '' }))} />
          )}
        </div>
      )}
    </Field>
  )
}

function TestButton({ path, label, dirty }: { path: string; label: string; dirty: boolean }) {
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>(path),
    onSuccess: setResult,
    onError: (e: Error) => setResult({ ok: false, message: e.message }),
  })
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button type="button" icon={<PlugZap className="size-4" />} loading={test.isPending} disabled={dirty} onClick={() => test.mutate()}>
        {label}
      </Button>
      {dirty ? (
        <span className="text-xs text-zinc-500">Save your changes first</span>
      ) : (
        result && <span className={clsx('text-sm', result.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>{result.message}</span>
      )}
    </div>
  )
}

function ProfileSection(s: SectionProps) {
  const { values, set, errors, data } = s
  return (
    <>
      <Card>
        <CardHeader title="About you" description="Used to sign cover letters and name the attached resume." />
        <div className="grid gap-5 p-5 sm:grid-cols-2">
          <Field label="Full name" hint="Defaults to the first line of your resume" error={errors.candidate_name}>
            {(id) => <Input id={id} value={values.candidate_name} onChange={(e) => set('candidate_name', e.target.value)} />}
          </Field>
          <Field label="Contact email" hint="Shown in cover letters; defaults to your Gmail address" error={errors.contact_email}>
            {(id) => <Input id={id} type="email" value={values.contact_email} onChange={(e) => set('contact_email', e.target.value)} />}
          </Field>
        </div>
      </Card>

      <Card>
        <CardHeader title="Resume (plain text)" description="Every job is scored against this text. Paste the full content of your resume." />
        <div className="space-y-5 p-5">
          <Field label="Resume text" error={errors.resume_text}>
            {(id) => <Textarea id={id} rows={14} value={values.resume_text} onChange={(e) => set('resume_text', e.target.value)} placeholder={'Jane Doe\nKochi, India | jane@example.com\n\nEDUCATION\n...\n\nSKILLS\n...'} />}
          </Field>
          <Field label="What are you looking for?" hint="Target role families, seniority, things to favour or avoid. The AI treats your target roles as your own field.">
            {(id) => <Textarea id={id} rows={4} value={values.preferences} onChange={(e) => set('preferences', e.target.value)} placeholder="e.g. Junior Python / backend developer roles, also QA automation and DevOps at trainee level. Avoid sales and BPO roles." />}
          </Field>
          <Switch checked={values.open_to_internships} onChange={(v) => set('open_to_internships', v)} label="Open to internships and trainee roles" description="Score intern, trainee and fresher roles leniently" />
          <Field label="Profile summary" hint="Short summary used to screen job titles quickly. Generated from your resume; edit it, or clear it to regenerate on the next scan.">
            {(id) => <Textarea id={id} rows={3} value={values.profile} onChange={(e) => set('profile', e.target.value)} />}
          </Field>
        </div>
      </Card>

      <Card>
        <CardHeader title="Resume to attach" description="A LaTeX resume is tailored to each job and compiled to a one-page PDF. Without one, the PDF below is attached unchanged." />
        <div className="space-y-5 p-5">
          {!data.system.pdflatex && (
            <p className="flex items-start gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-300">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              pdflatex is not installed here, so LaTeX resumes cannot be compiled. Run ApplyBot with Docker to get it.
            </p>
          )}
          <Field label="LaTeX resume" hint="Full source from \documentclass to \end{document}. Optional.">
            {(id) => <Textarea id={id} rows={12} spellCheck={false} className="font-mono text-xs" value={values.resume_tex} onChange={(e) => set('resume_tex', e.target.value)} />}
          </Field>
          <BasePdf hasPdf={data.system.base_pdf} />
        </div>
      </Card>
    </>
  )
}

function BasePdf({ hasPdf }: { hasPdf: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const input = useRef<HTMLInputElement>(null)
  const done = (msg: string) => {
    qc.invalidateQueries({ queryKey: ['settings'] })
    qc.invalidateQueries({ queryKey: ['stats'] })
    toast(msg)
  }
  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData()
      body.append('file', file)
      return api.post('/settings/base-pdf', body)
    },
    onSuccess: () => done('PDF uploaded'),
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const remove = useMutation({ mutationFn: () => api.del('/settings/base-pdf'), onSuccess: () => done('PDF removed') })
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed border-zinc-300 p-4 dark:border-zinc-700">
      <div>
        <p className="text-sm font-medium">Fallback PDF resume</p>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">{hasPdf ? 'Uploaded. Attached when no tailored resume can be made.' : 'Not uploaded'}</p>
      </div>
      <div className="flex gap-2">
        {hasPdf && (
          <>
            <a href="/api/settings/base-pdf" target="_blank" rel="noreferrer"><Button type="button" size="sm" icon={<ExternalLink className="size-3.5" />}>View</Button></a>
            <Button type="button" size="sm" variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>Remove</Button>
          </>
        )}
        <input ref={input} type="file" accept="application/pdf" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = '' }} />
        <Button type="button" size="sm" icon={<FileUp className="size-3.5" />} loading={upload.isPending} onClick={() => input.current?.click()}>{hasPdf ? 'Replace' : 'Upload PDF'}</Button>
      </div>
    </div>
  )
}

function AiSection(s: SectionProps) {
  const { values, set, errors, data, dirty } = s
  const p = values.llm_provider
  return (
    <Card>
      <CardHeader title="AI provider" description="Scores jobs, tailors resumes and writes cover letters." />
      <div className="space-y-5 p-5">
        <div className="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label="Provider">
          {data.options.providers.map((id) => (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={p === id}
              onClick={() => set('llm_provider', id)}
              className={clsx('rounded-lg border p-3 text-left transition-colors', p === id ? 'border-indigo-600 ring-1 ring-indigo-600 dark:border-indigo-400 dark:ring-indigo-400' : 'border-zinc-200 hover:border-zinc-300 dark:border-zinc-800 dark:hover:border-zinc-700')}
            >
              <span className="block text-sm font-medium">{PROVIDERS[id]?.label ?? id}</span>
              <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">{PROVIDERS[id]?.hint}</span>
            </button>
          ))}
        </div>

        {p === 'gemini' && (
          <div className="grid gap-5 sm:grid-cols-2">
            <SecretInput name="gemini_api_key" label="Gemini API key" s={s} />
            <Field label="Model">{(id) => <Input id={id} value={values.gemini_model} onChange={(e) => set('gemini_model', e.target.value)} />}</Field>
          </div>
        )}
        {p === 'groq' && (
          <div className="grid gap-5 sm:grid-cols-2">
            <SecretInput name="groq_api_key" label="Groq API key" s={s} />
            <Field label="Model">{(id) => <Input id={id} value={values.groq_model} onChange={(e) => set('groq_model', e.target.value)} />}</Field>
          </div>
        )}
        {p === 'openai' && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Base URL" hint="e.g. http://host.docker.internal:11434/v1 for Ollama on your machine" error={errors.openai_base_url}>
              {(id) => <Input id={id} value={values.openai_base_url} onChange={(e) => set('openai_base_url', e.target.value)} />}
            </Field>
            <Field label="Model">{(id) => <Input id={id} value={values.openai_model} onChange={(e) => set('openai_model', e.target.value)} />}</Field>
            <SecretInput name="openai_api_key" label="API key" hint="Leave empty for local servers" s={s} />
          </div>
        )}

        <Field label="Delay between AI calls (seconds)" hint="Keeps you inside free-tier rate limits. 4–6 s suits Gemini's free tier." error={errors.llm_delay}>
          {(id) => <Input id={id} type="number" min={0} max={120} step={0.5} className="w-32" value={values.llm_delay} onChange={(e) => set('llm_delay', Number(e.target.value))} />}
        </Field>
        <TestButton path="/settings/test-llm" label="Test connection" dirty={dirty} />
      </div>
    </Card>
  )
}

function GmailSection(s: SectionProps) {
  const { values, set, errors, dirty } = s
  return (
    <Card>
      <CardHeader title="Gmail" description="Applications are saved to your Drafts folder with the resume attached. Nothing is ever sent automatically." />
      <div className="space-y-5 p-5">
        <ol className="list-decimal space-y-1 rounded-lg bg-zinc-50 p-4 pl-8 text-sm text-zinc-700 dark:bg-zinc-800/50 dark:text-zinc-300">
          <li>Turn on 2-Step Verification for your Google account.</li>
          <li>Create an App Password at <a className="font-medium text-indigo-600 underline dark:text-indigo-400" href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">myaccount.google.com/apppasswords</a>.</li>
          <li>Make sure IMAP is enabled in Gmail → Settings → Forwarding and POP/IMAP.</li>
        </ol>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Gmail address" error={errors.gmail_address}>
            {(id) => <Input id={id} type="email" autoComplete="off" value={values.gmail_address} onChange={(e) => set('gmail_address', e.target.value)} />}
          </Field>
          <SecretInput name="gmail_app_password" label="App Password" hint="16 characters, not your normal password" s={s} />
        </div>
        <TestButton path="/settings/test-gmail" label="Test login" dirty={dirty} />
      </div>
    </Card>
  )
}

function AutomationSection(s: SectionProps) {
  const { values, set, errors, data } = s
  const toggleSource = (src: string, on: boolean) => set('sources', on ? [...values.sources, src] : values.sources.filter((x) => x !== src))
  return (
    <>
      <Card>
        <CardHeader title="Matching" />
        <div className="space-y-5 p-5">
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Job sites to scan</legend>
            <div className="flex flex-wrap gap-4">
              {data.options.sources.map((src) => (
                <label key={src} className="flex items-center gap-2 text-sm capitalize">
                  <input type="checkbox" className="size-4 accent-indigo-600" checked={values.sources.includes(src)} onChange={(e) => toggleSource(src, e.target.checked)} />
                  {src}
                </label>
              ))}
            </div>
            {errors.sources && <p className="mt-1 text-xs text-red-600">{errors.sources}</p>}
          </fieldset>
          <Field label="Minimum score for a match" hint="Jobs scored at or above this (0–100) get resumes and drafts." error={errors.min_score}>
            {(id) => <Input id={id} type="number" min={0} max={100} className="w-32" value={values.min_score} onChange={(e) => set('min_score', Math.round(Number(e.target.value)))} />}
          </Field>
          <Switch checked={values.reuse_resumes} onChange={(v) => set('reuse_resumes', v)} label="Reuse resumes for similar roles" description="Send an existing tailored resume when the role is the same kind, saving AI calls" />
        </div>
      </Card>
      <Card>
        <CardHeader title="Schedule" description="Run the daily pipeline automatically while ApplyBot is running." />
        <div className="space-y-5 p-5">
          <Switch checked={values.schedule_enabled} onChange={(v) => set('schedule_enabled', v)} label="Run every day" />
          <Field label="Time (24-hour, server time zone)" error={errors.schedule_time}>
            {(id) => <Input id={id} type="time" className="w-36" disabled={!values.schedule_enabled} value={values.schedule_time} onChange={(e) => set('schedule_time', e.target.value)} />}
          </Field>
        </div>
      </Card>
    </>
  )
}
