export type NapState = 'active-awake' | 'resters' | 'transitioners' | 'nappers' | 'risk'
export type Lang = 'en' | 'zh'

export const STATE_CONFIG: Record<NapState, { label: string; labelZh: string; color: string; bg: string; text: string; icon: string }> = {
  'active-awake': { label: 'Active Awake', labelZh: '活跃清醒', color: '#F59E0B', bg: '#FEF3C7', text: '#92400E', icon: '☀' },
  'resters':      { label: 'Resters',      labelZh: '安静休息', color: '#6B9FE4', bg: '#DBEAFE', text: '#1E40AF', icon: '◌' },
  'transitioners':{ label: 'Transitioners',labelZh: '过渡入睡', color: '#B58FD4', bg: '#EDE9FE', text: '#5B21B6', icon: '◑' },
  'nappers':      { label: 'Nappers',      labelZh: '稳定睡眠', color: '#849F46', bg: '#E8F0D6', text: '#3D5A1A', icon: '●' },
  'risk':         { label: 'Risk / Exception', labelZh: '需要关注', color: '#EF4444', bg: '#FEE2E2', text: '#991B1B', icon: '!' },
}

export interface Child {
  id: string; name: string; nameZh: string; initials: string; avatarBg: string
  state: NapState; timeInState: number; aiFeedback: string; aiFeedbackZh: string; hasAlert: boolean
  sensors: { respiratory: string; movement: string; temperature: string; sound: string }
  stateHistory: { state: NapState; time: string; duration: number }[]
  position: { row: number; col: number }
  pendingPlanId?: string
  activePlanId?: string
}

