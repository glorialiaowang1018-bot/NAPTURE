import { useContext, useState, createContext, useEffect } from 'react'
import { ApiUser, clearSession, getCurrentUser, getStoredUser, getToken, login } from './api'
import { Lang, T } from './data'
import TeacherApp from './teacher/TeacherApp'
import ParentApp from './parent/ParentApp'

type View = 'login' | 'teacher' | 'parent'
const DEMO_ACCOUNTS = {
  teacher: { phone: '13800000000', password: '123456' },
  parent: { phone: '13900000015', password: '123456' },
} as const

interface AppCtx {
  lang: Lang
  setLang: (lang: Lang) => void
  navigate: (view: View) => void
  user: ApiUser | null
  logout: () => void
}

export const AppContext = createContext<AppCtx>({
  lang: 'en',
  setLang: () => {},
  navigate: () => {},
  user: null,
  logout: () => {},
})

export const useLang = () => {
  const { lang } = useContext(AppContext)
  return T[lang]
}

export function LangToggle({ light }: { light?: boolean } = {}) {
  const { lang, setLang } = useContext(AppContext)
  return (
    <button
      onClick={() => setLang(lang === 'en' ? 'zh' : 'en')}
      className={`text-[11px] font-semibold tracking-wide px-3 py-1.5 rounded-full border transition-all ${light ? 'border-white/30 text-white/70 hover:border-white/60 hover:text-white' : 'border-[#E6E5DF] text-[#9B9B8E] hover:border-[#849F46] hover:text-[#849F46] bg-white'}`}
    >
      {lang === 'en' ? '中文' : 'EN'}
    </button>
  )
}

