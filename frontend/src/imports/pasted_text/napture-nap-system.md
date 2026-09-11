请为一个“幼儿园个性化午睡智能系统”设计一套完整的双角色数字界面，系统名称为 Napture。该数字系统与一个 AI Smart Headboard 智能床头板配套使用，核心目标是在幼儿园集体午睡场景中，根据不同儿童的午睡状态提供个性化支持，同时保留教师的监督和更高层级控制，并将午睡信息在午睡结束后同步给家长。

请设计成统一的产品生态，而不是两个彼此独立的产品。整个系统包括：
1. Login & Role Selection
2. Teacher Dashboard
3. Parent App
4. Bilingual System / 中文与 English 切换

整体视觉语言需要统一，包括品牌色、字体层级、卡片样式、圆角、图标、状态颜色、按钮、图表风格、Planky 角色形象等。但教师端与家长端的信息密度应不同：
Teacher Dashboard 更偏 operational、real-time、efficient；
Parent App 更偏 calm、simple、interpretive。

所有页面都需要支持中文 / English 一键切换。可以在右上角加入 language switch，例如“中文 | EN”或地球图标。中英文切换后页面结构、数据、图表、状态和交互逻辑不变，只切换文字。设计时要考虑英文和中文文本长度不同，避免固定宽度导致溢出。

-----------------------------------
A. LOGIN & ROLE SELECTION
-----------------------------------

首先设计统一登录入口。

登录页包括：
- Napture Logo
- Account / Email
- Password
- Log In
- Remember Me
- Forgot Password
- Language Switch：中文 / EN

用户登录后进入 Role Selection 页面。

标题：
Select Your Role

提供两个明显的大卡片：

Teacher
Subtitle:
Monitor and manage classroom naptime

Parent
Subtitle:
View your child’s nap report and routine suggestions

教师和家长使用同一套账号系统，但进入不同权限界面。

-----------------------------------
B. TEACHER DASHBOARD
-----------------------------------

教师端主要分成以下几类功能：

1. Classroom Overview / Monitor
2. Child Detail
3. AI Intervention Control
4. Risk / Alert
5. Nap Report & Publish
6. History / Children
7. Settings

核心设计理念：

The teacher interface is designed around class-wide visibility and human oversight.

AI can automatically identify children’s nap states and trigger interventions, while teachers retain higher-level control to review, override, switch, stop, or manually initiate feedback when necessary.

AI 不只是提供建议，而是可以主动运行和自动触发反馈；教师拥有比 AI 更高一级的监督和控制权限。

-------------------
B1. Classroom Overview
-------------------

教师首页不要设计成传统纯数据 dashboard，而是以真实幼儿园午睡教室为基础的 Classroom Nap Map。

教师可以：
- 查看整个班级的儿童状态
- 拖动儿童床位位置
- 根据真实教室布局重新排列床位
- 保存班级床位布局

每一个儿童对应一张 bed card / child card。

卡片显示：
- Child Name
- Avatar
- Current Nap State
- State Color
- Time in Current State
- AI Feedback Status
- Alert Indicator

教师能够通过颜色快速扫描全班。

午睡状态分类统一使用以下体系：

Active Awake
清醒并且活动较多

Resters
保持清醒但安静休息

Transitioners
正在从清醒向睡眠过渡

Nappers
已经进入稳定睡眠

Risk / Exception
出现需要教师关注的异常或风险

每一种状态使用统一固定颜色、icon 和 label。

Risk / Exception 使用明显红色 Alert。

-------------------
B2. Child Detail
-------------------

教师点击任意儿童卡片后，打开 Child Detail 页面或右侧 drawer。

内容包括：

Basic Information
- Name
- Avatar
- Class
- Current State
- Time in Current State
- Current AI Feedback

Real-time Signals
显示系统正在使用的多模态数据，例如：
- Respiratory Rate
- Body Movement
- Crying / Talking
- Body Temperature
- Other available sensor signals

界面不要设计得过于医疗化，可以使用：
Stable
Normal
Elevated
Changing
等状态表达。

加入 Nap State Timeline。

例如：
Active Awake
→ Resters
→ Transitioners
→ Nappers

让教师看到孩子在整个午睡过程中的状态变化，而不仅仅是当前状态。

