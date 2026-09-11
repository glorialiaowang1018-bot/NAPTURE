export type UserRole = 'teacher' | 'parent'

export interface ApiUser {
  id: string
  phone: string
  name: string
  role: UserRole
  child_id?: string | null
  child_name?: string | null
}

export interface AuthResponse {
  status: string
  token: string
  user: ApiUser
}

const TOKEN_KEY = 'nap_app_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem('nap_app_user')
}

export function getStoredUser(): ApiUser | null {
  const value = localStorage.getItem('nap_app_user')
  if (!value) return null
  try {
    return JSON.parse(value) as ApiUser
  } catch {
    clearSession()
    return null
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(path, { ...options, headers })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = typeof body?.msg === 'string' ? body.msg : `Request failed (${response.status})`
    if (response.status === 401) clearSession()
    throw new Error(message)
  }
  return body as T
}

export async function login(phone: string, password: string, role: UserRole): Promise<AuthResponse> {
  const result = await api<AuthResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ phone, password, role }),
  })
  localStorage.setItem(TOKEN_KEY, result.token)
  localStorage.setItem('nap_app_user', JSON.stringify(result.user))
  return result
}

export async function getCurrentUser(): Promise<ApiUser> {
  const result = await api<{ user: ApiUser }>('/api/auth/me')
  localStorage.setItem('nap_app_user', JSON.stringify(result.user))
  return result.user
}

export type InterventionAction = 'game' | 'story' | 'light' | 'white_noise'

export interface InterventionPlan {
  id: string
  execution_status?: string
  status?: string
  proposed_action?: { type?: string; label?: string }
  final_action?: { type?: string; label?: string }
}

export async function createManualIntervention(childId: string, actionType: InterventionAction): Promise<{ plan: InterventionPlan }> {
  return api(`/api/children/${childId}/interventions`, {
    method: 'POST',
    body: JSON.stringify({ action_type: actionType, param: 'manual' }),
  })
}

export async function cancelIntervention(planId: string): Promise<void> {
  await api(`/api/interventions/${planId}/cancel`, { method: 'POST' })
}

export async function overrideIntervention(planId: string, actionType: InterventionAction): Promise<{ plan: InterventionPlan }> {
  return api(`/api/interventions/${planId}/override`, {
    method: 'POST',
    body: JSON.stringify({ action_type: actionType, param: 'manual' }),
  })
}

export async function stopIntervention(planId: string): Promise<void> {
  await api(`/api/interventions/${planId}/stop`, { method: 'POST' })
}

export function subscribeToEvents(onEvent: (event: { type: string; payload: unknown }) => void): () => void {
  const source = new EventSource('/api/events')
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data))
    } catch {
      // Ignore malformed event payloads and keep the stream alive.
    }
  }
  return () => source.close()
}