export function NaptureLogo({ size = 'md', light }: { size?: 'sm' | 'md' | 'lg'; light?: boolean }) {
  const cfg = {
    sm: { box: 'w-7 h-7 rounded-lg', text: 'text-sm', icon: 14 },
    md: { box: 'w-9 h-9 rounded-xl', text: 'text-base', icon: 18 },
    lg: { box: 'w-12 h-12 rounded-2xl', text: 'text-xl', icon: 22 },
  }[size]
  const color = light ? '#849F46' : 'white'
  return (
    <div className="flex items-center gap-2.5">
      <div className={`${cfg.box} ${light ? 'bg-white/20' : 'bg-[#849F46]'} flex items-center justify-center flex-shrink-0`}>
        <svg width={cfg.icon} height={cfg.icon} viewBox="0 0 24 24" fill="none">
          <path d="M5 19 L5 12 Q5 5 12 5 Q19 5 19 12 L19 19" stroke={color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          <line x1="3" y1="19" x2="21" y2="19" stroke={color} strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      </div>
      <span className={`${cfg.text} font-semibold tracking-tight ${light ? 'text-white' : 'text-[#16191A]'}`}>Napture</span>
    </div>
  )
}

function FormField({ label, type = 'text', value, onChange }: { label: string; type?: string; value: string; onChange: (value: string) => void }) {
  return (
    <div>
      <label className="block text-[11px] font-semibold text-[#5A5A52] uppercase tracking-widest mb-1.5">{label}</label>
      <input type={type} value={value} onChange={(event) => onChange(event.target.value)} className="w-full px-3.5 py-2.5 rounded-lg border border-[#E6E5DF] bg-white text-[#16191A] text-sm focus:outline-none focus:ring-2 focus:ring-[#849F46]/25 focus:border-[#849F46] transition-all" />
    </div>
  )
}

function LoginPage() {
  const { navigate, lang } = useContext(AppContext)
  const [role, setRole] = useState<'teacher' | 'parent'>('teacher')
  const [phone, setPhone] = useState(DEMO_ACCOUNTS.teacher.phone)
  const [password, setPassword] = useState(DEMO_ACCOUNTS.teacher.password)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const t = T[lang].login

  function selectRole(nextRole: 'teacher' | 'parent') {
    setRole(nextRole)
    setPhone(DEMO_ACCOUNTS[nextRole].phone)
    setPassword(DEMO_ACCOUNTS[nextRole].password)
    setError('')
  }

  async function handleLogin(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(phone.trim(), password, role)
      navigate(role)
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : lang === 'en' ? 'Sign in failed' : '登录失败，请检查账号和密码')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-full flex">
      <div className="w-[42%] bg-[#849F46] flex flex-col p-10 relative overflow-hidden flex-shrink-0">
        <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-white opacity-[0.06]" />
        <div className="absolute bottom-8 -left-16 w-56 h-56 rounded-full bg-white opacity-[0.04]" />
        <NaptureLogo size="md" light />
        <div className="flex-1 flex flex-col justify-center">
          <p className="text-white/50 text-[11px] font-semibold uppercase tracking-[0.14em] mb-4">{lang === 'en' ? 'For Kindergartens' : '幼儿园专属'}</p>
          <h2 className="text-[2.1rem] font-semibold text-white leading-[1.2] mb-4">{lang === 'en' ? <>Every Quiet<br />Moment Belongs.</> : <>每一个<br />安静时刻。</>}</h2>
          <p className="text-white/55 text-sm leading-relaxed max-w-xs">{lang === 'en' ? 'AI-powered naptime intelligence that supports children, empowers teachers, and keeps parents informed.' : 'AI 驱动的午睡智能系统，支持儿童、辅助教师、告知家长。'}</p>
        </div>
        <div className="flex items-center gap-3"><div className="flex -space-x-1.5">{['EC', 'LW', 'SL', 'EL'].map((item) => <div key={item} className="w-6 h-6 rounded-full bg-white/25 border border-white/15 flex items-center justify-center text-[8px] text-white font-semibold">{item}</div>)}</div><p className="text-white/40 text-xs">{lang === 'en' ? '10 children monitored' : '10 名儿童受监护'}</p></div>
      </div>
      <div className="flex-1 flex flex-col bg-[#F7F6F2]">
        <div className="flex justify-end p-5"><LangToggle /></div>
        <div className="flex-1 flex items-center justify-center px-12"><div className="w-full max-w-[320px]">
          <div className="mb-6"><h3 className="text-[1.6rem] font-semibold text-[#16191A] leading-tight mb-1">{lang === 'en' ? 'Sign in' : '登录账号'}</h3><p className="text-sm text-[#9B9B8E]">{lang === 'en' ? 'Choose your role to continue' : '选择身份后继续'}</p></div>
          <div className="flex bg-[#ECEAE4] rounded-xl p-1 mb-5">{(['teacher', 'parent'] as const).map((item) => <button type="button" key={item} onClick={() => selectRole(item)} className={`flex-1 py-2 rounded-lg text-sm font-semibold transition-all ${role === item ? 'bg-white text-[#16191A] shadow-sm' : 'text-[#9B9B8E] hover:text-[#16191A]'}`}>{item === 'teacher' ? (lang === 'en' ? 'Teacher' : '教师') : (lang === 'en' ? 'Parent' : '家长')}</button>)}</div>
          <form className="space-y-3" onSubmit={handleLogin}>
            <FormField label={role === 'teacher' ? (lang === 'en' ? 'Phone / Account' : '手机号 / 账号') : (lang === 'en' ? 'Phone / Email' : '手机号 / 邮箱')} value={phone} onChange={setPhone} />
            <FormField label={lang === 'en' ? 'Password' : '密码'} type="password" value={password} onChange={setPassword} />
            {error && <p className="text-xs text-red-600" role="alert">{error}</p>}
            <button disabled={busy} className="w-full py-2.5 bg-[#849F46] text-white text-sm font-semibold rounded-lg hover:bg-[#6F8C38] disabled:opacity-60 active:scale-[0.99] transition-all">{busy ? (lang === 'en' ? 'Signing in...' : '登录中...') : t.login}</button>
          </form>
          <p className="text-center text-xs text-[#C0BFB8] mt-5">{t.demo}</p>
        </div></div>
      </div>
    </div>
  )
}

export default function App() {
  const storedUser = getStoredUser()
  const [view, setView] = useState<View>(storedUser?.role ?? 'login')
  const [lang, setLang] = useState<Lang>('en')
  const [user, setUser] = useState<ApiUser | null>(storedUser)

  useEffect(() => {
    if (!getToken()) return
    getCurrentUser().then((currentUser) => {
      setUser(currentUser)
      setView(currentUser.role)
    }).catch(() => {
      clearSession()
      setUser(null)
      setView('login')
    })
  }, [])

  function navigate(viewToOpen: View) {
    setView(viewToOpen)
    if (viewToOpen === 'teacher' || viewToOpen === 'parent') setUser(getStoredUser())
  }

  function logout() {
    clearSession()
    setUser(null)
    setView('login')
  }

  return <AppContext.Provider value={{ lang, setLang, navigate, user, logout }}><div className="h-full">{view === 'login' && <LoginPage />}{view === 'teacher' && <TeacherApp />}{view === 'parent' && <ParentApp />}</div></AppContext.Provider>
}