-------------------
B3. AI Intervention Control
-------------------

AI 根据儿童当前状态可以自动触发不同反馈，包括：

Gesture Drawing
适合 Active Awake

Bedtime Story
适合 Transitioners

Breathing Light + White Noise
适合 Resters

No Active Feedback
适合 Nappers

Teacher Alert
适合 Risk / Exception

当 AI 即将触发一个反馈时，教师端出现短暂的 Review Window。

例如：

AI Intervention Ready

Planky recommends:
Breathing Light + White Noise

Starting in 8s

显示 5–10 秒倒计时。

教师可以选择：

Allow
允许 AI 正常执行

Switch
切换为其他反馈方式

Cancel
取消本次反馈

如果教师在倒计时结束前没有任何操作，则 AI 自动执行。

教师也可以在 Child Detail 页面主动触发反馈，不必等待 AI。

Manual Feedback options：
- Gesture Drawing
- Bedtime Story
- Breathing Light + White Noise
- Stop Current Feedback

因此整个教师端需要体现：

AI-driven
Teacher-supervised

而不是：
AI recommendation
Teacher execution

-------------------
B4. Risk / Alert
-------------------

当检测到风险或异常状态时，不继续普通安抚反馈，而是优先通知教师。

设计明显的 Teacher Alert 页面或弹窗。

显示：
- Child Name
- Alert Type
- Time Detected
- Relevant Sensor Changes
- Current State
- Teacher Attention Required

Risk / Exception 是独立安全分支，不和普通四类午睡状态混在同一条线性反馈逻辑里。

-------------------
B5. Nap Report & Publish
-------------------

午睡结束后系统自动生成 Nap Report Draft。

报告内容包括：
- Date
- Nap Start Time
- Wake-up Time
- Total Nap Duration
- State Timeline
- Feedback Used
- AI-triggered Interventions
- Teacher Interventions
- Alerts / Exceptions
- Overall Nap Summary

教师需要先 Review。

流程：
Review
→ Edit if needed
→ Publish

只有教师发布后，家长端才能收到报告。

教师首页或者 Reports 页面需要展示：
Draft
Published
Pending
等状态。

教师端核心流程可概括为：

Monitor
→ Review & Intervene
→ Publish

-------------------
B6. Teacher Navigation
-------------------

教师端可使用左侧 sidebar 或顶部 navigation。

建议包括：

Overview
Children
Reports
History
Settings

右上角：
Language Switch
Teacher Profile
Notifications

-----------------------------------
C. PARENT APP
-----------------------------------

家长端需要设计成移动端 App。

家长端的设计基础是：

儿童午睡不是一个孤立事件，而是全天睡眠需求的一部分。

因此家长端的目标不是实时监控孩子，而是帮助家长理解白天午睡对全天睡眠和晚间作息的影响。

核心理念：

The parent app links daytime naps to the child’s overall sleep needs, helping parents understand how nap duration and timing may affect the evening routine.

家长端主要分成以下几类：

1. Daily Nap Summary
2. Report Details
3. AI Routine Suggestion
4. Nap History
5. Profile / Settings

家长端不提供：
- 实时摄像头
- 实时音频
- 实时床头板控制
- 修改教师操作
- 直接触发反馈

家长只查看教师发布后的 post-nap information。

-------------------
C1. Daily Nap Summary
-------------------

Parent App 首页首先回答：

“今天中午睡得怎么样？”

顶部使用一个大的 Today’s Nap 卡片。

显示：
- Nap Duration
- Nap Start & End Time
- Overall Nap Status
- Simple Planky Character Expression
- Short Summary

例如：

Today’s Nap
1h 18min
12:43–14:01

Stable Nap

或者：
Smooth transition into sleep

界面需要简洁，不要一上来展示大量图表。

-------------------
C2. Report Details
-------------------

点击 Daily Nap Summary 后进入详细报告。

包括：

Nap Start Time
Wake-up Time
Total Nap Duration
Nap State Timeline
State Changes
Feedback Used
Teacher Intervention
AI Intervention
Alert / Exception if any
Publish Time

尤其需要显示：

Feedback Used

例如：

12:36
Breathing Light + White Noise

12:42
Bedtime Story

让家长知道午睡过程中系统具体进行了哪些支持。

