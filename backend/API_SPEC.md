# Teacher / Parent Dashboard API

当前后端由 Flask 提供。设备通过 `/data` 上报传感器数据，浏览器干预模块通过 `/api/device/camera-observation` 上报非图像视觉特征。系统聚合近期趋势，允许 LLM 在安全范围内调整状态分类阈值，再由显式分类器产生状态并进入教师审核与反馈流程。`/api/ai/decision` 仍可接收外部 AI 管线的决策结果。

## 页面

- `GET /teacher`：教师端 Dashboard。
- `GET /parent`：家长端手机 Dashboard，按登录账号绑定关系读取报告。
- `GET /monitor/camera?child_id=<id>`：持续采集本地摄像头动作特征并接入统一状态管线；不上传原始画面。

## 演示模式

演示模式用于未连接 ESP32 时随机生成儿童状态、环境数据、互动记录和 AI 待干预计划，便于先测试教师端和家长端效果。

当前本机混合联调约定：

- 全班都使用连续的虚拟生理数据。
- `demo-015`（小晴）绑定本机虚拟执行端，教师手动干预会真实启动现有音频或页面程序。
- 其他孩子保留相同操作流程，但执行结果为 `execution_endpoint_not_connected`，不会启动本机效果，也不会伪造成功回执。
- `white_noise` 为组合动作：同时启动 `breath_noise.py` 和呼吸灯页面。

### `POST /api/debug/demo/start`

启动后端随机数据线程。

返回：

```json
{ "status": "ok", "enabled": true, "started": true }
```

### `POST /api/debug/demo/stop`

停止后端随机数据线程。

返回：

```json
{ "status": "ok", "enabled": false }
```

### `GET /api/debug/demo/status`

查看演示模式状态。

返回：

```json
{ "enabled": true, "children": ["demo-001", "demo-002"] }
```

### `POST /api/debug/demo/trigger`

手动触发一次演示 AI 干预计划，用来立刻测试教师端 5 秒取消/改写流程。若演示模式尚未启动，会自动启动。

返回：

```json
{
  "status": "ok",
  "child_id": "demo-001",
  "plan": {
    "id": "plan-id",
    "status": "pending",
    "proposed_action": { "type": "story", "param": "soft", "label": "异常安抚语音" }
  }
}
```

## REST API

### `POST /data`

设备实时数据上报。

请求体字段可包含：

```json
{
  "child_id": "device-default",
  "name": "可选儿童姓名",
  "state": "可选；无数值信号时作为回退状态",
  "hr": 82,
  "br": 22,
  "mic": 0.12,
  "motion": 30,
  "temperature": 25.5,
  "humidity": 53,
  "brightness": 120
}
```

当请求包含传感器数值时，后端会返回显式分类器产生的 `classified_state`，以及本次阈值来自 `llm`、`rules` 或 `rules_fallback`：

```json
{
  "status": "ok",
  "child_id": "device-default",
  "classified_state": "sleeping",
  "decision_source": "llm"
}
```

### `POST /api/device/camera-observation`

浏览器端摄像头模块上报动作与手势特征。接口不接收、不保存原始照片或视频。

```json
{
  "child_id": "device-default",
  "motion_ratio": 0.042,
  "gesture": "one",
  "hands_detected": 1,
  "source": "gesture_drawing_camera"
}
```

返回：

```json
{ "status": "ok", "msg": "received", "child_id": "device-default" }
```

### `GET /api/teacher/class-overview`

教师端班级总览、状态分布和待确认 AI 干预计划。

返回：

```json
{
  "children": [
    {
      "id": "device-default",
      "name": "未绑定儿童",
      "avatar": "",
      "current_state": "sleepy",
      "sleep_start": null,
      "sleep_duration_seconds": null,
      "environment": {},
      "priority": 1
    }
  ],
  "pending_interventions": [
    {
      "id": "plan-id",
      "child_id": "device-default",
      "state": "sleepy",
      "proposed_action": { "type": "white_noise", "param": "slow", "label": "白噪音/呼吸灯" },
      "status": "pending",
      "deadline_ts": 1781680000.0
    }
  ],
  "stats": {
    "state_distribution": { "sleepy": 1 },
    "sleeping_count": 0,
    "avg_sleep_seconds": null
  }
}
```

### `GET /api/children/<child_id>/detail`