export const CHILDREN: Child[] = [
  {
    id: 'c1', name: 'Emma Chen', nameZh: '陈小惠', initials: 'EC', avatarBg: '#849F46',
    state: 'nappers', timeInState: 28, aiFeedback: 'No Active Feedback', aiFeedbackZh: '无主动反馈', hasAlert: false,
    sensors: { respiratory: 'Stable', movement: 'Still', temperature: 'Normal', sound: 'Quiet' },
    stateHistory: [
      { state: 'active-awake', time: '12:20', duration: 8 }, { state: 'resters', time: '12:28', duration: 6 },
      { state: 'transitioners', time: '12:34', duration: 5 }, { state: 'nappers', time: '12:39', duration: 28 },
    ],
    position: { row: 0, col: 0 },
  },
  {
    id: 'c2', name: 'Lucas Wang', nameZh: '王乐晨', initials: 'LW', avatarBg: '#F59E0B',
    state: 'active-awake', timeInState: 15, aiFeedback: 'Gesture Drawing', aiFeedbackZh: '互动绘画', hasAlert: false,
    sensors: { respiratory: 'Normal', movement: 'Active', temperature: 'Normal', sound: 'Talking' },
    stateHistory: [{ state: 'active-awake', time: '12:20', duration: 15 }],
    position: { row: 0, col: 1 },
  },
  {
    id: 'c3', name: 'Sophia Liu', nameZh: '刘思颖', initials: 'SL', avatarBg: '#B58FD4',
    state: 'transitioners', timeInState: 7, aiFeedback: 'Bedtime Story', aiFeedbackZh: '睡前故事', hasAlert: false,
    sensors: { respiratory: 'Changing', movement: 'Slight', temperature: 'Normal', sound: 'Quiet' },
    stateHistory: [
      { state: 'active-awake', time: '12:20', duration: 10 }, { state: 'resters', time: '12:30', duration: 5 },
      { state: 'transitioners', time: '12:35', duration: 7 },
    ],
    position: { row: 0, col: 2 },
  },
  {
    id: 'c4', name: 'Oliver Zhang', nameZh: '张欧阳', initials: 'OZ', avatarBg: '#6B9FE4',
    state: 'resters', timeInState: 12, aiFeedback: 'Breathing Light + White Noise', aiFeedbackZh: '呼吸灯 + 白噪音', hasAlert: false,
    sensors: { respiratory: 'Normal', movement: 'Slight', temperature: 'Normal', sound: 'Quiet' },
    stateHistory: [
      { state: 'active-awake', time: '12:20', duration: 8 }, { state: 'resters', time: '12:28', duration: 12 },
    ],
    position: { row: 0, col: 3 },
  },
  {
    id: 'c5', name: 'Mia Huang', nameZh: '黄美艾', initials: 'MH', avatarBg: '#EF4444',
    state: 'risk', timeInState: 3, aiFeedback: 'Teacher Alert', aiFeedbackZh: '教师警报', hasAlert: true,
    sensors: { respiratory: 'Elevated', movement: 'Active', temperature: 'Elevated', sound: 'Crying' },
    stateHistory: [
      { state: 'active-awake', time: '12:20', duration: 12 }, { state: 'resters', time: '12:32', duration: 4 },
      { state: 'risk', time: '12:36', duration: 3 },
    ],
    position: { row: 1, col: 0 },
  },
  {
    id: 'c6', name: 'Ethan Li', nameZh: '李以晨', initials: 'EL', avatarBg: '#849F46',
    state: 'nappers', timeInState: 31, aiFeedback: 'No Active Feedback', aiFeedbackZh: '无主动反馈', hasAlert: false,
    sensors: { respiratory: 'Stable', movement: 'Still', temperature: 'Normal', sound: 'Quiet' },
    stateHistory: [
      { state: 'active-awake', time: '12:20', duration: 5 }, { state: 'resters', time: '12:25', duration: 3 },
      { state: 'transitioners', time: '12:28', duration: 4 }, { state: 'nappers', time: '12:32', duration: 31 },
    ],
    position: { row: 1, col: 1 },
  },
  {
    id: 'c7', name: 'Ava Wu', nameZh: '吴安娅', initials: 'AW', avatarBg: '#6B9FE4',
    state: 'resters', timeInState: 9, aiFeedback: 'Breathing Light + White Noise', aiFeedbackZh: '呼吸灯 + 白噪音', hasAlert: false,
    sensors: { respiratory: 'Normal', movement: 'Still', temperature: 'Normal', sound: 'Quiet' },
    stateHistory: [
      { state: 'active-awake', time: '12:20', duration: 11 }, { state: 'resters', time: '12:31', duration: 9 },
    ],
    position: { row: 1, col: 2 },
  },
  {
    id: 'c8', name: 'Noah Xu', nameZh: '徐诺亚', initials: 'NX', avatarBg: '#F59E0B',
    state: 'active-awake', timeInState: 20, aiFeedback: 'Gesture Drawing', aiFeedbackZh: '互动绘画', hasAlert: false,
    sensors: { respiratory: 'Normal', movement: 'Active', temperature: 'Normal', sound: 'Talking' },
    stateHistory: [{ state: 'active-awake', time: '12:20', duration: 20 }],
    position: { row: 1, col: 3 },
  },
  {
    id: 'c9', name: 'Isabella Zhou', nameZh: '周依萨', initials: 'IZ', avatarBg: '#B58FD4',
    state: 'transitioners', timeInState: 4, aiFeedback: 'Bedtime Story', aiFeedbackZh: '睡前故事', hasAlert: false,
    sensors: { respiratory: 'Changing', movement: 'Slight', temperature: 'Normal', sound: 'Quiet' },
    stateHistory: [
      { state: 'active-awake', time: '12:20', duration: 12 }, { state: 'resters', time: '12:32', duration: 6 },
      { state: 'transitioners', time: '12:38', duration: 4 },
    ],
    position: { row: 2, col: 0 },
  },
  {
    id: 'c10', name: 'Liam Chen', nameZh: '陈梁睿', initials: 'LC', avatarBg: '#849F46',
    state: 'nappers', timeInState: 22, aiFeedback: 'No Active Feedback', aiFeedbackZh: '无主动反馈', hasAlert: false,
    sensors: { respiratory: 'Stable', movement: 'Still', temperature: 'Normal', sound: 'Quiet' },
    stateHistory: [
      { state: 'active-awake', time: '12:20', duration: 7 }, { state: 'resters', time: '12:27', duration: 4 },
      { state: 'transitioners', time: '12:31', duration: 3 }, { state: 'nappers', time: '12:34', duration: 22 },
    ],
    position: { row: 2, col: 1 },
  },
]

export const NAP_REPORT = {
  date: 'Friday, August 29',
  dateZh: '2026年8月29日 周五',
  startTime: '12:20', endTime: '14:05', duration: 105,
  stateTimeline: [
    { state: 'active-awake' as NapState, time: '12:20', duration: 8 },
    { state: 'resters' as NapState, time: '12:28', duration: 6 },
    { state: 'transitioners' as NapState, time: '12:34', duration: 5 },
    { state: 'nappers' as NapState, time: '12:39', duration: 66 },
  ],
  feedbackUsed: [
    { time: '12:24', type: 'Gesture Drawing', typeZh: '互动绘画', trigger: 'ai' as const },
    { time: '12:36', type: 'Breathing Light + White Noise', typeZh: '呼吸灯 + 白噪音', trigger: 'ai' as const },
    { time: '12:42', type: 'Bedtime Story', typeZh: '睡前故事', trigger: 'teacher' as const },
  ],
  alerts: [] as string[],
  summary: 'Emma had a smooth and restful nap today. She transitioned from active play to stable sleep within 19 minutes. Deep sleep was maintained for over an hour with no interruptions.',
  summaryZh: '小惠今天午睡顺利，状态良好。她在19分钟内从活跃状态进入稳定睡眠，整个过程平稳。深度睡眠维持超过一小时，无中断。',
  status: 'draft' as 'draft' | 'published',
}

