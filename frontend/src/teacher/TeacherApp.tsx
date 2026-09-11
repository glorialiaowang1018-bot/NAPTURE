import { useState, useContext, useEffect } from 'react'
import { AppContext, LangToggle, NaptureLogo } from '../App'
import { CHILDREN, NAP_REPORT, STATE_CONFIG, T, Child, NapState } from '../data'
import { api, cancelIntervention, createManualIntervention, InterventionAction, overrideIntervention, stopIntervention, subscribeToEvents } from '../api'

type TeacherView = 'overview' | 'child-detail' | 'reports' | 'children' | 'history' | 'settings'

type BackendChild = {
  id: string
  name?: string
  current_state?: string
  emotion?: string
  sleep_duration_seconds?: number | null
  environment?: Record<string, string | number>
  motion_frequency?: string | number | null
  pending_intervention?: { id?: string; label?: string }
  latest_execution?: { plan_id?: string; action?: { label?: string; type?: string } }
}

function mapBackendChild(child: BackendChild, index: number): Child {
  const stateMap: Record<string, NapState> = {
    sleeping: 'nappers', sleepy: 'transitioners', need_help: 'resters', calm_awake: 'active-awake', alarm: 'risk', unknown: 'resters',
  }
  const state = stateMap[child.current_state || 'unknown'] || 'resters'
  const name = child.name || `Child ${index + 1}`
  const initials = name.slice(0, 2)
  const duration = Math.max(0, Math.round((child.sleep_duration_seconds || 0) / 60))
  const action = child.pending_intervention?.label || child.latest_execution?.action?.label || 'No Active Feedback'
  const environment = child.environment || {}
  return {
    id: child.id,
    name,
    nameZh: name,
    initials,
    avatarBg: STATE_CONFIG[state].color,
    state,
    timeInState: duration,
    aiFeedback: action,
    aiFeedbackZh: action,
    hasAlert: state === 'risk',
    sensors: {
      respiratory: String(environment.breath_rate || 'Normal'),
      movement: String(child.motion_frequency || 'Still'),
      temperature: String(environment.temperature || 'Normal'),
      sound: String(environment.noise || 'Quiet'),
    },
    stateHistory: [{ state, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), duration: Math.max(duration, 1) }],
    position: { row: Math.floor(index / 4), col: index % 4 },
    pendingPlanId: child.pending_intervention?.id,
    activePlanId: child.latest_execution?.plan_id,
  }
}

