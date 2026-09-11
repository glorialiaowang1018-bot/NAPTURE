import { useState, useContext, useEffect } from 'react'
import { AppContext, LangToggle } from '../App'
import { NAP_REPORT, NAP_HISTORY, STATE_CONFIG, T } from '../data'
import type { NapState } from '../data'
import { api } from '../api'

type ParentView = 'today' | 'report' | 'history' | 'profile'

export default function ParentApp() {
  const { lang, user, logout } = useContext(AppContext)
  const t = T[lang].parent
  const [view, setView] = useState<ParentView>('today')
  const [, setDataVersion] = useState(0)

  useEffect(() => {
    if (!user?.child_id) return
    let active = true
    async function loadParentData() {
      try {
        const [report, growth] = await Promise.all([
          api<{ child_name?: string; duration_seconds?: number; sleep_start?: string; wake_time?: string; quality?: string; suggestion?: { body?: string } }>(`/api/parent/${user.child_id}/today-report`),
          api<{ records?: Array<{ sleep_start?: string; duration_seconds?: number; quality?: string }> }>(`/api/parent/${user.child_id}/sleep-growth`),
        ])
        if (!active) return
        const duration = Math.round((report.duration_seconds || 0) / 60)
        NAP_REPORT.startTime = report.sleep_start ? new Date(report.sleep_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : NAP_REPORT.startTime
        NAP_REPORT.endTime = report.wake_time ? new Date(report.wake_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : NAP_REPORT.endTime
        NAP_REPORT.duration = duration || NAP_REPORT.duration
        NAP_REPORT.summaryZh = report.suggestion?.body || NAP_REPORT.summaryZh
        NAP_HISTORY.splice(0, NAP_HISTORY.length, ...(growth.records || []).slice(-5).map((record, index) => ({
          date: record.sleep_start || `Day ${index + 1}`,
          dateZh: record.sleep_start || `第${index + 1}天`,
          duration: Math.round((record.duration_seconds || 0) / 60),
          startTime: record.sleep_start ? new Date(record.sleep_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--',
          state: 'nappers' as NapState,
        })))
        setDataVersion((version) => version + 1)
      } catch {
        // Keep the bundled report visible if the backend is unavailable.
      }
    }
    loadParentData()
    return () => { active = false }
  }, [user?.child_id])

  return (
    <div className="h-full flex items-center justify-center bg-[#EDECEA]" style={{ fontFamily: "'Outfit', sans-serif" }}>
      {/* Phone frame */}
      <div className="relative w-[390px] h-full max-h-[844px] bg-[#F7F6F2] rounded-[44px] shadow-2xl shadow-black/25 overflow-hidden flex flex-col border-[5px] border-[#D8D6D0]">
        {/* Status bar */}
        <div className="flex items-center justify-between px-7 pt-4 pb-1.5 flex-shrink-0 bg-[#F7F6F2]">
          <span className="text-[13px] font-semibold text-[#16191A]">9:41</span>
          <div className="flex items-center gap-1.5">
            <svg width="17" height="11" viewBox="0 0 17 11" fill="#16191A" opacity="0.85">
              <rect x="0" y="3.5" width="3" height="7.5" rx="0.6"/>
              <rect x="4.5" y="2" width="3" height="9" rx="0.6"/>
              <rect x="9" y="0" width="3" height="11" rx="0.6"/>
              <rect x="13.5" y="1" width="3" height="10" rx="0.6" opacity="0.3"/>
            </svg>
            <svg width="16" height="11" viewBox="0 0 16 11" fill="none">
              <path d="M8 2.8C9.6 2.8 11 3.4 12.1 4.3L13.6 2.8C12.1 1.4 10.2 0.5 8 0.5S3.9 1.4 2.4 2.8L3.9 4.3C5 3.4 6.4 2.8 8 2.8Z" fill="#16191A" opacity="0.85"/>
              <path d="M8 5.5C9 5.5 9.9 5.9 10.6 6.6L12.1 5.1C11 4.1 9.6 3.5 8 3.5S5 4.1 3.9 5.1L5.4 6.6C6.1 5.9 7 5.5 8 5.5Z" fill="#16191A" opacity="0.85"/>
              <circle cx="8" cy="9.5" r="1.5" fill="#16191A" opacity="0.85"/>
            </svg>
            <div className="flex items-center">
              <div className="w-6 h-3 rounded-[3px] border-[1.5px] border-[#16191A]/70 flex items-center px-[2px]">
                <div className="w-[14px] h-[7px] bg-[#849F46] rounded-[1px]" />
              </div>
            </div>
          </div>
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-auto">
          {view === 'today'   && <TodayView    lang={lang} t={t} onViewReport={() => setView('report')} />}
          {view === 'report'  && <ReportDetail lang={lang} t={t} onBack={() => setView('today')} />}
          {view === 'history' && <HistoryView  lang={lang} t={t} />}
          {view === 'profile' && <ProfileView  lang={lang} />}
        </div>

        {/* Bottom nav */}
        <div className="flex-shrink-0 bg-white border-t border-[#ECEAE4] px-4 pt-2.5 pb-7">
          <div className="flex">
            {[
              { key: 'today',   icon: SunIcon,    label: t.nav.today },
              { key: 'report',  icon: DocIcon,    label: t.nav.reports },
              { key: 'history', icon: ChartIcon,  label: t.nav.history },
              { key: 'profile', icon: PersonIcon, label: t.nav.profile },
            ].map(({ key, icon: Icon, label }) => (
              <button key={key} onClick={() => setView(key as ParentView)}
                className="flex-1 flex flex-col items-center gap-1 py-1.5"
              >
                <span style={{ color: view === key ? '#849F46' : '#C0BFB8' }}><Icon /></span>
                <span className="text-[10px] font-semibold" style={{ color: view === key ? '#849F46' : '#C0BFB8' }}>{label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Lang toggle — outside phone */}
      <div className="absolute top-5 right-5 flex items-center gap-2"><LangToggle /><button onClick={logout} className="text-[11px] font-semibold text-[#8A8A80] hover:text-[#EF4444]">{lang === 'en' ? 'Sign out' : '退出'}</button></div>
    </div>
  )
}

// ── Today View ──────────────────────────────────────────────────────────────
function TodayView({ lang, t, onViewReport }: { lang: string; t: typeof T['en']['parent']; onViewReport: () => void }) {
  const dayLabels = ['M', 'T', 'W', 'T', 'F']
  const maxDur = Math.max(...NAP_HISTORY.map(n => n.duration))

  return (
    <div className="px-5 py-4 space-y-3.5">
      {/* Greeting row */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[17px] font-semibold text-[#16191A] leading-tight">{t.today.greeting}</h1>
          <p className="text-xs text-[#9B9B8E] mt-0.5">{t.today.subgreeting}</p>
        </div>
        <div className="w-8 h-8 rounded-full bg-[#849F46] flex items-center justify-center text-white text-[11px] font-bold">LW</div>
      </div>

      {/* Main nap card */}
      <div className="bg-[#849F46] rounded-[24px] p-5 relative overflow-hidden">
        {/* Decorative rings */}
        <div className="absolute -right-6 -bottom-6 w-28 h-28 rounded-full border-2 border-white/10" />
        <div className="absolute -right-2 -bottom-2 w-16 h-16 rounded-full border-2 border-white/10" />

        <p className="text-white/60 text-[10px] font-bold uppercase tracking-[0.12em] mb-2">{t.today.todaysNap}</p>
        <div className="flex items-baseline gap-1.5 mb-1">
          <span className="text-[36px] font-semibold text-white leading-none">1h 45</span>
          <span className="text-white/60 text-sm">{lang === 'en' ? 'min' : '分钟'}</span>
        </div>
        <p className="text-white/55 text-xs font-mono mb-4">12:20 – 14:05</p>
        <div className="flex items-end justify-between">
          <div>
            <span className="inline-flex items-center gap-1.5 bg-white/20 text-white text-[11px] font-semibold px-3 py-1.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-white" />
              {t.today.stableNap}
            </span>
            <p className="text-white/45 text-[11px] mt-2">{t.today.smoothTransition}</p>
          </div>
          <PlankyHappy />
        </div>
      </div>

      {/* View report button */}
      <button onClick={onViewReport}
        className="w-full py-3 bg-white rounded-2xl border border-[#ECEAE4] text-sm font-semibold text-[#849F46] hover:bg-[#EDF2E4] transition-colors flex items-center justify-center gap-2"
      >
        {t.today.viewDetails}
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
      </button>

      {/* Tonight's suggestion */}
      <div className="bg-white rounded-2xl border border-[#ECEAE4] p-4">
        <div className="flex items-center gap-2 mb-2.5">
          <div className="w-6 h-6 rounded-full bg-[#F4EFE0] flex items-center justify-center text-xs">🌙</div>
          <p className="text-sm font-semibold text-[#16191A]">{t.today.suggestion}</p>
        </div>
        <p className="text-[12px] text-[#6B6B62] leading-relaxed mb-2.5">{T[lang as 'en' | 'zh'].parent.suggestion.body}</p>
        <p className="text-[10px] text-[#B0AFA7] leading-relaxed italic">{T[lang as 'en' | 'zh'].parent.suggestion.tip}</p>
      </div>

      {/* Mini history chart */}
      <div>
        <div className="flex items-center justify-between mb-2.5">
          <p className="text-[10px] font-bold text-[#A8A79E] uppercase tracking-widest">{t.today.recentLabel}</p>
          <button className="text-[11px] text-[#849F46] font-medium">{t.today.viewHistory}</button>
        </div>
        <div className="bg-white rounded-2xl border border-[#ECEAE4] px-4 py-3">
          <div className="flex gap-2 items-end h-14">
            {NAP_HISTORY.slice().reverse().map((h, i) => {
              const pct = (h.duration / maxDur) * 100
              const isToday = i === NAP_HISTORY.length - 1
              return (
                <div key={i} className="flex-1 flex flex-col items-center gap-1.5">
                  <div className="w-full rounded-md transition-all"
                    style={{ height: `${pct}%`, minHeight: 4, background: isToday ? '#849F46' : '#E6E5DF' }}
                  />
                  <span className="text-[9px] font-medium text-[#C0BFB8]">{dayLabels[i]}</span>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Report Detail ───────────────────────────────────────────────────────────
function ReportDetail({ lang, t, onBack }: { lang: string; t: typeof T['en']['parent']; onBack: () => void }) {
  const report = NAP_REPORT
  const tr = t.report
  const totalTime = report.stateTimeline.reduce((s, h) => s + h.duration, 0)

  return (
    <div className="px-5 py-4">
      <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-[#9B9B8E] hover:text-[#849F46] mb-4 transition-colors">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M19 12H5M9 6l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
        {lang === 'en' ? 'Today' : '今天'}
      </button>

      <h2 className="font-semibold text-[#16191A] text-lg mb-0.5">{tr.title}</h2>
      <p className="text-xs text-[#9B9B8E] mb-4">{lang === 'en' ? report.date : report.dateZh} · {tr.forEmma}</p>

      {/* Duration row */}
      <div className="grid grid-cols-3 gap-2 mb-3.5">
        {[
          { label: tr.duration, val: '1h 45m' },
          { label: tr.start,   val: report.startTime },
          { label: tr.end,     val: report.endTime },
        ].map(({ label, val }) => (
          <div key={label} className="bg-white rounded-xl border border-[#ECEAE4] p-3 text-center">
            <p className="text-[10px] text-[#A8A79E] mb-1">{label}</p>
            <p className="font-mono text-sm font-semibold text-[#16191A]">{val}</p>
          </div>
        ))}
      </div>

      {/* State timeline */}
      <div className="bg-white rounded-2xl border border-[#ECEAE4] p-4 mb-3">
        <p className="text-[10px] font-bold text-[#A8A79E] uppercase tracking-widest mb-3">{tr.timeline}</p>
        <div className="flex h-4 rounded-lg overflow-hidden mb-3">
          {report.stateTimeline.map((h, i) => (
            <div key={i} style={{ width: `${(h.duration / totalTime) * 100}%`, background: STATE_CONFIG[h.state].color }} />
          ))}
        </div>
        <div className="space-y-2">
          {report.stateTimeline.map((h, i) => {
            const c = STATE_CONFIG[h.state]
            return (
              <div key={i} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: c.color }} />
                  <span className="text-xs text-[#16191A]">{lang === 'en' ? c.label : c.labelZh}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] text-[#A8A79E]">{h.time}</span>
                  <span className="text-[11px] text-[#9B9B8E]">{h.duration}{lang === 'en' ? 'min' : '分'}</span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Feedback */}
      <div className="bg-white rounded-2xl border border-[#ECEAE4] p-4 mb-3">
        <p className="text-[10px] font-bold text-[#A8A79E] uppercase tracking-widest mb-3">{tr.feedbackUsed}</p>
        <div className="space-y-2.5">
          {report.feedbackUsed.map((f, i) => (
            <div key={i} className="flex items-center gap-2.5">
              <span className="font-mono text-[10px] text-[#A8A79E] w-9">{f.time}</span>
              <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0 ${
                f.trigger === 'ai' ? 'bg-[#EDF2E4] text-[#3D5A1A]' : 'bg-[#DBEAFE] text-[#1E40AF]'
              }`}>{f.trigger === 'ai' ? tr.ai : tr.teacherLabel}</span>
              <span className="text-xs text-[#16191A]">{lang === 'en' ? f.type : f.typeZh}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Summary */}
      <div className="bg-white rounded-2xl border border-[#ECEAE4] p-4 mb-3">
        <p className="text-[10px] font-bold text-[#A8A79E] uppercase tracking-widest mb-2">{tr.summary}</p>
        <p className="text-xs text-[#3D4030] leading-relaxed">{lang === 'en' ? report.summary : report.summaryZh}</p>
      </div>

      <div className="flex items-center gap-1.5 text-[10px] text-[#B0AFA7]">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2"/>
          <path d="M12 8v4l2.5 2.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
        </svg>
        {tr.publishedBy}
      </div>
    </div>
  )
}

// ── History View ────────────────────────────────────────────────────────────
function HistoryView({ lang, t }: { lang: string; t: typeof T['en']['parent'] }) {
  const th = t.history
  const maxDur = Math.max(...NAP_HISTORY.map(n => n.duration))
  const avgDur = Math.round(NAP_HISTORY.reduce((s, h) => s + h.duration, 0) / NAP_HISTORY.length)
  const dayLabels = ['M', 'T', 'W', 'T', 'F']

  return (
    <div className="px-5 py-4">
      <h2 className="font-semibold text-[#16191A] text-lg mb-4">{th.title}</h2>

      {/* Weekly chart */}
      <div className="bg-white rounded-2xl border border-[#ECEAE4] p-4 mb-3.5">
        <div className="flex items-center justify-between mb-4">
          <p className="text-[10px] font-bold text-[#A8A79E] uppercase tracking-widest">{th.weeklyPattern}</p>
          <span className="text-[11px] text-[#9B9B8E]">{th.avg}: {avgDur}{lang === 'en' ? 'min' : '分'}</span>
        </div>
        <div className="flex gap-2 items-end h-20 mb-2">
          {NAP_HISTORY.slice().reverse().map((h, i) => {
            const pct = (h.duration / maxDur) * 100
            const isToday = i === NAP_HISTORY.length - 1
            const cfg = STATE_CONFIG[h.state]
            return (
              <div key={i} className="flex-1 flex flex-col items-center gap-1.5">
                <span className="text-[9px] font-mono text-[#C0BFB8]">{h.duration}</span>
                <div className="w-full rounded-md" style={{ height: `${pct}%`, minHeight: 6, background: isToday ? cfg.color : '#E6E5DF' }} />
                <span className="text-[9px] font-medium text-[#C0BFB8]">{dayLabels[i]}</span>
              </div>
            )
          })}
        </div>
        <div className="flex items-center gap-4 text-[10px] text-[#C0BFB8] mt-1">
          <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-[#849F46]"/>{lang === 'en' ? 'Today' : '今日'}</div>
          <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-[#E6E5DF]"/>{lang === 'en' ? 'Previous days' : '往日'}</div>
        </div>
      </div>

      {/* List */}
      <div className="space-y-2">
        {NAP_HISTORY.map((h, i) => {
          const cfg = STATE_CONFIG[h.state]
          return (
            <div key={i} className="bg-white rounded-xl border border-[#ECEAE4] px-4 py-3 flex items-center gap-3">
              <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: cfg.bg }}>
                <span className="w-2 h-2 rounded-full" style={{ background: cfg.color }} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-[#16191A]">{lang === 'en' ? h.date : h.dateZh}</p>
                <p className="text-[11px] text-[#9B9B8E]">{h.startTime} · {lang === 'en' ? cfg.label : cfg.labelZh}</p>
              </div>
              <div className="text-right flex-shrink-0">
                <p className="font-mono text-sm font-semibold text-[#16191A]">
                  {Math.floor(h.duration / 60) > 0 ? `${Math.floor(h.duration / 60)}h ` : ''}{h.duration % 60}m
                </p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Profile View ─────────────────────────────────────────────────────────────
function ProfileView({ lang }: { lang: string }) {
  return (
    <div className="px-5 py-4">
      <h2 className="font-semibold text-[#16191A] text-lg mb-5">{lang === 'en' ? 'Profile' : '我的'}</h2>
      <div className="bg-white rounded-2xl border border-[#ECEAE4] p-4 mb-4 flex items-center gap-3">
        <div className="w-12 h-12 rounded-xl bg-[#EDF2E4] flex items-center justify-center text-xl">👩‍👧</div>
        <div>
          <p className="font-semibold text-sm text-[#16191A]">{lang === 'en' ? 'Li Wei' : '李威'}</p>
          <p className="text-xs text-[#9B9B8E]">{lang === 'en' ? "Emma's parent" : '小惠的家长'}</p>
          <p className="text-xs text-[#849F46] mt-0.5 font-medium">{lang === 'en' ? 'Sunflower Class' : '向日葵班'}</p>
        </div>
      </div>
      <div className="space-y-1.5">
        {[
          lang === 'en' ? 'Notification Settings' : '通知设置',
          lang === 'en' ? 'Language' : '语言',
          lang === 'en' ? 'Privacy' : '隐私',
          lang === 'en' ? 'About Napture' : '关于 Napture',
        ].map(item => (
          <div key={item} className="bg-white rounded-xl border border-[#ECEAE4] px-4 py-3 flex items-center justify-between">
            <span className="text-sm text-[#16191A]">{item}</span>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="#C0BFB8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Planky ───────────────────────────────────────────────────────────────────
function PlankyHappy() {
  return (
    <svg width="54" height="54" viewBox="0 0 60 60" fill="none">
      <circle cx="30" cy="30" r="22" fill="url(#ph)"/>
      <defs>
        <radialGradient id="ph" cx="38%" cy="32%" r="65%">
          <stop offset="0%" stopColor="#C8E87A"/>
          <stop offset="100%" stopColor="#9AB84E"/>
        </radialGradient>
      </defs>
      {/* Happy squint eyes */}
      <path d="M20 27 Q23.5 23.5 27 27" stroke="#3D5A1A" strokeWidth="2.2" strokeLinecap="round" fill="none"/>
      <path d="M33 27 Q36.5 23.5 40 27" stroke="#3D5A1A" strokeWidth="2.2" strokeLinecap="round" fill="none"/>
      {/* Big smile */}
      <path d="M22 35 Q30 43 38 35" stroke="#3D5A1A" strokeWidth="2.2" strokeLinecap="round" fill="none"/>
      {/* Rosy cheeks */}
      <ellipse cx="19.5" cy="34" rx="3.5" ry="2.2" fill="#FF8888" opacity="0.22"/>
      <ellipse cx="40.5" cy="34" rx="3.5" ry="2.2" fill="#FF8888" opacity="0.22"/>
      {/* Leaf */}
      <path d="M30 8 C32 3.5 38 5 36 11 C34 9 32 8 30 8Z" fill="#5C7A2E"/>
    </svg>
  )
}

// ── Nav Icons ─────────────────────────────────────────────────────────────────
function SunIcon() {
  return <svg width="21" height="21" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
}
function DocIcon() {
  return <svg width="21" height="21" viewBox="0 0 24 24" fill="none">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"/>
    <path d="M8 12h8M8 16h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
}
function ChartIcon() {
  return <svg width="21" height="21" viewBox="0 0 24 24" fill="none">
    <rect x="3" y="12" width="4" height="9" rx="1" stroke="currentColor" strokeWidth="1.8"/>
    <rect x="10" y="7" width="4" height="14" rx="1" stroke="currentColor" strokeWidth="1.8"/>
    <rect x="17" y="3" width="4" height="18" rx="1" stroke="currentColor" strokeWidth="1.8"/>
  </svg>
}
function PersonIcon() {
  return <svg width="21" height="21" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="7" r="4" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M4 20c0-3.9 3.6-7 8-7s8 3.1 8 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
}

// prevent unused import warning
const _unused: NapState = 'nappers'
void _unused