儿童详情页数据：实时状态、环境、采样历史、睡眠记录、互动事件、家长反馈。

### `POST /api/ai/decision`

AI 主循环提交判断结果和即将执行的干预动作。后端创建 5 秒教师确认窗口；若教师未操作，由服务器批准并调度现有干预程序。调用方不得再次执行返回动作，避免重复触发。

请求体：

```json
{
  "child_id": "device-default",
  "state": "sleepy",
  "sensor": { "hr": 82, "br": 22, "motion": 20 },
  "llm_result": {},
  "proposed_action": { "type": "white_noise", "param": "slow", "label": "白噪音/呼吸灯" }
}
```

返回：

```json
{
  "status": "auto_approved|cancelled|overridden|no_intervention",
  "plan_id": "plan-id",
  "execute": false,
  "dispatched": true,
  "dispatch_owner": "server",
  "action": { "type": "white_noise", "param": "slow", "label": "白噪音/呼吸灯" }
}
```

### `POST /api/interventions/<plan_id>/cancel`

教师取消本次 AI 干预。

### `POST /api/interventions/<plan_id>/override`

教师改为其他干预方式。

请求体：

```json
{ "action_type": "white_noise|story|game|light", "param": "manual", "label": "可选显示名称" }
```

### `POST /api/children/<child_id>/interventions`

教师立即发起真实干预。返回 `202 accepted` 只代表进入执行队列，不代表执行成功。

```json
{ "action_type": "white_noise|story|game|light", "param": "manual" }
```

### `GET|POST /api/device/interventions/<plan_id>/feedback`

执行程序或设备回传真实状态。`status` 为 `received|started|completed|failed|stopped`，可附带 `source` 和 `message`。只有 `completed` 会计入成功反馈图表。

当前执行映射：

- `white_noise`：启动 `breath_noise.py`，根据进程退出码回执。
- `story`：启动 `story_player.py`，根据进程退出码回执。
- `light`：打开 Flask 托管的 `/interventions/breathing-light`，页面回传启动、结束或摄像头失败。
- `game`：打开 Flask 托管的 `/interventions/gesture-drawing`，页面回传启动、结束或摄像头失败。

### `GET /api/device/interventions/<plan_id>/control`

浏览器型干预页面每隔一段时间轮询该接口。教师停止计划后，页面收到 `stop_requested: true`，会停止动画、释放摄像头并回传 `stopped`。

### `POST /api/interventions/<plan_id>/stop`

教师停止正在运行的本地音频进程，或请求关闭浏览器型干预页面，终态记录为 `stopped`，不会计入执行完成。

### `POST /api/runtime/stop-all`

教师端“停止全部干预”按钮调用。立即停止演示数据、全部音频进程和进行中的干预，并通知呼吸灯及小游戏页面关闭。

### 家长端

- `GET /api/parent/<child_id>/today-report`
- `GET /api/parent/<child_id>/sleep-growth`
- `GET /api/parent/<child_id>/ai-suggestions`
- `GET /api/parent/<child_id>/interactions`
- `POST /api/parent/<child_id>/feedback`

家长反馈请求体：

```json
{
  "body_condition": "正常",
  "last_night_sleep": "21:00-7:00，夜醒1次",
  "note": "今天有点鼻塞"
}
```

## 实时事件

当前实现使用 `GET /api/events` 的 SSE 实时流，浏览器端通过 `EventSource` 订阅。若后续切换为 WebSocket，事件名和 payload 可保持一致。

事件定义：

- `child_state_updated`：儿童实时状态更新，payload 为 `ChildSummary`。
- `ai_intervention_pending`：AI 即将执行干预，payload 为 `InterventionPlan`，包含 `deadline_ts`。
- `teacher_intervention_cancelled`：教师取消干预，payload 为 `InterventionPlan`。
- `teacher_intervention_overridden`：教师改写干预，payload 为 `InterventionPlan`。
- `ai_intervention_resolved`：干预计划已批准、改写或取消，不代表执行成功。
- `intervention_dispatched`：指令进入执行队列。
- `intervention_device_feedback`：执行端真实回执，含 `received|started|completed|failed`。
- `parent_feedback_submitted`：家长提交反馈，payload 为 `ParentFeedback`。
- `page_event`：儿童端页面打开/关闭事件。
- `demo_mode_started` / `demo_mode_stopped`：演示模式开关事件。