export const NAP_HISTORY = [
  { date: 'Aug 29, Fri', dateZh: '8月29日 周五', duration: 105, startTime: '12:20', state: 'nappers' as NapState },
  { date: 'Aug 28, Thu', dateZh: '8月28日 周四', duration: 78, startTime: '12:35', state: 'nappers' as NapState },
  { date: 'Aug 27, Wed', dateZh: '8月27日 周三', duration: 45, startTime: '12:40', state: 'resters' as NapState },
  { date: 'Aug 26, Tue', dateZh: '8月26日 周二', duration: 92, startTime: '12:25', state: 'nappers' as NapState },
  { date: 'Aug 25, Mon', dateZh: '8月25日 周一', duration: 60, startTime: '12:30', state: 'nappers' as NapState },
]

export const T = {
  en: {
    login: {
      subtitle: 'Kindergarten Nap Intelligence System',
      email: 'Email Address', password: 'Password',
      remember: 'Remember me', forgot: 'Forgot password?',
      login: 'Log In', demo: 'Demo — click Log In to continue',
    },
    role: {
      selectRole: 'Select Your Role',
      subtitle: 'Choose your dashboard to get started.',
      teacher: 'Teacher', teacherSub: 'Monitor and manage classroom naptime',
      parent: 'Parent', parentSub: "View your child's nap report and routine suggestions",
    },
    teacher: {
      nav: { overview: 'Overview', children: 'Children', reports: 'Reports', history: 'History', settings: 'Settings' },
      overview: {
        title: 'Classroom Map', class: 'Sunflower Class', napStarted: 'Nap started at 12:20',
        minInState: 'min', saveLayout: 'Save Layout',
      },
      childDetail: {
        back: 'Back to Overview', class: 'Sunflower Class',
        currentState: 'Current State', timeInState: 'Time in State', currentFeedback: 'AI Feedback',
        realTimeSignals: 'Real-time Signals',
        respiratory: 'Respiratory Rate', movement: 'Body Movement', temperature: 'Body Temp', sound: 'Vocal Activity',
        timeline: 'Nap State Timeline', manualFeedback: 'Manual Feedback',
        gestureDraw: 'Gesture Drawing', story: 'Bedtime Story', breathLight: 'Breathing Light + White Noise', stopFeedback: 'Stop Current Feedback',
      },
      intervention: {
        title: 'AI Intervention Ready', recommends: 'Planky recommends:',
        startingIn: 'Starting in', seconds: 's',
        allow: 'Allow', switch: 'Switch', cancel: 'Cancel',
        autoNote: 'If no action is taken, AI will auto-execute.',
      },
      alert: {
        title: 'Teacher Alert', attention: 'Immediate Attention Required',
        alertType: 'Alert Type', elevated_temp: 'Elevated Body Temperature + Distress',
        detected: 'Detected at 12:39', sensorNote: 'Temperature: Elevated · Sound: Crying · Movement: Active',
        viewDetail: 'View Child Detail', dismiss: 'Acknowledge & Monitor',
      },
      report: {
        title: 'Nap Report', forEmma: 'Emma Chen',
        date: 'Date', startTime: 'Nap Start', endTime: 'Wake-up', duration: 'Duration', durationUnit: 'min',
        timeline: 'State Timeline', feedbackUsed: 'Feedback Used',
        ai: 'AI', teacher: 'Teacher', alerts: 'Alerts', none: 'None',
        summary: 'Summary', edit: 'Edit Report', publish: 'Publish to Parent', published: '✓ Report Published',
        draftBadge: 'Draft', publishedBadge: 'Published',
      },
    },
    parent: {
      nav: { today: 'Today', reports: 'Reports', history: 'History', profile: 'Profile' },
      today: {
        greeting: 'Good afternoon, Li Wei',
        subgreeting: "Here's Emma's nap update.",
        todaysNap: "Today's Nap", stableNap: 'Stable Nap',
        smoothTransition: 'Smooth transition into sleep',
        viewDetails: 'View Full Report',
        suggestion: "Tonight's Suggestion",
        viewHistory: 'View all history →',
        recentLabel: 'This week',
      },
      report: {
        title: "Today's Nap Report", forEmma: 'Emma',
        duration: 'Duration', start: 'Started', end: 'Woke up',
        timeline: 'State Timeline', feedbackUsed: 'Feedback Used',
        ai: 'AI', teacherLabel: 'Teacher',
        summary: 'Summary', publishedBy: 'Reviewed & published by teacher · 14:12',
      },
      suggestion: {
        title: "Tonight's Suggestion",
        from: "Based on today's nap",
        body: 'Emma had a great nap today — 1h 45min of quality sleep. This may slightly reduce her sleep pressure tonight. Consider keeping your usual bedtime, and adjust only if she seems less sleepy than usual.',
        tip: 'These suggestions are based on general sleep science. Every child is different.',
      },
      history: {
        title: 'Nap History', thisWeek: 'This Week',
        weeklyPattern: 'Weekly Pattern',
        avg: 'Weekly avg', min: 'min',
      },
    },
  },
  zh: {
    login: {
      subtitle: '幼儿园个性化午睡智能系统',
      email: '电子邮件', password: '密码',
      remember: '记住我', forgot: '忘记密码？',
      login: '登录', demo: '演示模式 — 点击登录继续',
    },
    role: {
      selectRole: '选择您的角色',
      subtitle: '选择您的专属界面开始使用。',
      teacher: '教师', teacherSub: '监控和管理班级午睡',
      parent: '家长', parentSub: '查看孩子的午睡报告和作息建议',
    },
    teacher: {
      nav: { overview: '总览', children: '儿童', reports: '报告', history: '历史', settings: '设置' },
      overview: {
        title: '教室地图', class: '向日葵班', napStarted: '午睡开始于 12:20',
        minInState: '分钟', saveLayout: '保存布局',
      },
      childDetail: {
        back: '返回总览', class: '向日葵班',
        currentState: '当前状态', timeInState: '持续时间', currentFeedback: 'AI 反馈',
        realTimeSignals: '实时信号',
        respiratory: '呼吸频率', movement: '身体活动', temperature: '体温', sound: '声音活动',
        timeline: '午睡状态时间线', manualFeedback: '手动干预',
        gestureDraw: '互动绘画', story: '睡前故事', breathLight: '呼吸灯 + 白噪音', stopFeedback: '停止当前反馈',
      },
      intervention: {
        title: 'AI 干预准备中', recommends: 'Planky 建议：',
        startingIn: '即将开始', seconds: '秒',
        allow: '允许', switch: '切换', cancel: '取消',
        autoNote: '如未操作，AI 将自动执行。',
      },
      alert: {
        title: '教师警报', attention: '需要立即关注',
        alertType: '警报类型', elevated_temp: '体温升高 + 情绪异常',
        detected: '检测时间 12:39', sensorNote: '体温：偏高 · 声音：哭泣 · 动作：活跃',
        viewDetail: '查看儿童详情', dismiss: '确认并观察',
      },
      report: {
        title: '午睡报告', forEmma: '陈小惠',
        date: '日期', startTime: '午睡开始', endTime: '唤醒时间', duration: '时长', durationUnit: '分钟',
        timeline: '状态时间线', feedbackUsed: '使用的反馈',
        ai: 'AI', teacher: '教师', alerts: '警报', none: '无',
        summary: '总结', edit: '编辑报告', publish: '发布给家长', published: '✓ 报告已发布',
        draftBadge: '草稿', publishedBadge: '已发布',
      },
    },
    parent: {
      nav: { today: '今天', reports: '报告', history: '历史', profile: '我的' },
      today: {
        greeting: '下午好，李威',
        subgreeting: '以下是小惠今日的午睡情况。',
        todaysNap: '今日午睡', stableNap: '稳定睡眠',
        smoothTransition: '顺利入睡',
        viewDetails: '查看完整报告',
        suggestion: '今晚建议',
        viewHistory: '查看所有历史 →',
        recentLabel: '本周',
      },
      report: {
        title: '今日午睡报告', forEmma: '小惠',
        duration: '时长', start: '开始时间', end: '唤醒时间',
        timeline: '状态时间线', feedbackUsed: '使用的反馈',
        ai: 'AI', teacherLabel: '教师',
        summary: '总结', publishedBy: '教师已审核发布 · 14:12',
      },
      suggestion: {
        title: '今晚建议',
        from: '根据今日午睡',
        body: '小惠今天午睡表现良好，高质量睡眠约1小时45分钟。今晚睡眠需求可能略有减少。建议维持平时的就寝时间，若孩子明显不困可稍作推迟。',
        tip: '以上建议基于通用睡眠科学原则，仅供参考，每个孩子情况不同。',
      },
      history: {
        title: '午睡历史', thisWeek: '本周',
        weeklyPattern: '本周规律',
        avg: '周均时长', min: '分钟',
      },
    },
  },
}