export default function TeacherApp() {
  const { lang, logout } = useContext(AppContext)
  const t = T[lang].teacher
  const [view, setView] = useState<TeacherView>('overview')
  const [activeNav, setActiveNav] = useState('overview')
  const [selectedChild, setSelectedChild] = useState<Child | null>(null)
  const [showIntervention, setShowIntervention] = useState(false)
  const [showAlert, setShowAlert] = useState(true)
  const [reportPublished, setReportPublished] = useState(false)
  const [publishing, setPublishing] = useState(false)

  useEffect(() => {
    let cancelled = false
    const refresh = async () => {
      try {
        const result = await api<{ children: BackendChild[] }>('/api/teacher/class-overview')
        if (cancelled || !result.children?.length) return
        CHILDREN.splice(0, CHILDREN.length, ...result.children.map(mapBackendChild))
        setSelectedChild((current) => current ? CHILDREN.find((child) => child.id === current.id) || null : current)
        setReportPublished(false)
      } catch {
        // The bundled sample data keeps the new UI usable while Flask is offline.
      }
    }
    api('/api/runtime/start', { method: 'POST' }).catch(() => {})
    refresh()
    const unsubscribe = subscribeToEvents(() => refresh())
    const heartbeat = window.setInterval(() => { api('/api/runtime/heartbeat', { method: 'POST' }).catch(() => {}) }, 5000)
    return () => { cancelled = true; unsubscribe(); window.clearInterval(heartbeat) }
  }, [])

  const alertChild = CHILDREN.find(c => c.hasAlert)!
  const interventionChild = CHILDREN[1]

  function navTo(nav: string) {
    setActiveNav(nav)
    setSelectedChild(null)
    if (nav === 'overview') setView('overview')
    else if (nav === 'children') setView('children')
    else if (nav === 'reports') setView('reports')
    else if (nav === 'history') setView('history')
    else if (nav === 'settings') setView('settings')
  }

  async function publishAllReports() {
    setPublishing(true)
    try {
      await api('/api/teacher/publish-all-reports', { method: 'POST' })
      setReportPublished(true)
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div className="h-full flex" style={{ fontFamily: "'Outfit', sans-serif" }}>
      {/* Sidebar */}
      <aside className="w-[200px] flex-shrink-0 bg-white border-r border-[#ECEAE4] flex flex-col">
        <div className="h-14 px-5 flex items-center border-b border-[#ECEAE4]">
          <NaptureLogo size="sm" />
        </div>
        <nav className="flex-1 p-2.5 space-y-0.5">
          {[
            { key: 'overview', icon: GridIcon,    label: t.nav.overview },
            { key: 'children', icon: UsersIcon,   label: t.nav.children },
            { key: 'reports',  icon: FileIcon,    label: t.nav.reports },
            { key: 'history',  icon: ClockIcon,   label: t.nav.history },
            { key: 'settings', icon: SettingsIcon,label: t.nav.settings },
          ].map(({ key, icon: Icon, label }) => (
            <button key={key} onClick={() => navTo(key)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                activeNav === key ? 'bg-[#EDF2E4] text-[#849F46]' : 'text-[#8A8A80] hover:bg-[#F7F6F2] hover:text-[#16191A]'
              }`}
            >
              <Icon active={activeNav === key} />
              {label}
            </button>
          ))}
        </nav>
        <div className="p-4 border-t border-[#ECEAE4]">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-full bg-[#849F46] flex items-center justify-center text-white text-[10px] font-bold">SW</div>
            <div>
              <p className="text-xs font-semibold text-[#16191A]">Ms. Sarah</p>
              <p className="text-[10px] text-[#A8A79E]">Lead Teacher</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0 bg-[#F7F6F2]">
        {/* Top bar */}
        <header className="h-14 bg-white border-b border-[#ECEAE4] flex items-center justify-between px-6 flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-[#16191A]">{t.overview.class}</span>
            <span className="text-[#D0CFC8]">·</span>
            <span className="text-sm text-[#9B9B8E]">{t.overview.napStarted}</span>
            <span className="text-[#D0CFC8]">·</span>
            <span className="text-sm font-mono text-[#16191A]">13:07</span>
          </div>
          <div className="flex items-center gap-2.5">
            <div className="flex items-center gap-1.5 mr-1">
              {(Object.entries(STATE_CONFIG) as [NapState, typeof STATE_CONFIG['nappers']][]).map(([key, cfg]) => {
                const count = CHILDREN.filter(c => c.state === key).length
                if (!count) return null
                return (
                  <div key={key} className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold" style={{ background: cfg.bg, color: cfg.text }}>
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: cfg.color }} />
                    {count}
                  </div>
                )
              })}
            </div>
            <button onClick={() => setShowAlert(true)}
              className="relative w-8 h-8 rounded-lg flex items-center justify-center text-[#8A8A80] hover:bg-[#F7F6F2] transition-colors"
            >
              <BellIcon />
              <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-[#EF4444] rounded-full" />
            </button>
            <button onClick={() => setShowIntervention(true)}
              className="text-[11px] font-semibold px-3 py-1.5 bg-[#849F46] text-white rounded-lg hover:bg-[#6F8C38] transition-colors"
            >
              {lang === 'en' ? '● AI Pending' : '● AI 待触发'}
            </button>
            <LangToggle />
            <button onClick={logout} className="text-[11px] font-semibold text-[#8A8A80] hover:text-[#EF4444]">{lang === 'en' ? 'Sign out' : '退出'}</button>
          </div>
        </header>

        {/* Page content */}
        <div className="flex-1 overflow-auto">
          {view === 'overview' && (
            <ClassroomOverview lang={lang} t={t}
              onChildClick={(c) => { setSelectedChild(c); setView('child-detail') }}
            />
          )}
          {view === 'child-detail' && selectedChild && (
            <ChildDetail child={selectedChild} lang={lang} t={t}
              onBack={() => { setView('overview'); setSelectedChild(null) }}
              onIntervention={() => setShowIntervention(true)}
            />
          )}
          {view === 'children' && (
            <ChildrenListView lang={lang} t={t}
              onChildClick={(c) => { setSelectedChild(c); setView('child-detail') }}
            />
          )}
          {view === 'reports' && (
            <ClassReportView lang={lang} t={t} published={reportPublished} publishing={publishing} onPublish={publishAllReports} />
          )}
          {view === 'history' && <HistoryListView lang={lang} />}
          {view === 'settings' && <SettingsView lang={lang} />}
        </div>
      </div>

      {showIntervention && (
        <InterventionModal lang={lang} t={t} child={interventionChild} onClose={() => setShowIntervention(false)} />
      )}
      {showAlert && (
        <AlertModal lang={lang} t={t} child={alertChild}
          onClose={() => setShowAlert(false)}
          onViewDetail={() => { setShowAlert(false); setSelectedChild(alertChild); setView('child-detail') }}
        />
      )}
    </div>
  )
}

// ── Classroom Overview ──────────────────────────────────────────────────────
function ClassroomOverview({ lang, t, onChildClick }: { lang: string; t: typeof T['en']['teacher']; onChildClick: (c: Child) => void }) {
  return (
    <div className="p-6">
      <div className="flex items-baseline justify-between mb-5">
        <div>
          <h1 className="text-lg font-semibold text-[#16191A]">{t.overview.title}</h1>
          <p className="text-xs text-[#9B9B8E] mt-0.5">
            {CHILDREN.length} {lang === 'en' ? 'children' : '名儿童'} &nbsp;·&nbsp; {lang === 'en' ? 'Drag cards to rearrange beds' : '可拖拽排列床位'}
          </p>
        </div>
        <button className="text-xs font-medium text-[#849F46] hover:underline">{t.overview.saveLayout}</button>
      </div>

      <div className="bg-white rounded-xl border border-[#ECEAE4]">
        <div className="flex items-center px-5 pt-4 pb-3 border-b border-[#F2F1EC]">
          <span className="text-[10px] font-semibold text-[#C0BFB8] uppercase tracking-[0.12em]">
            {lang === 'en' ? 'Classroom Floor Plan — Sunflower Class' : '教室平面图 — 向日葵班'}
          </span>
        </div>

        <div className="p-4">
          <div className="flex gap-1 mb-3 items-center">
            <div className="w-16 h-1.5 rounded-full bg-[#E8F0D6]" />
            <div className="flex-1 h-px bg-[#ECEAE4]" />
            <div className="w-16 h-1.5 rounded-full bg-[#E8F0D6]" />
            <p className="text-[9px] text-[#C0BFB8] ml-2">{lang === 'en' ? 'Windows' : '窗户'}</p>
          </div>

          <div className="grid grid-cols-5 gap-2.5">
            {CHILDREN.map(child => (
              <ChildCard key={child.id} child={child} lang={lang} onClick={onChildClick} />
            ))}
            <EmptyBed lang={lang} />
            <EmptyBed lang={lang} />
          </div>

          <div className="flex gap-1 mt-3 items-center">
            <div className="flex-1 h-px bg-[#ECEAE4]" />
            <p className="text-[9px] text-[#C0BFB8] mr-2">{lang === 'en' ? 'Door' : '门'}</p>
            <div className="w-12 h-1.5 rounded-full bg-[#ECEAE4]" />
            <div className="flex-1 h-px bg-[#ECEAE4]" />
          </div>
        </div>
      </div>
    </div>
  )
}

function ChildCard({ child, lang, onClick }: { child: Child; lang: string; onClick: (c: Child) => void }) {
  const cfg = STATE_CONFIG[child.state]
  return (
    <button onClick={() => onClick(child)}
      className={`relative bg-white text-left rounded-xl transition-all hover:-translate-y-0.5 overflow-hidden group ${
        child.hasAlert
          ? 'border-2 border-[#EF4444] shadow-sm shadow-red-100'
          : 'border border-[#ECEAE4] hover:border-[#849F46] hover:shadow-sm'
      }`}
    >
      <div className="h-[3px] w-full" style={{ background: cfg.color }} />
      <div className="p-3">
        <div className="flex items-center justify-between mb-2.5">
          <span className="text-[9px] font-semibold uppercase tracking-[0.08em]" style={{ color: cfg.color }}>
            {lang === 'en' ? cfg.label : cfg.labelZh}
          </span>
          {child.hasAlert && <span className="w-1.5 h-1.5 rounded-full bg-[#EF4444] animate-pulse" />}
        </div>
        <div className="flex flex-col items-center text-center mb-2.5">
          <div className="w-9 h-9 rounded-full flex items-center justify-center text-white text-xs font-bold mb-1.5" style={{ background: cfg.color }}>
            {child.initials}
          </div>
          <p className="text-[12px] font-semibold text-[#16191A] leading-tight">
            {lang === 'en' ? child.name.split(' ')[0] : child.nameZh}
          </p>
          <p className="text-[10px] text-[#A8A79E] mt-0.5">{child.timeInState} min</p>
        </div>
        <div className="text-[9px] text-[#A8A79E] text-center leading-tight truncate">
          {lang === 'en' ? child.aiFeedback : child.aiFeedbackZh}
        </div>
      </div>
    </button>
  )
}

function EmptyBed({ lang }: { lang: string }) {
  return (
    <div className="border border-dashed border-[#E6E5DF] rounded-xl flex items-center justify-center" style={{ minHeight: '130px' }}>
      <span className="text-[10px] text-[#D0CFC8]">{lang === 'en' ? 'Empty' : '空位'}</span>
    </div>
  )
}

// ── Children List ──────────────────────────────────────────────────────────
function ChildrenListView({ lang, t, onChildClick }: { lang: string; t: typeof T['en']['teacher']; onChildClick: (c: Child) => void }) {
  return (
    <div className="p-6">
      <div className="mb-5">
        <h1 className="text-lg font-semibold text-[#16191A]">{t.nav.children}</h1>
        <p className="text-xs text-[#9B9B8E] mt-0.5">{CHILDREN.length} {lang === 'en' ? 'children enrolled' : '名在班儿童'}</p>
      </div>
      <div className="bg-white rounded-xl border border-[#ECEAE4] overflow-hidden">
        <div className="grid grid-cols-[2fr_1fr_1fr_1fr_32px] px-5 py-3 border-b border-[#F2F1EC]">
          {[
            lang === 'en' ? 'Child' : '儿童',
            lang === 'en' ? 'State' : '状态',
            lang === 'en' ? 'Duration' : '时长',
            lang === 'en' ? 'Signals' : '信号',
            '',
          ].map((h, i) => (
            <span key={i} className="text-[10px] font-semibold text-[#A8A79E] uppercase tracking-widest">{h}</span>
          ))}
        </div>
        {CHILDREN.map((child, i) => {
          const cfg = STATE_CONFIG[child.state]
          const hasAnyAlert = child.hasAlert || ['Elevated', 'Active', 'Crying', 'High'].some(v => Object.values(child.sensors).includes(v))
          return (
            <button key={child.id} onClick={() => onChildClick(child)}
              className={`w-full grid grid-cols-[2fr_1fr_1fr_1fr_32px] items-center px-5 py-3.5 text-left hover:bg-[#F7F6F2] transition-colors ${
                i < CHILDREN.length - 1 ? 'border-b border-[#F2F1EC]' : ''
              } ${child.hasAlert ? 'bg-[#FFF8F8]' : ''}`}
            >
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0" style={{ background: cfg.color }}>
                  {child.initials}
                </div>
                <span className="text-sm font-medium text-[#16191A]">{lang === 'en' ? child.name : child.nameZh}</span>
              </div>
              <div>
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: cfg.bg, color: cfg.text }}>
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: cfg.color }} />
                  {lang === 'en' ? cfg.label : cfg.labelZh}
                </span>
              </div>
              <span className="font-mono text-xs text-[#9B9B8E]">{child.timeInState} min</span>
              <span className={`text-xs font-semibold ${hasAnyAlert ? 'text-[#EF4444]' : 'text-[#849F46]'}`}>
                {hasAnyAlert ? (lang === 'en' ? '⚠ Alert' : '⚠ 警报') : (lang === 'en' ? '✓ OK' : '✓ 正常')}
              </span>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="text-[#D0CFC8]">
                <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Class Report ──────────────────────────────────────────────────────────
function ClassReportView({ lang, t, published, publishing, onPublish }: { lang: string; t: typeof T['en']['teacher']; published: boolean; publishing: boolean; onPublish: () => void }) {
  const nappers = CHILDREN.filter(c => c.state === 'nappers').length
  const settling = CHILDREN.filter(c => ['transitioners', 'resters'].includes(c.state)).length
  const alerts = CHILDREN.filter(c => c.hasAlert).length

  return (
    <div className="p-6">
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-xl font-semibold text-[#16191A]">
            {lang === 'en' ? 'Class Nap Report' : '班级午睡报告'}
          </h1>
          <p className="text-xs text-[#9B9B8E] mt-0.5">
            {lang === 'en' ? 'Sunflower Class · Friday, August 29' : '向日葵班 · 2026年8月29日 周五'}
          </p>
        </div>
        {!published ? (
          <button onClick={onPublish} disabled={publishing}
            className="px-4 py-2 rounded-lg bg-[#849F46] text-white text-xs font-semibold hover:bg-[#6F8C38] transition-colors flex items-center gap-1.5"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
              <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            {publishing ? (lang === 'en' ? 'Publishing...' : '发布中...') : (lang === 'en' ? 'Publish All Reports' : '发布全部报告')}
          </button>
        ) : (
          <div className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-[#E8F0D6] text-[#3D5A1A] text-xs font-semibold">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
            {lang === 'en' ? 'Published to All Parents' : '已发布给所有家长'}
          </div>
        )}
      </div>

      {/* Class stats */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        {[
          { label: lang === 'en' ? 'Total' : '总人数', val: `${CHILDREN.length}`, color: '#849F46' },
          { label: lang === 'en' ? 'Sleeping' : '睡眠中', val: `${nappers}`, color: '#849F46' },
          { label: lang === 'en' ? 'Settling' : '过渡中', val: `${settling}`, color: '#B58FD4' },
          { label: lang === 'en' ? 'Alerts' : '警报', val: `${alerts}`, color: alerts > 0 ? '#EF4444' : '#A8A79E' },
        ].map(({ label, val, color }) => (
          <div key={label} className="bg-white rounded-xl border border-[#ECEAE4] px-4 py-3.5">
            <p className="text-[10px] text-[#A8A79E] uppercase tracking-wide mb-1.5">{label}</p>
            <p className="text-2xl font-semibold" style={{ color }}>{val}</p>
          </div>
        ))}
      </div>

      {/* Individual reports */}
      <div className="bg-white rounded-xl border border-[#ECEAE4] overflow-hidden">
        <div className="px-5 py-3 border-b border-[#F2F1EC]">
          <p className="text-[10px] font-semibold text-[#A8A79E] uppercase tracking-widest">
            {lang === 'en' ? 'Individual Reports' : '个人报告'}
          </p>
        </div>
        {CHILDREN.map((child, i) => {
          const cfg = STATE_CONFIG[child.state]
          const totalTime = child.stateHistory.reduce((s, h) => s + h.duration, 0)
          return (
            <div key={child.id} className={`px-5 py-4 ${i < CHILDREN.length - 1 ? 'border-b border-[#F2F1EC]' : ''} ${child.hasAlert ? 'bg-[#FFF8F8]' : ''}`}>
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0" style={{ background: cfg.color }}>
                  {child.initials}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-sm font-semibold text-[#16191A]">{lang === 'en' ? child.name : child.nameZh}</span>
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full" style={{ background: cfg.bg, color: cfg.text }}>
                      {lang === 'en' ? cfg.label : cfg.labelZh}
                    </span>
                    {child.hasAlert && <span className="text-[10px] font-semibold text-[#EF4444]">⚠</span>}
                  </div>
                  <div className="flex h-2 rounded-full overflow-hidden w-44 mb-1">
                    {child.stateHistory.map((h, j) => (
                      <div key={j} style={{ width: `${(h.duration / totalTime) * 100}%`, background: STATE_CONFIG[h.state].color }} />
                    ))}
                  </div>
                  <div className="flex gap-2 text-[10px] text-[#A8A79E]">
                    <span className="font-mono">{child.stateHistory[0]?.time}</span>
                    <span>·</span>
                    <span>{totalTime} min</span>
                    {child.aiFeedback !== 'No Active Feedback' && (
                      <>
                        <span>·</span>
                        <span className="text-[#849F46]">{lang === 'en' ? child.aiFeedback : child.aiFeedbackZh}</span>
                      </>
                    )}
                  </div>
                </div>
                <span className={`text-[10px] font-semibold flex-shrink-0 ${published ? 'text-[#849F46]' : 'text-[#A8A79E]'}`}>
                  {published ? (lang === 'en' ? '✓ Sent' : '✓ 已发') : (lang === 'en' ? 'Draft' : '草稿')}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── History ─────────────────────────────────────────────────────────────────
type HistorySession = {
  dateEn: string; dateZh: string
  startTime: string; endTime: string
  totalChildren: number; nappers: number; settling: number; awake: number; alerts: number
  avgDuration: number
  records: { initials: string; nameEn: string; nameZh: string; stateKey: NapState; duration: number; feedbackEn: string; feedbackZh: string }[]
}

const HISTORY_SESSIONS: HistorySession[] = [
  {
    dateEn: 'Friday, Aug 29', dateZh: '2026年8月29日 周五',
    startTime: '12:20', endTime: '14:05',
    totalChildren: 10, nappers: 3, settling: 4, awake: 2, alerts: 1, avgDuration: 76,
    records: [
      { initials: 'EC', nameEn: 'Emma Chen',     nameZh: '陈小惠', stateKey: 'nappers',      duration: 105, feedbackEn: '—',                          feedbackZh: '—' },
      { initials: 'LW', nameEn: 'Lucas Wang',    nameZh: '王乐晨', stateKey: 'active-awake', duration: 15,  feedbackEn: 'Gesture Drawing',              feedbackZh: '互动绘画' },
      { initials: 'SL', nameEn: 'Sophia Liu',    nameZh: '刘思颖', stateKey: 'transitioners',duration: 22,  feedbackEn: 'Bedtime Story',                feedbackZh: '睡前故事' },
      { initials: 'OZ', nameEn: 'Oliver Zhang',  nameZh: '张欧阳', stateKey: 'resters',      duration: 20,  feedbackEn: 'Breathing Light + White Noise', feedbackZh: '呼吸灯 + 白噪音' },
      { initials: 'MH', nameEn: 'Mia Huang',     nameZh: '黄美艾', stateKey: 'risk',         duration: 19,  feedbackEn: 'Teacher Alert',                feedbackZh: '教师警报' },
      { initials: 'EL', nameEn: 'Ethan Li',      nameZh: '李以晨', stateKey: 'nappers',      duration: 63,  feedbackEn: '—',                          feedbackZh: '—' },
      { initials: 'AW', nameEn: 'Ava Wu',        nameZh: '吴安娅', stateKey: 'resters',      duration: 20,  feedbackEn: 'Breathing Light + White Noise', feedbackZh: '呼吸灯 + 白噪音' },
      { initials: 'NX', nameEn: 'Noah Xu',       nameZh: '徐诺亚', stateKey: 'active-awake', duration: 40,  feedbackEn: 'Gesture Drawing',              feedbackZh: '互动绘画' },
      { initials: 'IZ', nameEn: 'Isabella Zhou', nameZh: '周依萨', stateKey: 'nappers',      duration: 27,  feedbackEn: 'Bedtime Story',                feedbackZh: '睡前故事' },
      { initials: 'LC', nameEn: 'Liam Chen',     nameZh: '陈梁睿', stateKey: 'nappers',      duration: 81,  feedbackEn: '—',                          feedbackZh: '—' },
    ],
  },
  {
    dateEn: 'Thursday, Aug 28', dateZh: '2026年8月28日 周四',
    startTime: '12:35', endTime: '13:53',
    totalChildren: 10, nappers: 5, settling: 3, awake: 2, alerts: 0, avgDuration: 78,
    records: [
      { initials: 'EC', nameEn: 'Emma Chen',     nameZh: '陈小惠', stateKey: 'nappers',       duration: 78,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'LW', nameEn: 'Lucas Wang',    nameZh: '王乐晨', stateKey: 'resters',       duration: 55,  feedbackEn: 'Bedtime Story', feedbackZh: '睡前故事' },
      { initials: 'SL', nameEn: 'Sophia Liu',    nameZh: '刘思颖', stateKey: 'nappers',       duration: 68,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'OZ', nameEn: 'Oliver Zhang',  nameZh: '张欧阳', stateKey: 'nappers',       duration: 98,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'MH', nameEn: 'Mia Huang',     nameZh: '黄美艾', stateKey: 'transitioners', duration: 38,  feedbackEn: 'Bedtime Story', feedbackZh: '睡前故事' },
      { initials: 'EL', nameEn: 'Ethan Li',      nameZh: '李以晨', stateKey: 'nappers',       duration: 88,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'AW', nameEn: 'Ava Wu',        nameZh: '吴安娅', stateKey: 'active-awake',  duration: 25,  feedbackEn: 'Gesture Drawing', feedbackZh: '互动绘画' },
      { initials: 'NX', nameEn: 'Noah Xu',       nameZh: '徐诺亚', stateKey: 'resters',       duration: 60,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'IZ', nameEn: 'Isabella Zhou', nameZh: '周依萨', stateKey: 'nappers',       duration: 90,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'LC', nameEn: 'Liam Chen',     nameZh: '陈梁睿', stateKey: 'active-awake',  duration: 20,  feedbackEn: 'Gesture Drawing', feedbackZh: '互动绘画' },
    ],
  },
  {
    dateEn: 'Wednesday, Aug 27', dateZh: '2026年8月27日 周三',
    startTime: '12:40', endTime: '13:25',
    totalChildren: 9, nappers: 2, settling: 4, awake: 3, alerts: 0, avgDuration: 45,
    records: [
      { initials: 'EC', nameEn: 'Emma Chen',    nameZh: '陈小惠', stateKey: 'resters',       duration: 45, feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'LW', nameEn: 'Lucas Wang',   nameZh: '王乐晨', stateKey: 'active-awake',  duration: 30, feedbackEn: 'Gesture Drawing', feedbackZh: '互动绘画' },
      { initials: 'SL', nameEn: 'Sophia Liu',   nameZh: '刘思颖', stateKey: 'nappers',       duration: 45, feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'OZ', nameEn: 'Oliver Zhang', nameZh: '张欧阳', stateKey: 'resters',       duration: 45, feedbackEn: 'Breathing Light', feedbackZh: '呼吸灯' },
      { initials: 'EL', nameEn: 'Ethan Li',     nameZh: '李以晨', stateKey: 'transitioners', duration: 45, feedbackEn: 'Bedtime Story',  feedbackZh: '睡前故事' },
      { initials: 'AW', nameEn: 'Ava Wu',       nameZh: '吴安娅', stateKey: 'active-awake',  duration: 20, feedbackEn: 'Gesture Drawing', feedbackZh: '互动绘画' },
      { initials: 'NX', nameEn: 'Noah Xu',      nameZh: '徐诺亚', stateKey: 'active-awake',  duration: 40, feedbackEn: 'Gesture Drawing', feedbackZh: '互动绘画' },
      { initials: 'IZ', nameEn: 'Isabella Zhou',nameZh: '周依萨', stateKey: 'nappers',       duration: 45, feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'LC', nameEn: 'Liam Chen',    nameZh: '陈梁睿', stateKey: 'transitioners', duration: 40, feedbackEn: 'Bedtime Story',  feedbackZh: '睡前故事' },
    ],
  },
  {
    dateEn: 'Tuesday, Aug 26', dateZh: '2026年8月26日 周二',
    startTime: '12:25', endTime: '13:57',
    totalChildren: 10, nappers: 6, settling: 2, awake: 2, alerts: 0, avgDuration: 92,
    records: [
      { initials: 'EC', nameEn: 'Emma Chen',     nameZh: '陈小惠', stateKey: 'nappers',       duration: 92,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'LW', nameEn: 'Lucas Wang',    nameZh: '王乐晨', stateKey: 'active-awake',  duration: 30,  feedbackEn: 'Gesture Drawing', feedbackZh: '互动绘画' },
      { initials: 'SL', nameEn: 'Sophia Liu',    nameZh: '刘思颖', stateKey: 'nappers',       duration: 88,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'OZ', nameEn: 'Oliver Zhang',  nameZh: '张欧阳', stateKey: 'nappers',       duration: 92,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'MH', nameEn: 'Mia Huang',     nameZh: '黄美艾', stateKey: 'nappers',       duration: 75,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'EL', nameEn: 'Ethan Li',      nameZh: '李以晨', stateKey: 'nappers',       duration: 90,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'AW', nameEn: 'Ava Wu',        nameZh: '吴安娅', stateKey: 'resters',       duration: 65,  feedbackEn: 'Breathing Light', feedbackZh: '呼吸灯' },
      { initials: 'NX', nameEn: 'Noah Xu',       nameZh: '徐诺亚', stateKey: 'active-awake',  duration: 35,  feedbackEn: 'Gesture Drawing', feedbackZh: '互动绘画' },
      { initials: 'IZ', nameEn: 'Isabella Zhou', nameZh: '周依萨', stateKey: 'nappers',       duration: 92,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'LC', nameEn: 'Liam Chen',     nameZh: '陈梁睿', stateKey: 'transitioners', duration: 72,  feedbackEn: 'Bedtime Story',  feedbackZh: '睡前故事' },
    ],
  },
  {
    dateEn: 'Monday, Aug 25', dateZh: '2026年8月25日 周一',
    startTime: '12:30', endTime: '13:30',
    totalChildren: 10, nappers: 4, settling: 3, awake: 1, alerts: 2, avgDuration: 60,
    records: [
      { initials: 'EC', nameEn: 'Emma Chen',     nameZh: '陈小惠', stateKey: 'nappers',       duration: 60,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'LW', nameEn: 'Lucas Wang',    nameZh: '王乐晨', stateKey: 'risk',          duration: 25,  feedbackEn: 'Teacher Alert',  feedbackZh: '教师警报' },
      { initials: 'SL', nameEn: 'Sophia Liu',    nameZh: '刘思颖', stateKey: 'nappers',       duration: 55,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'OZ', nameEn: 'Oliver Zhang',  nameZh: '张欧阳', stateKey: 'resters',       duration: 50,  feedbackEn: 'Breathing Light', feedbackZh: '呼吸灯' },
      { initials: 'MH', nameEn: 'Mia Huang',     nameZh: '黄美艾', stateKey: 'risk',          duration: 20,  feedbackEn: 'Teacher Alert',  feedbackZh: '教师警报' },
      { initials: 'EL', nameEn: 'Ethan Li',      nameZh: '李以晨', stateKey: 'nappers',       duration: 60,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'AW', nameEn: 'Ava Wu',        nameZh: '吴安娅', stateKey: 'transitioners', duration: 45,  feedbackEn: 'Bedtime Story',  feedbackZh: '睡前故事' },
      { initials: 'NX', nameEn: 'Noah Xu',       nameZh: '徐诺亚', stateKey: 'active-awake',  duration: 30,  feedbackEn: 'Gesture Drawing', feedbackZh: '互动绘画' },
      { initials: 'IZ', nameEn: 'Isabella Zhou', nameZh: '周依萨', stateKey: 'nappers',       duration: 60,  feedbackEn: '—',             feedbackZh: '—' },
      { initials: 'LC', nameEn: 'Liam Chen',     nameZh: '陈梁睿', stateKey: 'nappers',       duration: 58,  feedbackEn: '—',             feedbackZh: '—' },
    ],
  },
]

function HistoryListView({ lang }: { lang: string }) {
  const [selected, setSelected] = useState<HistorySession | null>(null)

  if (selected) {
    return <HistorySessionDetail lang={lang} session={selected} onBack={() => setSelected(null)} />
  }

  return (
    <div className="p-6">
      <div className="mb-5">
        <h1 className="text-lg font-semibold text-[#16191A]">{lang === 'en' ? 'Nap History' : '午睡历史'}</h1>
        <p className="text-xs text-[#9B9B8E] mt-0.5">{lang === 'en' ? 'Past class nap sessions — click to view class report' : '历史班级午睡记录 — 点击查看班级报告'}</p>
      </div>
      <div className="space-y-2.5">
        {HISTORY_SESSIONS.map((s, i) => (
          <button key={i} onClick={() => setSelected(s)}
            className="w-full bg-white rounded-xl border border-[#ECEAE4] px-5 py-4 hover:border-[#849F46] hover:shadow-sm transition-all text-left flex items-center gap-4 group"
          >
            <div className="w-9 h-9 rounded-xl bg-[#EDF2E4] flex items-center justify-center flex-shrink-0">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="9" stroke="#849F46" strokeWidth="1.8"/>
                <path d="M12 7v5l3 3" stroke="#849F46" strokeWidth="1.8" strokeLinecap="round"/>
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-semibold text-[#16191A]">{lang === 'en' ? s.dateEn : s.dateZh}</span>
                {s.alerts > 0 && (
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-[#FEE2E2] text-[#991B1B]">
                    {s.alerts} {lang === 'en' ? (s.alerts > 1 ? 'alerts' : 'alert') : '警报'}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 text-xs text-[#9B9B8E]">
                <span className="font-mono">{s.startTime} – {s.endTime}</span>
                <span>·</span>
                <span>{s.totalChildren} {lang === 'en' ? 'children' : '名儿童'}</span>
                <span>·</span>
                <span>{lang === 'en' ? `${s.nappers} sleeping` : `${s.nappers} 名入睡`}</span>
              </div>
            </div>
            <div className="text-right flex-shrink-0">
              <p className="font-mono text-sm font-semibold text-[#16191A]">
                {Math.floor(s.avgDuration / 60) > 0 ? `${Math.floor(s.avgDuration / 60)}h ` : ''}{s.avgDuration % 60}m
                <span className="text-[10px] font-normal text-[#A8A79E] ml-1">{lang === 'en' ? 'avg' : '均'}</span>
              </p>
              <p className="text-[10px] text-[#849F46] font-medium mt-0.5">{lang === 'en' ? 'Published' : '已发布'}</p>
            </div>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="text-[#D0CFC8] group-hover:text-[#849F46] transition-colors flex-shrink-0">
              <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
        ))}
      </div>
    </div>
  )
}

function HistorySessionDetail({ lang, session: s, onBack }: { lang: string; session: HistorySession; onBack: () => void }) {
  const stateBreakdown = (
    [['nappers','active-awake','transitioners','resters','risk'] as NapState[]]
  )[0].map(key => ({
    key,
    count: s.records.filter(r => r.stateKey === key).length,
    cfg: STATE_CONFIG[key],
  })).filter(b => b.count > 0)

  return (
    <div className="p-6">
      {/* Back */}
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-[#9B9B8E] hover:text-[#849F46] mb-5 transition-colors">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M19 12H5M9 6l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
        {lang === 'en' ? 'Back to History' : '返回历史'}
      </button>

      {/* Session header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-xl font-semibold text-[#16191A]">{lang === 'en' ? s.dateEn : s.dateZh}</h1>
          <div className="flex items-center gap-2 mt-1 text-xs text-[#9B9B8E]">
            <span className="font-mono">{s.startTime} – {s.endTime}</span>
            <span>·</span>
            <span>{lang === 'en' ? 'Sunflower Class' : '向日葵班'}</span>
            {s.alerts > 0 && (
              <span className="ml-1 text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-[#FEE2E2] text-[#991B1B]">
                {s.alerts} {lang === 'en' ? (s.alerts > 1 ? 'alerts' : 'alert') : '警报'}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#E8F0D6] text-[#3D5A1A] text-xs font-semibold">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none"><path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
          {lang === 'en' ? 'Published' : '已发布'}
        </div>
      </div>

      {/* ① Class summary — always first */}
      <div className="grid grid-cols-5 gap-3 mb-4">
        {[
          { label: lang === 'en' ? 'Total' : '总人数',   val: `${s.totalChildren}`, color: '#849F46' },
          { label: lang === 'en' ? 'Sleeping' : '入睡',  val: `${s.nappers}`,       color: '#849F46' },
          { label: lang === 'en' ? 'Settling' : '过渡中', val: `${s.settling}`,     color: '#B58FD4' },
          { label: lang === 'en' ? 'Active' : '清醒',    val: `${s.awake}`,         color: '#F59E0B' },
          { label: lang === 'en' ? 'Avg Nap' : '平均时长', val: `${s.avgDuration}m`, color: '#16191A' },
        ].map(({ label, val, color }) => (
          <div key={label} className="bg-white rounded-xl border border-[#ECEAE4] px-4 py-3.5">
            <p className="text-[10px] text-[#A8A79E] uppercase tracking-wide mb-1.5">{label}</p>
            <p className="text-2xl font-semibold" style={{ color }}>{val}</p>
          </div>
        ))}
      </div>

      {/* State distribution bar */}
      <div className="bg-white rounded-xl border border-[#ECEAE4] p-4 mb-4">
        <p className="text-[10px] font-semibold text-[#A8A79E] uppercase tracking-widest mb-3">
          {lang === 'en' ? 'Class State Distribution' : '班级状态分布'}
        </p>
        <div className="flex h-4 rounded-lg overflow-hidden mb-3">
          {stateBreakdown.map(({ key, count, cfg }) => (
            <div key={key} style={{ width: `${(count / s.totalChildren) * 100}%`, background: cfg.color }}
              title={`${lang === 'en' ? cfg.label : cfg.labelZh}: ${count}`}
            />
          ))}
        </div>
        <div className="flex flex-wrap gap-3">
          {stateBreakdown.map(({ key, count, cfg }) => (
            <div key={key} className="flex items-center gap-1.5 text-xs">
              <span className="w-2 h-2 rounded-full" style={{ background: cfg.color }} />
              <span className="text-[#16191A] font-medium">{lang === 'en' ? cfg.label : cfg.labelZh}</span>
              <span className="text-[#A8A79E]">{count} {lang === 'en' ? 'children' : '人'}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ② Individual records */}
      <div className="bg-white rounded-xl border border-[#ECEAE4] overflow-hidden">
        <div className="px-5 py-3 border-b border-[#F2F1EC]">
          <p className="text-[10px] font-semibold text-[#A8A79E] uppercase tracking-widest">
            {lang === 'en' ? 'Individual Records' : '个人记录'}
          </p>
        </div>
        <div className="grid grid-cols-[2fr_1fr_1fr_2fr] px-5 py-2.5 border-b border-[#F2F1EC]">
          {[
            lang === 'en' ? 'Child' : '儿童',
            lang === 'en' ? 'Final State' : '最终状态',
            lang === 'en' ? 'Duration' : '时长',
            lang === 'en' ? 'Feedback Used' : '使用反馈',
          ].map((h, i) => (
            <span key={i} className="text-[10px] font-semibold text-[#A8A79E] uppercase tracking-widest">{h}</span>
          ))}
        </div>
        {s.records.map((r, i) => {
          const cfg = STATE_CONFIG[r.stateKey]
          return (
            <div key={i} className={`grid grid-cols-[2fr_1fr_1fr_2fr] items-center px-5 py-3.5 ${
              i < s.records.length - 1 ? 'border-b border-[#F2F1EC]' : ''
            } ${r.stateKey === 'risk' ? 'bg-[#FFF8F8]' : ''}`}>
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full flex items-center justify-center text-white text-[9px] font-bold flex-shrink-0" style={{ background: cfg.color }}>
                  {r.initials}
                </div>
                <span className="text-sm font-medium text-[#16191A]">{lang === 'en' ? r.nameEn : r.nameZh}</span>
              </div>
              <div>
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: cfg.bg, color: cfg.text }}>
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: cfg.color }} />
                  {lang === 'en' ? cfg.label : cfg.labelZh}
                </span>
              </div>
              <span className="font-mono text-sm text-[#16191A] font-semibold">{r.duration}m</span>
              <span className="text-xs text-[#9B9B8E]">{lang === 'en' ? r.feedbackEn : r.feedbackZh}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Settings ───────────────────────────────────────────────────────────────
function SettingsView({ lang }: { lang: string }) {
  return (
    <div className="p-6 max-w-xl">
      <div className="mb-5">
        <h1 className="text-lg font-semibold text-[#16191A]">{lang === 'en' ? 'Settings' : '设置'}</h1>
        <p className="text-xs text-[#9B9B8E] mt-0.5">{lang === 'en' ? 'Account and class preferences' : '账号与班级设置'}</p>
      </div>

      <div className="bg-white rounded-xl border border-[#ECEAE4] p-5 mb-4">
        <p className="text-[10px] font-semibold text-[#A8A79E] uppercase tracking-widest mb-3">{lang === 'en' ? 'Teacher Profile' : '教师信息'}</p>
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-[#849F46] flex items-center justify-center text-white font-bold text-sm">SW</div>
          <div>
            <p className="font-semibold text-sm text-[#16191A]">{lang === 'en' ? 'Sarah Wong' : '王晓萍'}</p>
            <p className="text-xs text-[#9B9B8E]">{lang === 'en' ? 'Lead Teacher · Sunflower Class' : '主班教师 · 向日葵班'}</p>
            <p className="text-xs text-[#849F46] font-mono mt-0.5">T-20240918</p>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        {[
          { label: lang === 'en' ? 'Class Settings' : '班级设置', sub: lang === 'en' ? 'Sunflower Class · 10 children' : '向日葵班 · 10名儿童' },
          { label: lang === 'en' ? 'Alert Thresholds' : '警报阈值', sub: lang === 'en' ? 'Customize sensor alert settings' : '自定义传感器警报' },
          { label: lang === 'en' ? 'AI Intervention' : 'AI 干预设置', sub: lang === 'en' ? 'Manage auto-execute preferences' : '管理AI自动执行偏好' },
          { label: lang === 'en' ? 'Notifications' : '通知设置', sub: lang === 'en' ? 'Email and push preferences' : '邮件和推送偏好' },
          { label: lang === 'en' ? 'Data & Privacy' : '数据与隐私', sub: lang === 'en' ? 'Data retention and export' : '数据保留与导出' },
        ].map(({ label, sub }) => (
          <button key={label} className="w-full bg-white rounded-xl border border-[#ECEAE4] px-5 py-4 flex items-center justify-between hover:border-[#849F46] hover:shadow-sm transition-all text-left">
            <div>
              <p className="text-sm font-medium text-[#16191A]">{label}</p>
              <p className="text-[11px] text-[#A8A79E] mt-0.5">{sub}</p>
            </div>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="#C0BFB8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Child Detail ────────────────────────────────────────────────────────────
function ChildDetail({ child, lang, t, onBack, onIntervention }: {
  child: Child; lang: string; t: typeof T['en']['teacher']; onBack: () => void; onIntervention: () => void
}) {
  const cfg = STATE_CONFIG[child.state]
  const cd = t.childDetail
  const totalTime = child.stateHistory.reduce((s, h) => s + h.duration, 0)
  const [busyAction, setBusyAction] = useState<InterventionAction | 'stop' | null>(null)
  const [actionMessage, setActionMessage] = useState('')

  async function triggerAction(action: InterventionAction) {
    setBusyAction(action)
    setActionMessage('')
    try {
      const result = await createManualIntervention(child.id, action)
      setActionMessage(lang === 'en' ? `Started: ${result.plan.final_action?.label || action}` : `已启动：${result.plan.final_action?.label || action}`)
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : lang === 'en' ? 'Unable to start intervention' : '启动干预失败')
    } finally {
      setBusyAction(null)
    }
  }

  async function stopAction() {
    if (!child.activePlanId) {
      setActionMessage(lang === 'en' ? 'No running intervention' : '当前没有正在运行的干预')
      return
    }
    setBusyAction('stop')
    setActionMessage('')
    try {
      await stopIntervention(child.activePlanId)
      setActionMessage(lang === 'en' ? 'Intervention stopped' : '干预已停止')
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : lang === 'en' ? 'Unable to stop intervention' : '停止干预失败')
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <div className="p-6">
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-[#9B9B8E] hover:text-[#849F46] mb-5 transition-colors">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M19 12H5M9 6l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
        {cd.back}
      </button>

      <div className="grid grid-cols-[280px_1fr] gap-5">
        {/* Left col */}
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-[#ECEAE4] overflow-hidden">
            <div className="h-1 w-full" style={{ background: cfg.color }} />
            <div className="p-5">
              <div className="flex flex-col items-center text-center mb-4">
                <div className="w-14 h-14 rounded-full flex items-center justify-center text-white text-lg font-bold mb-3" style={{ background: cfg.color }}>
                  {child.initials}
                </div>
                <h2 className="font-semibold text-[#16191A] text-lg leading-tight">
                  {lang === 'en' ? child.name : child.nameZh}
                </h2>
                <p className="text-[11px] text-[#9B9B8E] mt-0.5">{cd.class}</p>
              </div>
              <div className="space-y-2.5 pt-3 border-t border-[#F2F1EC]">
                <Row label={cd.currentState}>
                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: cfg.bg, color: cfg.text }}>
                    {lang === 'en' ? cfg.label : cfg.labelZh}
                  </span>
                </Row>
                <Row label={cd.timeInState}>
                  <span className="font-mono text-xs font-semibold text-[#16191A]">{child.timeInState} min</span>
                </Row>
                <Row label={cd.currentFeedback}>
                  <span className="text-[11px] font-medium text-[#849F46] text-right max-w-[120px] leading-tight">
                    {lang === 'en' ? child.aiFeedback : child.aiFeedbackZh}
                  </span>
                </Row>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl border border-[#ECEAE4] p-4">
            <p className="text-[10px] font-semibold text-[#A8A79E] uppercase tracking-widest mb-3">{cd.realTimeSignals}</p>
            <div className="space-y-2.5">
              {([
                { label: cd.respiratory, val: child.sensors.respiratory },
                { label: cd.movement,    val: child.sensors.movement },
                { label: cd.temperature, val: child.sensors.temperature },
                { label: cd.sound,       val: child.sensors.sound },
              ] as { label: string; val: string }[]).map(({ label, val }) => {
                const isAlert = ['Elevated', 'Active', 'Crying', 'High'].includes(val)
                const isGood  = ['Stable', 'Still', 'Quiet', 'Normal'].includes(val)
                const [dotColor, bgColor, textColor] = isAlert
                  ? ['#EF4444', '#FEE2E2', '#991B1B']
                  : isGood
                  ? ['#849F46', '#E8F0D6', '#3D5A1A']
                  : ['#C9A96E', '#FBF3E6', '#78520E']
                return (
                  <div key={label} className="flex items-center justify-between">
                    <span className="text-[11px] text-[#9B9B8E]">{label}</span>
                    <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: bgColor, color: textColor }}>
                      <span className="w-1.5 h-1.5 rounded-full" style={{ background: dotColor }} />
                      {val}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* Right col */}
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-[#ECEAE4] p-5">
            <p className="text-[10px] font-semibold text-[#A8A79E] uppercase tracking-widest mb-4">{cd.timeline}</p>
            <div className="flex h-5 rounded-lg overflow-hidden mb-4">
              {child.stateHistory.map((h, i) => (
                <div key={i} style={{ width: `${(h.duration / totalTime) * 100}%`, background: STATE_CONFIG[h.state].color }}
                  title={`${lang === 'en' ? STATE_CONFIG[h.state].label : STATE_CONFIG[h.state].labelZh} · ${h.duration}min`}
                />
              ))}
            </div>
            <div className="flex items-start gap-2">
              {child.stateHistory.map((h, i) => {
                const c = STATE_CONFIG[h.state]
                return (
                  <div key={i} className="flex-1 min-w-0 bg-[#F7F6F2] rounded-lg px-2.5 py-2">
                    <div className="flex items-center gap-1 mb-0.5">
                      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: c.color }} />
                      <span className="text-[10px] font-semibold text-[#16191A] truncate">{lang === 'en' ? c.label : c.labelZh}</span>
                    </div>
                    <p className="font-mono text-[10px] text-[#A8A79E]">{h.time}</p>
                    <p className="text-[10px] text-[#A8A79E]">{h.duration}min</p>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="bg-white rounded-xl border border-[#ECEAE4] p-5">
            <p className="text-[10px] font-semibold text-[#A8A79E] uppercase tracking-widest mb-4">{cd.manualFeedback}</p>
            <div className="grid grid-cols-2 gap-2">
              {[
                { label: cd.gestureDraw,  icon: PenIcon,  desc: lang === 'en' ? 'Active Awake' : '活跃清醒', danger: false },
                { label: cd.story,        icon: BookIcon, desc: lang === 'en' ? 'Transitioners' : '过渡入睡', danger: false },
                { label: cd.breathLight,  icon: LampIcon, desc: lang === 'en' ? 'Resters' : '安静休息', danger: false },
                { label: cd.stopFeedback, icon: StopIcon, desc: lang === 'en' ? 'Stop current' : '停止当前', danger: true },
              ].map(({ label, icon: Icon, desc, danger }, index) => (
                <button key={label}
                  onClick={() => danger ? stopAction() : triggerAction((['game', 'story', 'white_noise'] as InterventionAction[])[index])}
                  disabled={busyAction !== null}
                  className={`text-left p-3.5 rounded-xl border transition-all hover:shadow-sm flex items-start gap-2.5 ${
                    danger
                      ? 'border-[#FEE2E2] bg-[#FFF8F8] hover:border-[#EF4444] text-[#991B1B]'
                      : 'border-[#ECEAE4] bg-[#F7F6F2] hover:border-[#849F46] text-[#16191A]'
                  }`}
                >
                  <span className={`mt-0.5 ${danger ? 'text-[#EF4444]' : 'text-[#849F46]'}`}><Icon /></span>
                  <div>
                    <p className="text-xs font-semibold leading-tight">{label}</p>
                    <p className="text-[10px] text-[#A8A79E] mt-0.5">{busyAction === (danger ? 'stop' : (['game', 'story', 'white_noise'] as InterventionAction[])[index]) ? (lang === 'en' ? 'Working...' : '处理中...') : desc}</p>
                  </div>
                </button>
              ))}
            </div>
            {actionMessage && <p className="mt-3 text-xs text-[#6B6B62]" role="status">{actionMessage}</p>}
            <button onClick={onIntervention}
              className="w-full mt-3 py-2.5 bg-[#849F46] text-white text-sm font-semibold rounded-xl hover:bg-[#6F8C38] transition-colors"
            >
              {lang === 'en' ? 'Trigger AI Intervention' : '触发 AI 干预'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function actionForFeedback(feedback: string): InterventionAction {
  const value = feedback.toLowerCase()
  if (value.includes('draw') || value.includes('game') || value.includes('绘画')) return 'game'
  if (value.includes('story') || value.includes('故事')) return 'story'
  if (value.includes('light') || value.includes('呼吸')) return 'light'
  return 'white_noise'
}

// ── AI Intervention Modal ──────────────────────────────────────────────────
function InterventionModal({ lang, t, child, onClose }: { lang: string; t: typeof T['en']['teacher']; child: Child; onClose: () => void }) {
  const [count, setCount] = useState(8)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const ti = t.intervention
  const recommendedAction = actionForFeedback(child.aiFeedback)

  async function allow() {
    setBusy(true)
    setError('')
    try {
      if (child.pendingPlanId) await overrideIntervention(child.pendingPlanId, recommendedAction)
      else await createManualIntervention(child.id, recommendedAction)
      onClose()
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : lang === 'en' ? 'Unable to allow intervention' : '无法允许干预')
    } finally {
      setBusy(false)
    }
  }

  async function switchAction() {
    setBusy(true)
    setError('')
    try {
      if (child.pendingPlanId) await overrideIntervention(child.pendingPlanId, 'white_noise')
      else await createManualIntervention(child.id, 'white_noise')
      onClose()
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : lang === 'en' ? 'Unable to switch intervention' : '无法切换干预')
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    if (!child.pendingPlanId) {
      onClose()
      return
    }
    setBusy(true)
    setError('')
    try {
      await cancelIntervention(child.pendingPlanId)
      onClose()
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : lang === 'en' ? 'Unable to cancel intervention' : '无法取消干预')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (count <= 0) { onClose(); return }
    const id = setTimeout(() => setCount(c => c - 1), 1000)
    return () => clearTimeout(id)
  }, [count, onClose])

  const radius = 30
  const circ = 2 * Math.PI * radius
  const dash = circ * (count / 8)

  return (
    <div className="fixed inset-0 bg-black/35 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-[360px] overflow-hidden">
        <div className="px-6 pt-6 pb-4 text-center border-b border-[#F2F1EC]">
          <div className="flex justify-center mb-3"><PlankySleeping /></div>
          <p className="text-[10px] font-semibold text-[#9B9B8E] uppercase tracking-widest mb-0.5">{ti.title}</p>
          <p className="text-sm font-semibold text-[#16191A]">{lang === 'en' ? child.name : child.nameZh}</p>
        </div>
        <div className="px-6 py-5 text-center">
          <p className="text-[11px] text-[#9B9B8E] mb-2">{ti.recommends}</p>
          <div className="inline-block bg-[#EDF2E4] rounded-xl px-5 py-2.5 mb-5">
            <p className="text-sm font-semibold text-[#3D5A1A]">
              {lang === 'en' ? child.aiFeedback : child.aiFeedbackZh}
            </p>
          </div>
          <div className="flex justify-center mb-1">
            <svg width="84" height="84" viewBox="0 0 84 84">
              <circle cx="42" cy="42" r={radius} fill="none" stroke="#ECEAE4" strokeWidth="4"/>
              <circle cx="42" cy="42" r={radius} fill="none" stroke="#849F46" strokeWidth="4"
                strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
                transform="rotate(-90 42 42)" style={{ transition: 'stroke-dasharray 0.9s linear' }}
              />
              <text x="42" y="47" textAnchor="middle" fontSize="22" fontWeight="700" fill="#16191A">{count}</text>
            </svg>
          </div>
          <p className="text-[11px] text-[#C0BFB8] mb-5">{ti.autoNote}</p>
        </div>
        <div className="px-6 pb-6 grid grid-cols-3 gap-2">
          {error && <p className="col-span-3 text-xs text-red-600" role="alert">{error}</p>}
          <button onClick={cancel} disabled={busy} className="py-2.5 rounded-xl border border-[#ECEAE4] text-sm font-medium text-[#9B9B8E] hover:bg-[#F7F6F2] disabled:opacity-50 transition-colors">{ti.cancel}</button>
          <button onClick={switchAction} disabled={busy} className="py-2.5 rounded-xl border border-[#E6D9C0] text-sm font-medium text-[#8B6914] bg-[#FBF3E6] hover:bg-[#F5E8CC] disabled:opacity-50 transition-colors">{ti.switch}</button>
          <button onClick={allow} disabled={busy} className="py-2.5 rounded-xl bg-[#849F46] text-white text-sm font-semibold hover:bg-[#6F8C38] disabled:opacity-50 transition-colors">{ti.allow}</button>
        </div>
      </div>
    </div>
  )
}

// ── Alert Modal ─────────────────────────────────────────────────────────────
function AlertModal({ lang, t, child, onClose, onViewDetail }: {
  lang: string; t: typeof T['en']['teacher']; child: Child; onClose: () => void; onViewDetail: () => void
}) {
  const al = t.alert
  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm overflow-hidden">
        <div className="bg-[#EF4444] px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-white/20 flex items-center justify-center flex-shrink-0">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M12 9v4M12 17h.01" stroke="white" strokeWidth="2" strokeLinecap="round"/>
              </svg>
            </div>
            <div>
              <p className="text-white/60 text-[10px] font-semibold uppercase tracking-widest">{al.title}</p>
              <p className="text-white font-semibold text-base">{al.attention}</p>
            </div>
          </div>
        </div>
        <div className="p-5">
          <div className="flex items-center gap-3 mb-4 pb-4 border-b border-[#F2F1EC]">
            <div className="w-11 h-11 rounded-full bg-[#EF4444] flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
              {child.initials}
            </div>
            <div>
              <p className="font-semibold text-[#16191A] text-sm">{lang === 'en' ? child.name : child.nameZh}</p>
              <p className="text-xs text-[#9B9B8E]">{lang === 'en' ? 'Sunflower Class' : '向日葵班'}</p>
            </div>
          </div>
          <div className="space-y-2.5 mb-4">
            <div className="flex items-start justify-between gap-3">
              <span className="text-xs text-[#9B9B8E]">{al.alertType}</span>
              <span className="text-xs font-semibold text-[#EF4444] text-right">{lang === 'en' ? al.elevated_temp : '体温升高 + 情绪异常'}</span>
            </div>
            <div className="flex items-start justify-between gap-3">
              <span className="text-xs text-[#9B9B8E]">{lang === 'en' ? 'Detected' : '检测时间'}</span>
              <span className="text-xs font-semibold text-[#16191A]">{al.detected}</span>
            </div>
            <div className="bg-[#FEE2E2] rounded-xl p-3 mt-1">
              <p className="text-[10px] font-semibold text-[#991B1B] mb-1">{lang === 'en' ? 'Sensor Changes' : '传感器变化'}</p>
              <p className="text-[11px] text-[#7E7D74]">{al.sensorNote}</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button onClick={onClose} className="py-2.5 rounded-xl border border-[#ECEAE4] text-sm font-medium text-[#9B9B8E] hover:bg-[#F7F6F2] transition-colors">{al.dismiss}</button>
            <button onClick={onViewDetail} className="py-2.5 rounded-xl bg-[#EF4444] text-white text-sm font-semibold hover:bg-[#DC2626] transition-colors">{al.viewDetail}</button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[11px] text-[#A8A79E] flex-shrink-0">{label}</span>
      <div className="text-right">{children}</div>
    </div>
  )
}

function PlankySleeping() {
  return (
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
      <circle cx="32" cy="32" r="24" fill="url(#pg2)"/>
      <defs>
        <radialGradient id="pg2" cx="38%" cy="32%" r="65%">
          <stop offset="0%" stopColor="#BCE86A"/>
          <stop offset="100%" stopColor="#849F46"/>
        </radialGradient>
      </defs>
      <path d="M22 29.5 Q25.5 26.5 29 29.5" stroke="#3D5A1A" strokeWidth="2" strokeLinecap="round" fill="none"/>
      <path d="M35 29.5 Q38.5 26.5 42 29.5" stroke="#3D5A1A" strokeWidth="2" strokeLinecap="round" fill="none"/>
      <path d="M25 37 Q32 43 39 37" stroke="#3D5A1A" strokeWidth="2" strokeLinecap="round" fill="none"/>
      <ellipse cx="21" cy="35" rx="3.5" ry="2" fill="#FF9999" opacity="0.25"/>
      <ellipse cx="43" cy="35" rx="3.5" ry="2" fill="#FF9999" opacity="0.25"/>
      <path d="M32 8 C34 4 39 5.5 37 11 C35 9 33 8.5 32 8Z" fill="#5C7A2E"/>
      <text x="48" y="20" fontSize="7" fill="#849F46" fontWeight="700" opacity="0.9">z</text>
      <text x="53" y="13" fontSize="9" fill="#849F46" fontWeight="700" opacity="0.65">z</text>
    </svg>
  )
}

// ── Feedback Icons ───────────────────────────────────────────────────────────
function PenIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4 12.5-12.5z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
}
function BookIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
}
function LampIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M9 18h6M10 22h4M12 2a7 7 0 015.25 11.63A5 5 0 0112 18a5 5 0 01-5.25-4.37A7 7 0 0112 2z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
}
function StopIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="18" height="18" rx="3" stroke="currentColor" strokeWidth="2"/></svg>
}

// ── Nav Icons ────────────────────────────────────────────────────────────────
function GridIcon({ active }: { active: boolean }) {
  const w = active ? 2.2 : 1.8
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <rect x="3" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth={w}/>
    <rect x="14" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth={w}/>
    <rect x="3" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth={w}/>
    <rect x="14" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth={w}/>
  </svg>
}
function UsersIcon({ active }: { active: boolean }) {
  const w = active ? 2.2 : 1.8
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <circle cx="9" cy="7" r="3" stroke="currentColor" strokeWidth={w}/>
    <path d="M3 20c0-3.3 3.1-6 7-6" stroke="currentColor" strokeWidth={w} strokeLinecap="round"/>
    <circle cx="17" cy="9" r="2.5" stroke="currentColor" strokeWidth={w - 0.2}/>
    <path d="M13 20c0-2.8 1.8-5 4-5s4 2.2 4 5" stroke="currentColor" strokeWidth={w - 0.2} strokeLinecap="round"/>
  </svg>
}
function FileIcon({ active }: { active: boolean }) {
  const w = active ? 2.2 : 1.8
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" stroke="currentColor" strokeWidth={w} strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M14 2v6h6M8 13h8M8 17h5" stroke="currentColor" strokeWidth={w} strokeLinecap="round"/>
  </svg>
}
function ClockIcon({ active }: { active: boolean }) {
  const w = active ? 2.2 : 1.8
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth={w}/>
    <path d="M12 7v5l3 3" stroke="currentColor" strokeWidth={w} strokeLinecap="round"/>
  </svg>
}
function SettingsIcon({ active }: { active: boolean }) {
  const w = active ? 2.2 : 1.8
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth={w}/>
    <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" stroke="currentColor" strokeWidth={w}/>
  </svg>
}
function BellIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
}

// prevent unused import warning
const _r: NapState = 'nappers'
void _r
void NAP_REPORT