-------------------
C3. AI Routine Suggestion
-------------------

根据当天午睡情况，系统生成简单的 evening routine suggestion。

例如：

如果当天午睡较长：
A longer nap today may reduce sleep pressure tonight. Consider keeping the usual bedtime or moving it slightly later if your child is not sleepy.

如果当天午睡较短：
Your child had a shorter nap today. An earlier and calmer bedtime routine may be helpful tonight.

建议语气不要像医疗诊断。

使用：
May
Consider
Could help

避免：
Must
Should
Treatment
Diagnosis

这个模块可以命名为：

Tonight’s Suggestion

或者：

AI Routine Suggestion

-------------------
C4. Nap History
-------------------

History 页面用于查看过去的午睡记录。

按日期展示：
- Nap Duration
- Nap Start Time
- Overall State
- Feedback Used

可以增加简单 Weekly Nap Pattern。

例如：
Mon
Tue
Wed
Thu
Fri

展示午睡时长或时间变化。

避免设计得像专业医疗监测仪表盘，重点是帮助家长理解短期模式。

-------------------
C5. Parent Navigation
-------------------

底部 navigation 建议：

Today
Reports
History
Profile

或者更简单：

Today
History
Profile

右上角保留：
中文 / EN

-----------------------------------
D. SHARED DESIGN SYSTEM
-----------------------------------

Teacher Dashboard 与 Parent App 必须明显属于同一套产品生态。

统一：
- Primary color palette
- Secondary colors
- Typography
- Icons
- Planky
- Status colors
- Cards
- Rounded corners
- Buttons
- Charts
- Alert components
- Child avatar style
- Tags
- Language switch

但不要让两端视觉完全一样。

Teacher Dashboard：
更紧凑
更多数据
更强调状态扫描
更强调实时性
更强调操作权限

Parent App：
更留白
更柔和
更少数据
更强调总结
更强调解释
更强调家庭日常理解

可以理解为：

Teacher Dashboard = Operational Interface
Parent App = Interpretive Interface

-----------------------------------
E. VISUAL STYLE
-----------------------------------

整体风格需要：

- Calm
- Warm
- Child-friendly
- Professional
- Contemporary
- Soft but not childish
- Suitable for kindergarten environment
- Avoid overly cartoonish UI
- Avoid generic blue “AI dashboard” aesthetic
- Avoid excessive gradients
- Avoid futuristic neon effects
- Avoid medical monitor appearance

可以使用柔和绿色、米白、浅灰、木色等与实体智能床头板一致的颜色。

Planky 可以作为统一角色元素出现，但不要占据过多面积。

Teacher Dashboard 需要更像成熟的 classroom management system。

Parent App 需要更像简洁、温暖、可信赖的家庭 sleep companion。

-----------------------------------
F. IMPORTANT UX PRINCIPLES
-----------------------------------

请严格遵循以下逻辑：

1. AI 是主动系统，不只是 recommendation system。
2. AI 可以自动触发反馈。
3. 教师拥有比 AI 更高一级的监督和控制权限。
4. 普通情况下教师无需逐次确认 AI。
5. AI 触发前提供短暂 5–10 秒 review window。
6. 教师可以取消、切换、覆盖或主动触发反馈。
7. Risk / Exception 始终优先升级给教师。
8. 家长没有实时控制权限。
9. 家长只接收教师审核并发布后的报告。
10. 家长端重点连接 daytime nap 与 overall daily sleep needs。
11. Teacher 与 Parent 使用统一视觉系统，但信息层级和权限不同。
12. 所有界面支持中文 / English 双语切换。
13. 所有状态命名、颜色和视觉表达在所有端保持一致。
14. 避免把产品设计成医疗诊断系统。
15. 所有 UI 需要真实、可实现、适合设计作品集展示，而不是纯概念 dashboard。

请最终输出一套完整、高保真、统一设计语言的 Teacher Dashboard + Parent App UI system，并优先展示以下关键页面：

1. Login
2. Role Selection
3. Teacher Classroom Overview
4. Teacher Child Detail
5. AI Intervention Countdown / Review
6. Teacher Alert
7. Nap Report Review & Publish
8. Parent Today’s Nap
9. Parent Report Details
10. Parent AI Routine Suggestion
11. Parent Nap History
12. English / Chinese language switching states