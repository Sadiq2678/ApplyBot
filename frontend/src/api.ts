// Typed client for the FastAPI backend (app/main.py).

export class ApiError extends Error {
  status: number
  errors?: Record<string, string>
  constructor(status: number, message: string, errors?: Record<string, string>) {
    super(message)
    this.status = status
    this.errors = errors
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const res = await fetch(`/api${path}`, init)
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : null
  if (!res.ok) {
    const errors = data?.errors
    const message =
      data?.message ??
      (errors ? Object.values(errors).join('. ') : null) ??
      (typeof data?.detail === 'string' ? data.detail : null) ??
      `Request failed (${res.status})`
    throw new ApiError(res.status, message, errors)
  }
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
}

export type JobStatus = 'match' | 'drafted' | 'applied' | 'not_fit' | 'screened_out' | 'pending'

export interface JobSummary {
  id: number
  title: string
  company: string | null
  source: string
  contact_email: string | null
  posted_date: string | null
  closing_date: string | null
  score: number | null
  applicable: boolean | null
  url: string
  is_walk_in: boolean | null
  created_at: string
  resume_file: string | null
  is_open: boolean
  status: JobStatus
}

export interface Job extends JobSummary {
  job_listing_id: string | null
  company_website: string | null
  walk_in_address: string | null
  description: string | null
  skills: string | null
  experience_required: string | null
  matching_skills: string[] | null
  missing_skills: string[] | null
  reason: string | null
  email_sent: boolean
  email_drafted: boolean | null
  drafted_at: string | null
  sent_at: string | null
  resume_pdf: string | null
}

export interface Draft {
  to: string
  subject: string
  body: string
  attachment: string | null
  sent: boolean
  sent_at: string | null
}

export interface Stats {
  total: number
  matches: number
  manual: number
  drafted: number
  applied: number
  new_week: number
  last_new: string | null
  setup: { resume: boolean; llm: boolean; attachment: boolean; gmail: boolean }
  schedule: { enabled: boolean; time: string }
  min_score: number
  active_run: number | null
}

export type RunStatus = 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface Run {
  id: number
  kind: 'pipeline' | 'job'
  options: Record<string, unknown>
  trigger: string
  status: RunStatus
  summary: string | null
  started_at: string
  finished_at: string | null
  log?: string
}

export interface SettingsValues {
  candidate_name: string
  contact_email: string
  resume_text: string
  resume_tex: string
  profile: string
  preferences: string
  open_to_internships: boolean
  llm_provider: string
  gemini_api_key: string
  gemini_model: string
  groq_api_key: string
  groq_model: string
  openai_base_url: string
  openai_api_key: string
  openai_model: string
  llm_delay: number
  gmail_address: string
  gmail_app_password: string
  sources: string[]
  min_score: number
  reuse_resumes: boolean
  schedule_enabled: boolean
  schedule_time: string
}

export interface SettingsResponse {
  values: SettingsValues
  secrets_set: Record<string, boolean>
  options: { providers: string[]; sources: string[] }
  system: { pdflatex: boolean; base_pdf: boolean; auth: boolean }
}

export function runLabel(run: Pick<Run, 'kind' | 'options'>): string {
  const o = run.options
  if (run.kind === 'job') {
    const action = { evaluate: 'Re-evaluate', resume: 'Tailor resume', draft: 'Create draft' }[
      String(o.action)
    ]
    return `${action ?? 'Job'} · #${o.job_id}`
  }
  if (o.scan === false) return 'Resumes & drafts'
  if (o.drafts === false) return o.rescore ? 'Re-score jobs' : 'Scan for jobs'
  return o.dry_run ? 'Daily run (dry run)' : 'Daily run'
}
