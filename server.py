# -*- coding: utf-8 -*-
from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import dashscope
from dashscope import Generation
from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env(Path(__file__).resolve().parent.parent / ".env")


def react_frontend_or_none():
  index = FRONTEND_DIST / "index.html"
  if index.exists():
    return index.read_text(encoding="utf-8")
  return None

DEFAULT_CHILD_ID = "device-default"
MAX_HISTORY = 1000
LOCAL_INTERVENTION_CHILD_ID = os.getenv("LOCAL_INTERVENTION_CHILD_ID", "demo-015")

lock = threading.RLock()
intervention_cv = threading.Condition(lock)
event_subscribers: list[queue.Queue] = []

last_data = None
last_time = None
last_page_event = {"page": None, "event": None, "time": None, "id": 0}

children: dict[str, dict] = {}
sensor_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))
camera_observations: dict[str, deque] = defaultdict(lambda: deque(maxlen=120))
decision_profile_cache: dict[str, dict] = {}
sleep_records: dict[str, list] = defaultdict(list)
interactions: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))
parent_feedback: dict[str, list] = defaultdict(list)
interventions: dict[str, dict] = {}
running_processes: dict[str, subprocess.Popen] = {}
last_teacher_heartbeat: float | None = None
CLOUD_RUNTIME_ALWAYS_ON = os.getenv("CLOUD_RUNTIME_ALWAYS_ON", "0") == "1"
runtime_active = CLOUD_RUNTIME_ALWAYS_ON
runtime_pause_until = 0.0
active_sleep_starts: dict[str, float] = {}
last_auto_intervention_at: dict[tuple[str, str], float] = {}
users: dict[str, dict] = {}
sessions: dict[str, str] = {}
published_reports: dict[str, list] = defaultdict(list)
child_positions: dict[str, int] = {}

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()
DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "qwen-turbo").strip() or "qwen-turbo"
LLM_DECISION_INTERVAL_SECONDS = max(30, int(os.getenv("LLM_DECISION_INTERVAL_SECONDS", "120")))
dashscope.api_key = DASHSCOPE_API_KEY

STATE_FILE = Path(__file__).with_name("nap_app_state.json")


def load_persistent_state() -> None:
    if not STATE_FILE.exists():
        return
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        users.update(state.get("users") or {})
        child_positions.update({str(k): int(v) for k, v in (state.get("child_positions") or {}).items()})
        for child_id, reports in (state.get("published_reports") or {}).items():
            published_reports[child_id].extend(reports[-90:])
    except (OSError, ValueError, TypeError):
        pass


def save_persistent_state() -> None:
    state = {
        "users": users,
        "child_positions": child_positions,
        "published_reports": dict(published_reports),
    }
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_FILE)


load_persistent_state()

demo_stop_event = threading.Event()
demo_thread: threading.Thread | None = None


def now_ts() -> float:
    return time.time()


def iso(ts: float | None = None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_payload(data):
    if not isinstance(data, dict):
        return {}
    return {str(k).lower(): v for k, v in data.items()}


def child_id_from(data: dict | None) -> str:
    data = data or {}
    return str(
        data.get("child_id")
        or data.get("childid")
        or data.get("student_id")
        or data.get("device_id")
        or data.get("device")
        or DEFAULT_CHILD_ID
    )


def ensure_child(child_id: str, data: dict | None = None) -> dict:
    data = data or {}
    if child_id not in child_positions:
        child_positions[child_id] = len(child_positions)
    child = children.setdefault(
        child_id,
        {
            "id": child_id,
            "name": data.get("name") or data.get("child_name") or "未绑定儿童",
            "avatar": data.get("avatar") or "",
            "class_id": data.get("class_id") or "default-class",
            "state": "unknown",
            "emotion": "未知",
            "motion_frequency": None,
            "environment": {},
            "last_seen": None,
            "sleep_start": None,
            "wake_time": None,
            "sleep_quality": "暂无数据",
            "unread_parent_feedback_count": 0,
        },
    )
    if data.get("name") or data.get("child_name"):
        child["name"] = data.get("name") or data.get("child_name")
    if data.get("avatar"):
        child["avatar"] = data.get("avatar")
    if data.get("class_id"):
        child["class_id"] = data.get("class_id")
    return child


def public_user(user: dict | None) -> dict | None:
    if not user:
        return None
    return {
        "id": user["id"],
        "phone": user["phone"],
        "name": user["name"],
        "role": user["role"],
        "child_id": user.get("child_id"),
        "child_name": user.get("child_name"),
    }


def auth_user() -> dict | None:
    token = request.headers.get("Authorization", "").replace("Bearer ", "", 1).strip()
    user_id = sessions.get(token)
    user = users.get(user_id) if user_id else None
    if user:
        repair_parent_binding(user)
    return user


def is_bound_parent(child_id: str) -> bool:
    user = auth_user()
    return bool(user and user.get("role") == "parent" and user.get("child_id") == child_id)


def is_teacher() -> bool:
    user = auth_user()
    return bool(user and user.get("role") == "teacher")


def has_local_intervention_endpoint(child_id: str) -> bool:
    return child_id in {item["id"] for item in DEMO_CHILDREN} or child_id == LOCAL_INTERVENTION_CHILD_ID


def stop_active_runtime(reason: str = "teacher_console_closed") -> None:
    global runtime_active
    runtime_active = CLOUD_RUNTIME_ALWAYS_ON and reason != "teacher_stopped_all"
    stop_demo_mode()
    for plan_id, process in list(running_processes.items()):
        try:
            if process.poll() is None:
                process.terminate()
        except OSError:
            pass
        record_execution_feedback(plan_id, "stopped", {"source": "runtime", "reason": reason})
    for plan in list(interventions.values()):
        if plan.get("execution_status") in ("queued", "received", "started"):
            record_execution_feedback(plan["id"], "stopped", {"source": "runtime", "reason": reason})


def runtime_watchdog() -> None:
    while True:
        time.sleep(3)
        if CLOUD_RUNTIME_ALWAYS_ON:
            continue
        with lock:
            heartbeat = last_teacher_heartbeat
            should_stop = runtime_active and heartbeat is not None and now_ts() - heartbeat > 12
        if should_stop:
            stop_active_runtime()




def publish(event_type: str, payload: dict) -> None:
    event = {"type": event_type, "time": iso(now_ts()), "payload": payload}
    stale = []
    for subscriber in event_subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            stale.append(subscriber)
    for subscriber in stale:
        if subscriber in event_subscribers:
            event_subscribers.remove(subscriber)


def add_interaction(child_id: str, event_type: str, detail: dict) -> dict:
    item = {
        "id": uuid.uuid4().hex,
        "child_id": child_id,
        "type": event_type,
        "detail": detail,
        "time": iso(now_ts()),
    }
    interactions[child_id].appendleft(item)
    return item


def calculate_quality(child_id: str) -> str:
    samples = list(sensor_history[child_id])[:30]
    motion_values = [s.get("motion") for s in samples if isinstance(s.get("motion"), (int, float))]
    if not motion_values:
        return "暂无数据"
    avg_motion = sum(motion_values) / len(motion_values)
    if avg_motion < 120:
        return "平稳"
    if avg_motion < 480:
        return "一般"
    return "易醒"


def update_sleep_transition(child_id: str, old_state: str, new_state: str, ts: float) -> None:
    child = ensure_child(child_id)
    if new_state == "sleeping" and old_state != "sleeping":
        active_sleep_starts[child_id] = ts
        child["sleep_start"] = iso(ts)
        child["wake_time"] = None
    if old_state == "sleeping" and new_state != "sleeping":
        start_ts = active_sleep_starts.pop(child_id, None)
        if start_ts:
            record = {
                "id": uuid.uuid4().hex,
                "child_id": child_id,
                "sleep_start": iso(start_ts),
                "wake_time": iso(ts),
                "duration_seconds": max(0, int(ts - start_ts)),
                "quality": calculate_quality(child_id),
            }
            sleep_records[child_id].append(record)
            child["wake_time"] = record["wake_time"]
            child["sleep_quality"] = record["quality"]


def parse_environment(data: dict) -> dict:
    return {
        "temperature": data.get("temperature") or data.get("temp") or data.get("to"),
        "humidity": data.get("humidity"),
        "noise": data.get("noise") or data.get("mic"),
        "brightness": data.get("brightness") or data.get("light"),
        "heart_rate": data.get("hr"),
        "breath_rate": data.get("br"),
    }


BASE_DECISION_THRESHOLDS = {
    "sleep_motion_max": 45.0,
    "sleep_heart_rate_max": 90.0,
    "sleep_breath_rate_max": 22.0,
    "help_motion_min": 160.0,
    "help_heart_rate_min": 100.0,
    "help_breath_rate_min": 27.0,
    "help_noise_min": 70.0,
    "alarm_motion_min": 360.0,
    "alarm_heart_rate_min": 118.0,
    "alarm_breath_rate_min": 34.0,
    "alarm_noise_min": 85.0,
    "camera_help_ratio": 0.07,
    "camera_alarm_ratio": 0.16,
}


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_present(data: dict, *keys: str):
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def normalized_noise(value) -> float | None:
    parsed = number(value)
    if parsed is None:
        return None
    return parsed * 100 if 0 <= parsed <= 1 else parsed


def average(values: list) -> float | None:
    numeric = [number(value) for value in values]
    numeric = [value for value in numeric if value is not None]
    return round(sum(numeric) / len(numeric), 3) if numeric else None


def sensor_trend_summary(child_id: str, incoming: dict | None = None) -> dict:
    incoming = incoming or {}
    recent = list(sensor_history[child_id])[:30]

    def series(*keys: str) -> list:
        values = []
        for item in [incoming, *recent]:
            for key in keys:
                if item.get(key) is not None:
                    values.append(item[key])
                    break
            environment = item.get("environment") or {}
            if not any(item.get(key) is not None for key in keys):
                for key in keys:
                    if environment.get(key) is not None:
                        values.append(environment[key])
                        break
        return values

    camera = list(camera_observations[child_id])[:20]
    return {
        "sample_count": len(recent) + (1 if incoming else 0),
        "heart_rate_avg": average(series("hr", "heart_rate")),
        "breath_rate_avg": average(series("br", "breath_rate")),
        "motion_avg": average(series("motion", "motion_frequency")),
        "noise_avg": average([normalized_noise(value) for value in series("mic", "noise")]),
        "temperature_avg": average(series("temperature", "temp", "to")),
        "camera_motion_avg": average([item.get("motion_ratio") for item in camera]),
        "recent_gestures": [item.get("gesture") for item in camera if item.get("gesture") not in (None, "", "none")][:5],
    }


def parse_llm_json(text: str) -> dict:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM response does not contain a JSON object")
    value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM response is not a JSON object")
    return value


def call_llm_json(prompt: str) -> dict:
    if not DASHSCOPE_API_KEY:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")
    response = Generation.call(model=DASHSCOPE_MODEL, prompt=prompt)
    text = getattr(getattr(response, "output", None), "text", "")
    return parse_llm_json(text)


def llm_adjusted_thresholds(child_id: str, trend: dict) -> tuple[dict, dict]:
    cached = decision_profile_cache.get(child_id)
    if cached and now_ts() < cached["expires_at"]:
        return cached["thresholds"], cached["metadata"]

    thresholds = dict(BASE_DECISION_THRESHOLDS)
    metadata = {"source": "rules", "model": None, "trend": trend}
    if DASHSCOPE_API_KEY and trend.get("sample_count", 0) >= 3:
        prompt = f"""
You assist a kindergarten nap-monitoring prototype. Review the aggregated, non-identifying sensor trend below.
Return JSON only with: {{"multipliers": {{threshold_name: number}}, "reason": "short explanation"}}.
You may adjust only these thresholds by a multiplier between 0.85 and 1.15:
{json.dumps(BASE_DECISION_THRESHOLDS, ensure_ascii=False)}
Trend:
{json.dumps(trend, ensure_ascii=False)}
Do not diagnose illness. Prefer conservative changes and leave uncertain thresholds at 1.0.
""".strip()
        try:
            result = call_llm_json(prompt)
            multipliers = result.get("multipliers") or {}
            for key, base_value in BASE_DECISION_THRESHOLDS.items():
                multiplier = number(multipliers.get(key))
                if multiplier is not None:
                    thresholds[key] = round(base_value * min(1.15, max(0.85, multiplier)), 3)
            metadata = {
                "source": "llm",
                "model": DASHSCOPE_MODEL,
                "reason": str(result.get("reason") or "")[:240],
                "trend": trend,
            }
        except Exception as exc:
            metadata = {"source": "rules_fallback", "model": DASHSCOPE_MODEL, "error": type(exc).__name__, "trend": trend}

    decision_profile_cache[child_id] = {
        "thresholds": thresholds,
        "metadata": metadata,
        "expires_at": now_ts() + LLM_DECISION_INTERVAL_SECONDS,
    }
    return thresholds, metadata


def classify_sensor_state(child_id: str, payload: dict) -> tuple[str, dict]:
    trend = sensor_trend_summary(child_id, payload)
    thresholds, llm_metadata = llm_adjusted_thresholds(child_id, trend)
    heart_rate = number(first_present(payload, "hr", "heart_rate"))
    breath_rate = number(first_present(payload, "br", "breath_rate"))
    motion = number(first_present(payload, "motion", "motion_frequency"))
    noise = normalized_noise(first_present(payload, "mic", "noise"))
    camera_motion = trend.get("camera_motion_avg")

    measurements = [heart_rate, breath_rate, motion, noise, camera_motion]
    explicit_state = payload.get("state") or payload.get("status")
    if all(value is None for value in measurements):
        state = explicit_state or "unknown"
    elif (
        (heart_rate is not None and heart_rate >= thresholds["alarm_heart_rate_min"])
        or (breath_rate is not None and breath_rate >= thresholds["alarm_breath_rate_min"])
        or (motion is not None and motion >= thresholds["alarm_motion_min"])
        or (noise is not None and noise >= thresholds["alarm_noise_min"])
        or (camera_motion is not None and camera_motion >= thresholds["camera_alarm_ratio"])
    ):
        state = "alarm"
    elif (
        (heart_rate is not None and heart_rate >= thresholds["help_heart_rate_min"])
        or (breath_rate is not None and breath_rate >= thresholds["help_breath_rate_min"])
        or (motion is not None and motion >= thresholds["help_motion_min"])
        or (noise is not None and noise >= thresholds["help_noise_min"])
        or (camera_motion is not None and camera_motion >= thresholds["camera_help_ratio"])
    ):
        state = "need_help"
    elif (
        motion is not None
        and motion <= thresholds["sleep_motion_max"]
        and (heart_rate is None or heart_rate <= thresholds["sleep_heart_rate_max"])
        and (breath_rate is None or breath_rate <= thresholds["sleep_breath_rate_max"])
    ):
        state = "sleeping"
    elif motion is not None and motion < thresholds["help_motion_min"]:
        state = "sleepy"
    else:
        state = explicit_state or "calm_awake"

    return state, {
        **llm_metadata,
        "thresholds": thresholds,
        "classifier": "explicit-threshold-v1",
        "classified_state": state,
    }


def get_pending_intervention(child_id: str) -> dict | None:
    for plan in interventions.values():
        if plan["child_id"] == child_id and plan["status"] == "pending":
            return plan
    return None


def build_child_summary(child_id: str) -> dict:
    child = ensure_child(child_id)
    last_sample = sensor_history[child_id][0] if sensor_history[child_id] else {}
    duration_seconds = None
    if child.get("state") == "sleeping" and child_id in active_sleep_starts:
        duration_seconds = int(now_ts() - active_sleep_starts[child_id])
    pending = get_pending_intervention(child_id)
    child_plans = [plan for plan in interventions.values() if plan.get("child_id") == child_id and plan.get("execution_status")]
    latest_execution = child_plans[-1] if child_plans else None
    latest_report = published_reports[child_id][-1] if published_reports[child_id] else None
    if not latest_report:
        report_status = "not_published"
    elif latest_report.get("read_at"):
        report_status = "read"
    elif latest_report.get("delivered_at"):
        report_status = "delivered"
    else:
        report_status = "published"
    return {
        "id": child_id,
        "name": child.get("name"),
        "avatar": child.get("avatar"),
        "current_state": child.get("state"),
        "emotion": child.get("emotion"),
        "sleep_start": child.get("sleep_start"),
        "sleep_duration_seconds": duration_seconds,
        "last_seen": child.get("last_seen"),
        "environment": child.get("environment") or {},
        "motion_frequency": child.get("motion_frequency"),
        "seat_index": child_positions.get(child_id, 0),
        "execution_connected": has_local_intervention_endpoint(child_id),
        "execution_endpoint": "本机虚拟执行端" if has_local_intervention_endpoint(child_id) else None,
        "report_status": report_status,
        "latest_report": {
            "published_at": latest_report.get("published_at"),
            "delivered_at": latest_report.get("delivered_at"),
            "read_at": latest_report.get("read_at"),
            "recipient_count": latest_report.get("recipient_count", 0),
        } if latest_report else None,
        "priority": 0 if child.get("state") == "alarm" else 1,
        "unread_parent_feedback_count": child.get("unread_parent_feedback_count", 0),
        "pending_intervention": {
            "id": pending["id"],
            "label": pending["proposed_action"].get("label") or pending["proposed_action"].get("type"),
            "deadline_ts": pending["deadline_ts"],
            "action": pending["proposed_action"],
        } if pending else None,
        "latest_execution": {
            "plan_id": latest_execution.get("id"),
            "action": latest_execution.get("final_action") or latest_execution.get("proposed_action"),
            "status": latest_execution.get("execution_status"),
            "updated_at": latest_execution.get("execution_updated_at"),
            "feedback": latest_execution.get("execution_feedback"),
            "simulated": bool((latest_execution.get("execution_feedback") or {}).get("simulated")),
        } if latest_execution else None,
        "last_sample": last_sample,
    }


DEMO_CHILDREN = [
    {"id": "demo-001", "name": "小雨"},
    {"id": "demo-002", "name": "辰辰"},
    {"id": "demo-003", "name": "安安"},
    {"id": "demo-004", "name": "朵朵"},
    {"id": "demo-005", "name": "乐乐"},
    {"id": "demo-006", "name": "小朗"},
    {"id": "demo-007", "name": "小橙"},
    {"id": "demo-008", "name": "小河"},
    {"id": "demo-009", "name": "小贝"},
    {"id": "demo-010", "name": "小禾"},
    {"id": "demo-011", "name": "小羽"},
    {"id": "demo-012", "name": "小星"},
    {"id": "demo-013", "name": "小哲"},
    {"id": "demo-014", "name": "小然"},
    {"id": "demo-015", "name": "小晴"},
    {"id": "demo-016", "name": "小航"},
]


def ensure_class_roster() -> None:
    for index, info in enumerate(DEMO_CHILDREN):
        child = ensure_child(info["id"], info)
        child["name"] = info["name"]
        child_positions.setdefault(info["id"], index)


def resolve_child_binding(child_key: str = "", child_name: str = "") -> tuple[str, str] | None:
    key = (child_key or "").strip()
    name = (child_name or "").strip()
    candidates = DEMO_CHILDREN + [
        {"id": child_id, "name": child.get("name")}
        for child_id, child in children.items()
        if child_id not in {item["id"] for item in DEMO_CHILDREN}
    ]
    for candidate in candidates:
        if key and key in (candidate["id"], candidate.get("name")):
            return candidate["id"], candidate.get("name") or candidate["id"]
    for candidate in candidates:
        if name and name == candidate.get("name"):
            return candidate["id"], candidate.get("name") or candidate["id"]
    if key and key != DEFAULT_CHILD_ID:
        child = ensure_child(key, {"child_name": name or None})
        return key, child.get("name") or key
    return None

def repair_parent_binding(user: dict) -> None:
    if user.get("role") != "parent":
        return
    current_id = user.get("child_id") or ""
    if current_id != DEFAULT_CHILD_ID:
        return
    resolved = resolve_child_binding("", user.get("child_name") or "")
    if resolved:
        user["child_id"], user["child_name"] = resolved
        save_persistent_state()


DEFAULT_TEACHER_PHONE = "13800000000"
DEFAULT_PARENT_PHONE = "13900000015"
DEFAULT_PASSWORD = "123456"


def seed_default_accounts() -> None:
    changed = False
    defaults = [
        {"phone": DEFAULT_TEACHER_PHONE, "name": "演示教师", "role": "teacher", "child_id": None, "child_name": None},
        {"phone": DEFAULT_PARENT_PHONE, "name": "小晴家长", "role": "parent", "child_id": "demo-015", "child_name": "小晴"},
    ]
    for account in defaults:
        exists = any(user.get("phone") == account["phone"] and user.get("role") == account["role"] for user in users.values())
        if exists:
            continue
        user_id = uuid.uuid4().hex
        users[user_id] = {
            "id": user_id,
            "phone": account["phone"],
            "password_hash": generate_password_hash(DEFAULT_PASSWORD),
            "role": account["role"],
            "name": account["name"],
            "child_id": account["child_id"],
            "child_name": account["child_name"],
        }
        changed = True
    if changed:
        save_persistent_state()


seed_default_accounts()


def demo_action_for_state(state: str) -> dict:
    if state == "sleeping":
        return {"type": "white_noise", "param": "steady", "label": "白噪声", "source": "demo"}
    if state == "sleepy":
        return {"type": "story", "param": "soft", "label": "睡前故事", "source": "demo"}
    if state == "need_help":
        return {"type": "light", "param": "breathing", "label": "呼吸灯", "source": "demo"}
    if state == "calm_awake":
        return {"type": "game", "param": "gesture", "label": "手势小游戏", "source": "demo"}
    if state == "alarm":
        return {"type": "teacher_alert", "param": "alert", "label": "教师提醒", "source": "demo"}
    return {"type": "none", "label": "无需干预", "source": "demo"}


ACTION_LABELS = {
    "white_noise": "白噪声",
    "light": "呼吸灯",
    "game": "手势小游戏",
    "story": "睡前故事",
    "teacher_alert": "教师提醒",
}


REPORT_INTERVENTION_EVENTS = {
    "ai_intervention_pending",
    "teacher_manual_intervention",
    "intervention_dispatched",
    "intervention_device_feedback",
    "teacher_cancelled_intervention",
    "teacher_overrode_intervention",
}


def visible_intervention_events(child_id: str, limit: int = 100) -> list[dict]:
    return [
        event for event in list(interactions[child_id])[:limit]
        if event.get("type") in REPORT_INTERVENTION_EVENTS
        and (event.get("detail") or {}).get("action")
    ]


def record_execution_feedback(plan_id: str, status: str, detail: dict | None = None) -> dict | None:
    detail = detail or {}
    with lock:
        plan = interventions.get(plan_id)
        if not plan:
            return None
        current = plan.get("execution_status")
        if current in ("completed", "failed", "stopped", "cancelled"):
            return plan
        plan["execution_status"] = status
        plan["execution_updated_at"] = iso(now_ts())
        plan["execution_feedback"] = {**detail, "status": status, "time": plan["execution_updated_at"]}
        event = add_interaction(
            plan["child_id"],
            "intervention_device_feedback",
            {"plan_id": plan_id, "status": status, "action": plan.get("final_action") or plan.get("proposed_action"), **detail},
        )
    publish("intervention_device_feedback", {"plan": plan, "feedback": event})
    return plan


def monitor_local_process(plan_id: str, process: subprocess.Popen, max_duration: int) -> None:
    running_processes[plan_id] = process
    record_execution_feedback(plan_id, "started", {"source": "local_process", "pid": process.pid})
    try:
        return_code = process.wait(timeout=max_duration)
        if return_code == 0:
            record_execution_feedback(plan_id, "completed", {"source": "local_process", "return_code": return_code})
        else:
            record_execution_feedback(plan_id, "failed", {"source": "local_process", "return_code": return_code})
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        record_execution_feedback(plan_id, "completed", {"source": "local_process", "reason": "scheduled_duration_complete"})
    finally:
        running_processes.pop(plan_id, None)


def monitor_browser_intervention(plan_id: str, timeout_seconds: int) -> None:
    time.sleep(timeout_seconds)
    with lock:
        plan = interventions.get(plan_id)
        status = plan.get("execution_status") if plan else None
    if status not in ("completed", "failed"):
        record_execution_feedback(plan_id, "failed", {"source": "browser_page", "reason": "feedback_timeout"})


def run_intervention(plan_id: str) -> None:
    with lock:
        plan = interventions.get(plan_id)
        action = (plan or {}).get("final_action") or (plan or {}).get("proposed_action") or {}
    if not plan:
        return
    if not runtime_active:
        record_execution_feedback(
            plan_id,
            "failed",
            {"source": "runtime", "reason": "teacher_console_closed", "message": "教师页面已关闭"},
        )
        return
    if not has_local_intervention_endpoint(plan["child_id"]):
        record_execution_feedback(
            plan_id,
            "failed",
            {"source": "dispatcher", "reason": "execution_endpoint_not_connected", "message": "该孩子未连接执行端"},
        )
        return
    action_type = action.get("type")
    parameter = str(action.get("param") or "normal")
    base_dir = Path(__file__).resolve().parent
    local_port = os.getenv("PORT", "5000")
    control_base_url = f"http://127.0.0.1:{local_port}"
    try:
        if action_type in ("white_noise", "light"):
            script = base_dir / "breath_noise.py"
            process = subprocess.Popen(
                [sys.executable, str(script), parameter],
                cwd=str(base_dir),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            url = f"{control_base_url}/interventions/breathing-light?plan_id={plan_id}&child_id={plan['child_id']}&action={action_type}"
            if not webbrowser.open(url, new=1):
                process.terminate()
                record_execution_feedback(plan_id, "failed", {"source": "browser_page", "reason": "browser_open_failed"})
                return
            threading.Thread(target=monitor_browser_intervention, args=(plan_id, 45), daemon=True).start()
            monitor_local_process(plan_id, process, 120)
            return
        if action_type == "story":
            script = base_dir / "story_player.py"
            process = subprocess.Popen(
                [sys.executable, str(script), parameter],
                cwd=str(base_dir),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            monitor_local_process(plan_id, process, 90)
            return
        if action_type in ("light", "game"):
            page_route = "breathing-light" if action_type == "light" else "gesture-drawing"
            url = f"{control_base_url}/interventions/{page_route}?plan_id={plan_id}&child_id={plan['child_id']}&action={action_type}"
            if not webbrowser.open(url, new=1):
                record_execution_feedback(plan_id, "failed", {"source": "browser_page", "reason": "browser_open_failed"})
                return
            record_execution_feedback(plan_id, "started", {"source": "browser_page"})
            threading.Thread(target=monitor_browser_intervention, args=(plan_id, 75), daemon=True).start()
            return
        record_execution_feedback(plan_id, "failed", {"source": "dispatcher", "reason": "unsupported_action"})
    except Exception as exc:
        record_execution_feedback(plan_id, "failed", {"source": "dispatcher", "reason": type(exc).__name__, "message": str(exc)[:200]})


def dispatch_intervention(plan: dict) -> None:
    plan["execution_status"] = "queued"
    plan["execution_updated_at"] = iso(now_ts())
    plan["execution_feedback"] = None
    add_interaction(
        plan["child_id"],
        "intervention_dispatched",
        {"plan_id": plan["id"], "status": "queued", "action": plan.get("final_action") or plan.get("proposed_action")},
    )
    publish("intervention_dispatched", plan)
    record_execution_feedback(plan["id"], "queued", {"source": "dispatcher", "reason": "intervention_triggered"})
    threading.Thread(target=run_intervention, args=(plan["id"],), daemon=True).start()


def resolve_demo_intervention_later(plan_id: str) -> None:
    time.sleep(5)
    with intervention_cv:
        plan = interventions.get(plan_id)
        if not plan or plan["status"] != "pending":
            return
        plan["status"] = "auto_approved"
        plan["final_action"] = plan["proposed_action"]
        plan["resolved_at"] = iso(now_ts())
        add_interaction(plan["child_id"], "ai_intervention_resolved", {"plan_id": plan_id, "status": plan["status"], "action": plan["final_action"]})
        publish("ai_intervention_resolved", plan)
        intervention_cv.notify_all()
    if has_local_intervention_endpoint(plan["child_id"]):
        with lock:
            dispatch_intervention(plan)
    else:
        record_execution_feedback(plan_id, "completed", {"source": "demo_simulator", "simulated": True})


def create_demo_intervention(child_id: str, state: str, decision_metadata: dict | None = None) -> dict | None:
    action = demo_action_for_state(state)
    if action["type"] == "none":
        return None
    existing = any(
        p["child_id"] == child_id
        and (p["status"] == "pending" or p.get("execution_status") in ("queued", "received", "started"))
        for p in interventions.values()
    )
    if existing:
        return None
    ts = now_ts()
    child = ensure_child(child_id)
    plan_id = uuid.uuid4().hex
    plan = {
        "id": plan_id,
        "child_id": child_id,
        "child_name": child.get("name"),
        "state": state,
        "proposed_action": action,
        "final_action": None,
        "llm_result": decision_metadata or {"source": "rules"},
        "status": "pending",
        "created_at": iso(ts),
        "deadline_ts": ts + 5,
        "resolved_at": None,
        "demo": True,
        "origin": "demo",
        "execution_status": "awaiting_approval",
        "execution_updated_at": iso(ts),
        "execution_feedback": None,
    }
    interventions[plan_id] = plan
    add_interaction(child_id, "ai_intervention_pending", {"plan_id": plan_id, "action": action})
    publish("ai_intervention_pending", plan)
    threading.Thread(target=resolve_demo_intervention_later, args=(plan_id,), daemon=True).start()
    return plan


def maybe_create_ai_intervention(
    child_id: str,
    state: str,
    source: str = "state_monitor",
    decision_metadata: dict | None = None,
) -> dict | None:
    if state not in ("sleepy", "need_help", "alarm"):
        return None
    key = (child_id, state)
    ts = now_ts()
    last_ts = last_auto_intervention_at.get(key, 0)
    if ts - last_ts < 120:
        return None
    plan = create_demo_intervention(child_id, state, decision_metadata)
    if plan:
        plan["origin"] = source
        plan["llm_result"] = {
            **(decision_metadata or {}),
            "pipeline_source": source,
            "trigger_state": state,
        }
        last_auto_intervention_at[key] = ts
    return plan


def seed_demo_sleep_record(child_id: str) -> None:
    if sleep_records[child_id]:
        return
    for offset in range(5, 0, -1):
        wake_ts = now_ts() - offset * 86400 - random.randint(600, 2400)
        start_ts = wake_ts - random.randint(2400, 5600)
        sleep_records[child_id].append(
            {
                "id": uuid.uuid4().hex,
                "child_id": child_id,
                "sleep_start": iso(start_ts),
                "wake_time": iso(wake_ts),
                "duration_seconds": int(wake_ts - start_ts),
                "quality": random.choice(["平稳", "一般", "易醒"]),
                "demo": True,
            }
        )


def demo_tick() -> None:
    states = ["sleeping", "sleepy", "need_help", "calm_awake", "alarm"]
    weights = [0.46, 0.2, 0.17, 0.11, 0.06]
    profiles = {
        "sleeping": {"heart_rate": (68, 88), "breath_rate": (14, 22), "motion": (2, 35), "emotions": ["平静", "熟睡"]},
        "sleepy": {"heart_rate": (75, 96), "breath_rate": (16, 24), "motion": (35, 120), "emotions": ["困倦", "平静"]},
        "need_help": {"heart_rate": (88, 116), "breath_rate": (22, 32), "motion": (120, 360), "emotions": ["轻微不安", "需要安抚"]},
        "calm_awake": {"heart_rate": (78, 102), "breath_rate": (18, 27), "motion": (50, 190), "emotions": ["清醒", "平静"]},
        "alarm": {"heart_rate": (106, 136), "breath_rate": (28, 40), "motion": (320, 650), "emotions": ["明显不安", "哭闹"]},
    }
    with lock:
        classroom_temperature = round(random.uniform(24.6, 25.8), 1)
        classroom_humidity = random.randint(48, 58)
        classroom_noise = round(random.uniform(0.12, 0.34), 2)
        classroom_brightness = random.randint(18, 72)
        for info in DEMO_CHILDREN:
            child_id = info["id"]
            child = ensure_child(child_id, info)
            old_state = child.get("state", "unknown")
            if old_state == "unknown":
                state = random.choices(states, weights=weights, k=1)[0]
            elif random.random() < 0.01:
                state = random.choices(states, weights=weights, k=1)[0]
            else:
                state = old_state
            ts = now_ts()
            profile = profiles[state]
            env = {
                "temperature": round(classroom_temperature + random.uniform(-0.2, 0.2), 1),
                "humidity": classroom_humidity + random.randint(-2, 2),
                "noise": round(max(0.05, classroom_noise + random.uniform(-0.04, 0.04)), 2),
                "brightness": max(8, classroom_brightness + random.randint(-8, 8)),
                "heart_rate": random.randint(*profile["heart_rate"]),
                "breath_rate": random.randint(*profile["breath_rate"]),
            }
            motion = random.randint(*profile["motion"])
            child.update(
                {
                    "name": info["name"],
                    "state": state,
                    "emotion": random.choice(profile["emotions"]),
                    "motion_frequency": motion,
                    "environment": env,
                    "last_seen": iso(ts),
                }
            )
            update_sleep_transition(child_id, old_state, state, ts)
            if state == "sleeping" and (old_state != "sleeping" or child_id not in active_sleep_starts):
                simulated_elapsed = random.randint(20 * 60, 95 * 60)
                active_sleep_starts[child_id] = ts - simulated_elapsed
                child["sleep_start"] = iso(active_sleep_starts[child_id])
            seed_demo_sleep_record(child_id)
            sample = {
                "time": iso(ts),
                "child_id": child_id,
                "state": state,
                "hr": env["heart_rate"],
                "br": env["breath_rate"],
                "mic": env["noise"],
                "motion": motion,
                "environment": env,
                "demo": True,
            }
            sensor_history[child_id].appendleft(sample)
            add_interaction(child_id, "demo_sensor_update", sample)
            publish("child_state_updated", build_child_summary(child_id))
            maybe_create_ai_intervention(child_id, state, "demo_state_monitor")


def demo_loop() -> None:
    while not demo_stop_event.is_set():
        demo_tick()
        demo_stop_event.wait(4)


def start_demo_mode() -> bool:
    global demo_thread
    with lock:
        if demo_thread and demo_thread.is_alive():
            return False
        demo_stop_event.clear()
        demo_tick()
        demo_thread = threading.Thread(target=demo_loop, daemon=True)
        demo_thread.start()
    publish("demo_mode_started", {"enabled": True})
    return True


def stop_demo_mode() -> bool:
    demo_stop_event.set()
    publish("demo_mode_stopped", {"enabled": False})
    return True


def demo_mode_enabled() -> bool:
    return bool(demo_thread and demo_thread.is_alive() and not demo_stop_event.is_set())


def dashboard_html(title: str, root_id: str, script: str, body_class: str = "") -> str:
    subtitle = "每日午睡报告 · 作息建议 · 历史记录" if body_class == "parent-page" else "班级午睡管理 · 实时状态 · 干预确认"
    modal_close = "closeParentDialog(event)" if body_class == "parent-page" else "closeChildModal(event)"
    stop_control = '<button id="runtime-toggle-btn" class="primary" onclick="toggleTeacherRuntime()">午睡监护：开</button><button class="emergency-stop" onclick="confirmStopAllInterventions()">停止全部干预</button>' if body_class == "teacher-page" else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#4a755c">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="{title}">
  <link rel="manifest" href="/manifest.webmanifest?app={'parent' if body_class == 'parent-page' else 'teacher'}">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg:#f6f2e6; --paper:#fffaf1; --panel:#f7f2e7; --ink:#2a342d; --muted:#717b6f;
      --line:#e3d9cb; --green:#6b9d78; --green-dark:#3f6d4f; --mint:#d7e5d2;
      --blue:#4c7e72; --amber:#c7a255; --red:#c34f4f; --purple:#7a6588; --teal:#4c7f75;
      --shadow:0 12px 30px rgba(35, 46, 36, .08);
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif; background-image:radial-gradient(circle at 12% 12%, rgba(108, 135, 106,0.10), transparent 18%); }}
    header {{ padding:22px 28px 8px; display:flex; justify-content:space-between; gap:16px; align-items:flex-start; max-width:1240px; margin:auto; }}
    h1 {{ margin:0; font-size:26px; letter-spacing:0; }}
    h2 {{ margin:0 0 14px; font-size:18px; }}
    h3 {{ margin:16px 0 8px; font-size:14px; color:var(--muted); }}
    main {{ padding:12px 28px 32px; display:grid; gap:18px; max-width:1240px; margin:auto; }}
    .grid {{ display:grid; grid-template-columns:repeat(12, minmax(0, 1fr)); gap:18px; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:22px; box-shadow:var(--shadow); }}
    .span-3 {{ grid-column:span 3; }} .span-4 {{ grid-column:span 4; }} .span-5 {{ grid-column:span 5; }} .span-6 {{ grid-column:span 6; }} .span-7 {{ grid-column:span 7; }} .span-8 {{ grid-column:span 8; }} .span-12 {{ grid-column:span 12; }}
    .muted {{ color:var(--muted); font-size:13px; line-height:1.6; }}
    .hero {{ background:#eef2e8; border:1px solid #dde4d8; color:var(--ink); overflow:hidden; position:relative; }}
    .hero::after {{ content:""; position:absolute; width:180px; height:180px; right:-20px; top:-30px; border-radius:50%; background:rgba(111, 144, 116, .14); }}
    .hero-content {{ position:relative; z-index:1; display:flex; justify-content:space-between; align-items:flex-start; gap:18px; flex-wrap:wrap; }}
    .hero-title {{ font-size:26px; font-weight:800; }}
    .hero-sub {{ margin-top:8px; opacity:.75; max-width:560px; }}
    .hero-rate {{ text-align:right; font-size:36px; font-weight:900; color:var(--green-dark); }}
    .metric-grid {{ margin-top:24px; display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:14px; position:relative; z-index:1; }}
    .metric-card {{ background:#ffffff; border:1px solid var(--line); border-radius:14px; padding:18px; min-height:88px; }}
    .metric {{ font-size:28px; font-weight:800; margin-top:8px; color:var(--ink); }}
    .state {{ display:inline-flex; align-items:center; justify-content:center; min-width:80px; padding:6px 12px; border-radius:999px; font-size:12px; font-weight:700; background:#ece8e1; color:var(--ink); }}
    .state.sleeping {{ background:#d7e7d9; color:#3f6d4f; }} .state.sleepy {{ background:#e1ebe4; color:#4c7f75; }} .state.need_help {{ background:#f5ede2; color:#7a611d; }} .state.calm_awake {{ background:#ece8e1; color:#5e6a67; }} .state.alarm {{ background:#f2d9d9; color:#8c3f3f; }} .state.unknown {{ background:#ece8e1; color:#5e6a67; }}
    .legend {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }}
    .legend span {{ display:inline-flex; align-items:center; gap:8px; font-size:12px; color:var(--muted); }}
    .dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; background:#b2b7a8; }}
    .nap-map {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:14px; }}
    .kid-tile {{ border:1px solid #dde4d8; background:#f9f6f0; border-radius:14px; height:194px; overflow:hidden; padding:14px 12px; display:grid; place-items:center; align-content:center; text-align:center; cursor:pointer; transition:box-shadow .18s ease, border-color .18s ease, background .18s ease; }}
    .kid-content {{ display:grid; place-items:center; align-content:center; min-width:0; max-width:100%; transition:transform .18s ease; will-change:transform; }}
    .kid-tile:hover {{ border-color:#9fb7a3; box-shadow:0 12px 24px rgba(40, 54, 42, .08), 0 0 0 2px rgba(74, 117, 92, .10); }}
    .kid-tile:hover .kid-content {{ transform:translateY(-3px); }}
    .kid-tile[draggable="true"] {{ cursor:grab; outline:1px dashed #6b9d78; }}
    .kid-tile[draggable="true"]:active {{ cursor:grabbing; opacity:.72; }}
    .kid-tile.selected {{ outline:2px solid rgba(63, 109, 79, .18); box-shadow:0 0 0 1px rgba(63, 109, 79, .12); }}
    .kid-tile.sleeping {{ border-color:#9bc2a4; background:#edf6ec; }}
    .kid-tile.sleepy {{ border-color:#aac5d5; background:#eef5f9; }}
    .kid-tile.need_help {{ border-color:#d7c39d; background:#faf3e7; }}
    .kid-tile.calm_awake {{ border-color:#d7d3cd; background:#f6f2ed; }}
    .kid-tile.alarm {{ border-color:#d7b3b3; background:#f7e7e7; }}
    .tile-icon {{ width:32px; height:32px; border-radius:50%; display:grid; place-items:center; font-weight:900; color:#ffffff; margin-bottom:8px; background:var(--green-dark); }}
    .pending-banner {{ margin-top:12px; display:flex; justify-content:space-between; align-items:center; gap:8px; padding:8px 10px; border-radius:12px; background:rgba(255,255,255,0.9); border:1px solid rgba(211,79,79,.15); }}
    .pending-banner span {{ font-size:12px; color:#8c3f3f; }}
    .cancel-btn {{ border:1px solid #d7b3b3; background:#fee8e8; color:#8c3f3f; border-radius:10px; padding:6px 10px; font-size:12px; cursor:pointer; }}
    .tile-name {{ font-weight:800; font-size:15px; }}
    .tile-time {{ margin-top:6px; font-size:13px; color:var(--muted); }}
    .connection-check {{ width:24px; height:24px; display:grid; place-items:center; border-radius:50%; background:#d7e7d9; color:#3f6d4f; font-weight:900; font-size:14px; }}
    .detail-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap; }}
    .close-like {{ border:0; background:transparent; font-size:22px; padding:0; color:#55615a; cursor:pointer; }}
    .stat-row {{ display:grid; grid-template-columns:1fr auto; gap:10px; padding:14px; border-radius:14px; background:#f4efe8; margin-top:12px; }}
    .bars {{ min-height:120px; display:flex; align-items:end; gap:8px; padding:14px; border-radius:14px; background:#f4efe8; }}
    .bar {{ flex:1; min-height:12px; border-radius:6px 6px 0 0; background:#6b9d78; }}
    .action-bars {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:12px; margin-top:12px; }}
    .action-bar {{ min-height:132px; display:grid; grid-template-rows:1fr auto auto; align-items:end; gap:8px; padding:12px; border-radius:14px; background:#f4efe8; text-align:center; }}
    .action-fill {{ width:100%; min-height:8px; border-radius:10px 10px 4px 4px; background:#4a755c; }}
    .action-name {{ color:var(--muted); font-size:12px; }}
    .action-count {{ font-weight:900; }}
    .list {{ display:grid; gap:12px; }}
    .item {{ border:1px solid var(--line); border-radius:14px; padding:14px; background:#fcfaf6; }}
    .item.alarm {{ border-left:4px solid var(--red); }} .item.need_help {{ border-left:4px solid var(--amber); }}
    button, select, input, textarea {{ font:inherit; }}
    button {{ border:1px solid var(--line); background:#f7f3ed; color:var(--ink); border-radius:12px; padding:11px 14px; cursor:pointer; transition:background .16s ease, transform .16s ease; }}
    button:hover {{ background:#efeadf; }}
    button.primary {{ background:#4a755c; color:#fff; border-color:transparent; }} button.danger {{ background:#b34f4f; color:#fff; border-color:transparent; }} button.soft {{ background:#e6efe5; color:#3f6d4f; border-color:transparent; }}
    .emergency-stop {{ background:#fff4ef; color:#9a3412; border-color:#f4c7b1; }}
    input, textarea, select {{ width:100%; border:1px solid var(--line); border-radius:12px; padding:12px 14px; background:#fffdfa; color:var(--ink); }}
    textarea {{ min-height:100px; resize:vertical; }}
    .row {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
    .action-grid {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; }}
    .action-btn {{ min-height:96px; display:grid; place-items:center; gap:10px; text-align:center; background:#f7f3ed; border:1px solid #e4dbd0; border-radius:14px; color:var(--ink); }}
    .action-dot {{ width:38px; height:38px; border-radius:50%; color:#fff; display:grid; place-items:center; font-weight:900; background:#4c7f75; }}
    .unread-badge {{ position:absolute; top:10px; right:10px; min-width:22px; height:22px; padding:0 6px; border-radius:999px; background:#ef4444; color:#fff; font-size:12px; font-weight:700; display:grid; place-items:center; box-shadow:0 2px 8px rgba(0,0,0,.12); }}
    .kid-tile {{ position:relative; }}
    .ai-box {{ margin-top:18px; padding:18px; border-radius:14px; background:#f4efe8; border:1px solid #e3d9cb; }}
    .countdown {{ font-size:22px; font-weight:900; color:#8c3f3f; }}
    .toast {{ position:fixed; right:24px; top:24px; z-index:80; display:none; min-width:260px; max-width:420px; padding:14px 16px; border-radius:14px; background:#eef4e9; color:#34523b; box-shadow:var(--shadow); border:1px solid #d8e1d6; }}
    .header-right {{ display:flex; align-items:center; gap:12px; }}
    .language-toggle {{ min-width:54px; padding:8px 11px; font-size:12px; font-weight:800; }}
    .emergency-stop {{ padding:7px 10px; border-radius:8px; border-color:#d7b3b3; background:#fff0f0; color:#9b3434; font-size:12px; font-weight:800; }}
    .hidden {{ display:none !important; }}
    .modal-overlay {{ position:fixed; inset:0; display:flex; align-items:center; justify-content:center; padding:24px; background:rgba(16, 31, 24, .42); opacity:0; pointer-events:none; transition:opacity .18s ease; z-index:98; }}
    .modal-overlay.active {{ opacity:1; pointer-events:auto; }}
    .modal-card {{ position:relative; width:100%; max-width:820px; max-height:calc(100vh - 80px); overflow:auto; scrollbar-width:none; -ms-overflow-style:none; background:#fffdf8; border:1px solid var(--line); border-radius:22px; padding:26px 64px 26px 26px; box-shadow:0 28px 80px rgba(15, 35, 24, .16); }}
    .modal-card::-webkit-scrollbar {{ display:none; width:0; height:0; }}
    .modal-card::before {{ content:""; position:absolute; inset:0; border-radius:22px; pointer-events:none; box-shadow:0 0 0 1px rgba(255,255,255,.18) inset; }}
    .modal-close {{ position:absolute; z-index:3; top:12px; right:12px; width:38px; height:38px; display:grid; place-items:center; padding:0; border:1px solid var(--line); border-radius:50%; background:#fffdf8; color:var(--ink); font-size:22px; line-height:1; cursor:pointer; }}
    .panel-map {{ min-height:74vh; padding:24px; }}
    .nap-map {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:18px; }}
    body.teacher-page main {{ max-width:none; }}
    body.parent-page {{ background:#e9efe8; }}
    body.parent-page header {{ max-width:430px; padding:14px 16px 6px; }}
    body.parent-page h1 {{ font-size:18px; }}
    body.parent-page main {{ max-width:430px; min-height:calc(100vh - 72px); padding:8px 14px 92px; display:block; }}
    body.parent-page .header-right {{ display:flex; }}
    .phone-app {{ display:grid; gap:14px; }}
    .app-hero {{ border-radius:26px; padding:22px; color:#f8fbf5; background:linear-gradient(135deg,#315f4a,#7b8f6b); box-shadow:0 18px 36px rgba(47, 80, 59, .18); }}
    .app-hero-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:14px; }}
    .app-child {{ font-size:24px; font-weight:900; }}
    .app-status {{ padding:7px 10px; border-radius:999px; background:rgba(255,255,255,.18); font-size:12px; font-weight:800; white-space:nowrap; }}
    .app-quality {{ margin-top:18px; display:flex; align-items:end; justify-content:space-between; gap:12px; }}
    .app-quality strong {{ display:block; font-size:34px; line-height:1; }}
    .app-quality span {{ display:block; margin-top:6px; opacity:.82; font-size:13px; }}
    .app-card {{ background:#fffdf8; border:1px solid #dde5d9; border-radius:22px; padding:18px; box-shadow:0 10px 24px rgba(47, 68, 50, .08); }}
    .app-card h2 {{ margin-bottom:12px; font-size:16px; }}
    .app-metrics {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
    .app-metric {{ min-height:78px; padding:14px; border-radius:18px; background:#f3f6ef; }}
    .app-metric b {{ display:block; margin-top:7px; font-size:19px; }}
    .app-feed {{ display:grid; gap:10px; }}
    .app-feed .item {{ border-radius:16px; background:#f8f6f0; }}
    .app-inputs {{ display:grid; gap:10px; }}
    .auth-card {{ margin-top:18px; display:grid; gap:12px; }}
    .auth-switch {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
    .auth-switch button.active {{ background:#dfeadb; color:#315f4a; font-weight:900; }}
    .bottom-tabs {{ position:fixed; left:50%; bottom:12px; transform:translateX(-50%); width:min(402px, calc(100vw - 28px)); display:grid; grid-template-columns:repeat(2, 1fr); gap:8px; padding:8px; border-radius:24px; background:rgba(255,253,248,.94); border:1px solid #dce5da; box-shadow:0 18px 40px rgba(31,48,34,.18); z-index:60; }}
    .bottom-tabs button {{ border:0; border-radius:18px; padding:10px 8px; background:transparent; font-size:12px; font-weight:800; }}
    .bottom-tabs button.active {{ background:#dfeadb; color:#315f4a; }}
    .app-screen {{ display:none; }}
    .app-screen.active {{ display:block; }}
    .panel, .metric-card, .kid-tile, .item, .app-card, .action-btn, .stat-row, .bars, .action-bar, .ai-box {{ border-radius:16px; }}
    button, input, textarea, select {{ border-radius:12px; }}
    html.lang-en body {{ font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif; }}
    html.lang-en h1 {{ letter-spacing:-.02em; }}
    html.lang-en .header-right {{ flex-wrap:wrap; justify-content:flex-end; }}
    html.lang-en .state {{ min-width:0; white-space:normal; text-align:center; }}
    html.lang-en .app-status {{ white-space:normal; text-align:center; }}
    html.lang-en .app-hero-top {{ align-items:stretch; }}
    html.lang-en .bottom-tabs button {{ min-height:42px; }}
    @media (max-width: 980px) {{ header, main {{ padding-left:14px; padding-right:14px; }} .grid, .metric-grid {{ display:block; }} .panel, .metric-card {{ margin-bottom:14px; }} .action-grid {{ grid-template-columns:1fr; }} .panel-map {{ min-height:auto; padding:18px; }} }}
  </style>
</head>
<body class="{body_class}">
  <div class="toast" id="toast"></div>
  <header><div><h1>{title}</h1><div class="muted">{subtitle}</div></div><div class="header-right">{stop_control}<button type="button" id="language-toggle-btn" class="language-toggle soft" onclick="toggleLanguage(event)">EN</button><div class="muted" id="clock"></div></div></header>
  <main id="{root_id}"></main>
  <div id="child-modal" class="modal-overlay hidden" onclick="{modal_close}"></div>
  <script>
    let uiLanguage = localStorage.getItem('nap_language') || 'zh';
    const fmtTime = v => v ? new Date(v).toLocaleTimeString(uiLanguage === 'en' ? 'en-US' : 'zh-CN', {{ hour:'2-digit', minute:'2-digit' }}) : '-';
    const fmtDateTime = v => v ? new Date(v).toLocaleString(uiLanguage === 'en' ? 'en-US' : 'zh-CN') : '-';
    const fmtDur = s => s == null ? '-' : Number(s) < 60 ? (uiLanguage === 'en' ? 'Under 1 min' : '不足1分钟') : uiLanguage === 'en' ? `${{Math.floor(s/3600)}}h ${{Math.floor((s%3600)/60)}}m` : `${{Math.floor(s/3600)}}小时${{Math.floor((s%3600)/60)}}分`;
    const stateText = s => uiLanguage === 'en' ? ({{unknown:'Unknown', sleeping:'Sleeping', sleepy:'Sleepy', need_help:'Soothing', calm_awake:'Awake', alarm:'Alarm'}}[s] || s || 'Unknown') : ({{unknown:'未知', sleeping:'已入睡', sleepy:'浅睡/困倦', need_help:'需安抚', calm_awake:'清醒', alarm:'异常'}}[s] || s || '未知');
    const stateIcon = s => ({{sleeping:'☾', sleepy:'▰', need_help:'⚡', calm_awake:'◉', alarm:'!'}}[s] || '?');
    const stateColor = s => ({{sleeping:'#16a34a', sleepy:'#3b82f6', need_help:'#f59e0b', calm_awake:'#94a3b8', alarm:'#ef4444'}}[s] || '#94a3b8');
    const eventLabel = t => ({{
      parent_feedback: '家长反馈',
      ai_intervention_pending: 'AI建议已生成',
      ai_intervention_resolved: 'AI干预已处理',
      teacher_cancelled_intervention: '教师已取消干预',
      teacher_overrode_intervention: '教师已改写干预',
      teacher_manual_intervention: '教师手动发起干预',
      intervention_dispatched: '干预已发送',
      intervention_device_feedback: '干预设备反馈',
      demo_manual_alarm: '演示异常事件',
      demo_sensor_update: '传感器更新',
      sensor_update: '传感器更新',
      ai_state: 'AI状态评估',
      child_state_updated: '状态更新',
      page_event: '页面事件',
    }}[t] || t.replace(/_/g, ' '));
    const actionText = a => ({{
      white_noise: '白噪声',
      light: '呼吸灯',
      game: '手势小游戏',
      story: '睡前故事',
      teacher_alert: '教师提醒',
      none: '无需干预',
    }}[(a || {{}}).type] || (a || {{}}).label || (a || {{}}).type || '-');
    function formatInteractionEvent(e) {{
      const detail = e.detail || {{}};
      const executionStatus = s => ({{received:'设备已接收',started:'正在执行',completed:'已完成',failed:'未执行成功',queued:'等待设备响应',stopped:'教师已停止'}}[s] || s || '');
      if (detail.action) return `${{eventLabel(e.type)}}：${{actionText(detail.action)}}${{detail.status ? ` · ${{executionStatus(detail.status)}}` : ''}}${{detail.simulated ? ' · 演示模拟' : ''}}`;
      if (detail.state) return `${{eventLabel(e.type)}}：${{stateText(detail.state)}}`;
      if (detail.page) return `${{eventLabel(e.type)}}：${{detail.page}} / ${{detail.event || ''}}`;
      if (detail.note || detail.body_condition || detail.last_night_sleep) return `${{eventLabel(e.type)}}：${{detail.note || detail.body_condition || detail.last_night_sleep}}`;
      return eventLabel(e.type);
    }}
    function showToast(text) {{
      const el = document.getElementById('toast');
      el.textContent = text; el.style.display = 'block';
      clearTimeout(window.__toastTimer); window.__toastTimer = setTimeout(() => el.style.display = 'none', 2400);
    }}
    const i18nPairs = [
      ['教师端','Teacher Console'],['家长端','Parent App'],['班级午睡管理 · 实时状态 · 干预确认','Class nap monitoring · Live status · Intervention review'],
      ['每日午睡报告 · 作息建议 · 历史记录','Daily nap reports · Routines · History'],['午睡监护：开','Nap monitoring: On'],['停止全部干预','Stop all interventions'],
      ['班级午睡空间总览','Class nap overview'],['位置与教室床位对应，状态变化不会改变位置','Beds stay mapped to their classroom positions while status updates live'],
      ['调整床位位置','Arrange beds'],['保存并锁定床位','Save bed layout'],['演示教师','Demo teacher'],['退出账号','Log out'],
      ['已入睡','Sleeping'],['浅睡/困倦','Sleepy'],['需要安抚','Soothing'],['需安抚','Soothing'],['清醒','Awake'],['异常','Alarm'],
      ['全班午睡报告','Class nap report'],['发布全班报告','Publish class report'],['当前入睡','Asleep now'],['平均午睡','Average nap'],['未知','Unknown'],
      ['当前无待确认AI干预。','No AI interventions awaiting confirmation.'],['暂无收到儿童午睡数据。','No nap data received yet.'],
      ['儿童详情','Child details'],['请选择孩子查看实时状态、记录和环境数据。','Select a child to view live status, records, and environment data.'],
      ['刷新数据','Refresh data'],['发布今日报告','Publish today’s report'],['今日报告','Today’s report'],['报告明细','Report details'],
      ['AI作息建议','AI routine suggestion'],['历史午睡记录','Nap history'],['干预记录','Intervention history'],['报告','Reports'],['记录','History'],
      ['家长登录','Parent login'],['家长注册','Parent registration'],['教师登录','Teacher login'],['教师注册','Teacher registration'],
      ['登录','Log in'],['注册','Sign up'],['注册并进入班级','Sign up and enter class'],['注册并绑定孩子','Sign up and link child'],
      ['手机号','Phone number'],['密码','Password'],['教师姓名','Teacher name'],['家长姓名','Parent name'],['请选择孩子','Select a child'],
      ['确认','Confirm'],['取消','Cancel'],['知道了','Got it'],['发布','Publish'],['睡眠质量','Sleep quality'],['午睡时长','Nap duration'],['5秒内未取消，系统将把建议发送至干预设备','If not cancelled within 5 seconds, the recommendation will be sent to the intervention device'],['当前建议：','Current recommendation:'],['取消本次','Cancel this'],['改为此方式','Use this instead'],
      ['入睡','Sleep start'],['起床','Wake up'],['状态','Status'],['发布','Published'],['选择孩子','Select child'],
      ['入睡时间','Sleep start time'],['起床时间','Wake-up time'],['暂无数据','No data yet'],['作息较稳定，继续保持','Routine looks stable — keep it up'],
      ['今天午睡表现平稳，晚间按平时节奏入睡即可，继续保持固定的睡前仪式。','Today’s nap was steady. Keep the usual evening rhythm and bedtime routine.'],
      ['最后更新','Last updated'],['已持续','Duration'],['情绪','Mood'],['家长报告','Parent report'],['干预设备','Intervention device'],['未连接','Not connected'],['已完成','Completed'],['环境','Environment'],['心率/呼吸','Heart rate / breathing'],
      ['状态变化趋势','Status trend'],['当前没有待确认的干预建议','No interventions awaiting confirmation'],['立即干预','Intervene now'],['该孩子尚未连接干预设备。','This child is not connected to an intervention device.'],['干预设备已连接','Intervention device connected'],['打开安静小游戏','Open quiet game'],['播放睡前故事','Play bedtime story'],['干预完成统计','Intervention summary'],['白噪声+呼吸灯','White noise + breathing light'],['历史记录','History'],
      ['最近干预','Latest intervention'],['暂无历史记录','No history yet'],['暂无趋势','No trend data'],['暂无','No data'],['平静','Calm'],['困倦','Sleepy'],['停止当前播放','Stop playback'],['已连接','Connected'],['体验设备','demo device'],['已连接 · 小晴体验设备','Connected · demo device'],['小晴已连接体验设备。','Demo device connected.'],
      ['干预设备反馈：','Intervention device feedback:'],['干预已发送：','Intervention sent:'],['AI建议已生成：','AI suggestion generated:'],
      ['预计执行在','Expected at'],['待老师发布','Waiting for teacher'],['暂无完整午睡记录','No complete nap record yet'],['暂无评价','No rating yet'],
      ['干预设备反馈','Intervention device feedback'],['AI建议已生成','AI suggestion generated'],['演示模拟','Demo simulation'],['确认发布全班','Publish class report'],['将为全班孩子生成当前午睡报告并发送给绑定家长；同一天再次发布会更新原报告。','This will generate and send the current nap report for every child to their linked parent. Publishing again today will update the existing report.'],
      ['等待教师确认','Waiting for teacher confirmation'],['等待设备响应','Waiting for device'],['设备已接收','Device received'],['正在执行','In progress'],['进行中','In progress'],['未执行成功','Failed'],['教师已取消','Cancelled by teacher'],['教师已停止','Stopped by teacher'],['干预已发送','Intervention sent'],['AI建议','AI suggestion'],['家长反馈','Parent feedback'],['平稳','Stable'],['一般','Fair'],['易醒','Light sleep'],['暂无AI建议','No AI suggestion yet'],['老师端生成午睡数据后，这里会自动显示作息建议。','A routine suggestion will appear here after the teacher console generates nap data.'],['等待今日午睡报告','Waiting for today’s nap report'],['老师发布今日午睡报告后，这里会结合午睡时长、睡眠质量和近期趋势生成作息建议。','After today’s nap report is published, a routine suggestion will be generated from nap duration, sleep quality, and recent trends.'],['午睡偏短，今晚建议提前入睡','Nap was short; an earlier bedtime is recommended tonight'],['午睡偏长，今晚观察入睡时间','Nap was long; observe bedtime tonight'],['近期午睡略短，建议稳定午休前节奏','Recent naps are slightly short; stabilize the pre-nap routine'],['近期午睡较长，留意夜间作息','Recent naps are long; watch the nighttime routine'],['睡眠质量一般，今晚保持低刺激','Sleep quality is fair; keep stimulation low tonight'],['作息较稳定，继续保持','Routine is stable; keep it up'],['今天午睡不足 30 分钟，晚间可以提前 15-20 分钟进入洗漱、讲故事和关灯流程，减少睡前兴奋活动。','Today’s nap was under 30 minutes. Start the wash-up, story, and lights-out routine 15–20 minutes earlier and reduce stimulating activities.'],['今天午睡超过 2 小时，晚间可以保持安静活动，但不必过早上床；如果夜间入睡延后，明天可适当缩短午睡。','Today’s nap exceeded two hours. Keep evening activities calm without going to bed too early; shorten tomorrow’s nap if bedtime is delayed.'],['最近午睡平均时长偏短，可以在午饭后固定 10 分钟安静阅读或轻音乐，帮助身体形成午休信号。','Recent naps average short. Add 10 minutes of quiet reading or soft music after lunch to build a nap cue.'],['最近午睡平均时长较长，如果晚上入睡困难，可以和老师沟通午睡唤醒时间，避免白天睡眠挤占夜间睡眠。','Recent naps average long. If bedtime is difficult, discuss the wake-up time with the teacher so daytime sleep does not displace nighttime sleep.'],['今天午睡质量一般，晚间建议减少屏幕和剧烈游戏，保持卧室光线偏暗、声音稳定。','Today’s nap quality was fair. Reduce screens and vigorous play tonight, keeping the room dim and sounds steady.'],['今天午睡表现平稳，晚间按平时节奏入睡即可，继续保持固定的睡前仪式。','Today’s nap was steady. Keep the usual evening rhythm and bedtime routine.'],
      ['当前孩子数据不可用，请检查 child_id 或后端是否已启动。','Child data is unavailable. Check the child ID or whether the server is running.'],
      ['今日暂无报告','No report for today'],['暂无历史午睡记录','No nap history'],['暂无干预记录','No intervention history'],
      ['等待老师发布今日报告','Waiting for today’s report'],['最近发布','Published'],['演示异常事件','Demo alert'],['传感器更新','Sensor update'],
      ['无需干预','No intervention'],['小游戏','Gesture game'],['手势小游戏','Gesture game'],['睡前故事','Bedtime story'],['白噪声 + 呼吸灯','White noise'],['白噪声','White noise'],['呼吸灯','Breathing light'],['教师提醒','Teacher alert'],
      ['已发布，等待家长端接收','Published · waiting for parent app'],['已送达，等待家长查看','Delivered · waiting for parent view'],['家长已查看','Viewed by parent'],
      ['小雨','Rain'],['辰辰','Chen'],['安安','Annie'],['朵朵','Daisy'],['乐乐','Lola'],['小朗','Leo'],['小橙','Sunny'],['小河','River'],['小贝','Bella'],['小禾','Hazel'],['小羽','Skye'],['小星','Star'],['小哲','Theo'],['小然','Renee'],['小晴','Sunny'],['小航','Hank']
    ];
    function translateText(value) {{
      let out = value;
      [...i18nPairs].sort((a,b) => uiLanguage === 'en' ? b[0].length - a[0].length : b[1].length - a[1].length).forEach(([zh,en]) => {{ out = out.split(uiLanguage === 'en' ? zh : en).join(uiLanguage === 'en' ? en : zh); }});
      if (uiLanguage === 'en') out = out.replace(/当前共 (\\d+) 名儿童。/g, '$1 children in class.').replace(/(\\d+) 人/g, '$1 children').replace(/(\\d+)小时(\\d+)分/g, '$1h $2m');
      else out = out.replace(/(\\d+) children in class\\./g, '当前共 $1 名儿童。').replace(/(\\d+) children/g, '$1 人').replace(/(\\d+)h (\\d+)m/g, '$1小时$2分');
      if (uiLanguage === 'en') out = out.replace(/(\\d+)次/g, '$1 times');
      else out = out.replace(/(\\d+) times/g, '$1次');
      return out;
    }}
    function applyLanguage() {{
      document.documentElement.lang = uiLanguage === 'en' ? 'en' : 'zh-CN';
      document.documentElement.classList.toggle('lang-en', uiLanguage === 'en');
      document.querySelectorAll('input, textarea').forEach(el => {{ if (el.placeholder) el.placeholder = translateText(el.placeholder); }});
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(node => {{ if (node.parentElement && !['SCRIPT','STYLE'].includes(node.parentElement.tagName)) node.nodeValue = translateText(node.nodeValue); }});
      const toggle = document.getElementById('language-toggle-btn'); if (toggle) toggle.textContent = uiLanguage === 'en' ? '中文' : 'EN';
    }}
    let languageToggleLock = false;
    function toggleLanguage(event) {{
      if (event) event.preventDefault();
      if (languageToggleLock) return;
      languageToggleLock = true;
      uiLanguage = uiLanguage === 'en' ? 'zh' : 'en'; localStorage.setItem('nap_language', uiLanguage);
      applyLanguage();
      setTimeout(() => languageToggleLock = false, 450);
    }}
    setTimeout(applyLanguage, 0);
    if ('serviceWorker' in navigator) {{
      navigator.serviceWorker.getRegistrations().then(items => items.forEach(item => item.unregister())).catch(() => {{}});
    }}
    setInterval(() => document.getElementById('clock').textContent = new Date().toLocaleString('zh-CN'), 1000);
    async function api(url, opts) {{
      const res = await fetch(url, opts);
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }}
    const params = new URLSearchParams(location.search);
    const demoRequested = params.get('demo') === '1';
    async function triggerDemoIntervention() {{
      await api('/api/debug/demo/trigger', {{ method:'POST', headers: localStorage.getItem('nap_teacher_token') ? {{Authorization:`Bearer ${{localStorage.getItem('nap_teacher_token')}}`}} : {{}} }});
      showToast('已触发一条AI干预计划');
    }}
    async function startDemoMode() {{
      await api('/api/debug/demo/start', {{ method:'POST', headers: localStorage.getItem('nap_teacher_token') ? {{Authorization:`Bearer ${{localStorage.getItem('nap_teacher_token')}}`}} : {{}} }});
      document.documentElement.classList.add('demo-on');
      showToast('演示数据已启动');
    }}
    async function stopDemoMode() {{
      await api('/api/debug/demo/stop', {{ method:'POST', headers: localStorage.getItem('nap_teacher_token') ? {{Authorization:`Bearer ${{localStorage.getItem('nap_teacher_token')}}`}} : {{}} }});
      document.documentElement.classList.remove('demo-on');
      showToast('演示模式已停止');
    }}
    function setRuntimeToggleLabel(enabled) {{
      const btn = document.getElementById('runtime-toggle-btn');
      if (!btn) return;
      btn.textContent = enabled ? '午睡监护：开' : '午睡监护：关';
      btn.className = enabled ? 'primary' : 'soft';
    }}
    async function stopAllInterventions(options = {{}}) {{
      const token = localStorage.getItem('nap_teacher_token');
      try {{
        await api('/api/runtime/stop-all', {{ method:'POST', keepalive: !!options.keepalive, headers:token ? {{Authorization:`Bearer ${{token}}`}} : {{}} }});
        document.documentElement.classList.remove('demo-on');
        if (!options.silent) showToast('已停止全部干预和演示任务');
      }} catch (error) {{
        if (!options.silent) showToast('停止失败，请重新登录后再试');
      }}
    }}
    function confirmStopAllInterventions() {{
      if (!confirm('确认停止全班床头板、正在播放的声音和演示任务？')) return;
      if (typeof teacherRuntimeEnabled !== 'undefined') teacherRuntimeEnabled = false;
      setRuntimeToggleLabel(false);
      stopAllInterventions();
    }}
    {script}
  </script>
</body>
</html>"""


TEACHER_SCRIPT = r"""
const root = document.getElementById('teacher-root');
let selectedChild = null;
let data = { children: [], pending_interventions: [], stats: {} };
let demoEnabled = false;
let teacherAuthMode = 'login';
let currentTeacher = null;
let layoutEditing = false;
let draggedChildId = null;
let openDetailChildId = null;
let teacherRefreshTimer = null;
let teacherRuntimeEnabled = true;
let teacherShutdownSent = false;
let hoveredChildId = null;

function sendTeacherHeartbeat() {
  if (!currentTeacher || !teacherRuntimeEnabled) return;
  fetch('/api/runtime/heartbeat', {method:'POST', keepalive:true, headers:teacherAuthHeaders()}).catch(() => {});
}
setInterval(sendTeacherHeartbeat, 4000);

async function startTeacherRuntime() {
  teacherRuntimeEnabled = true;
  teacherShutdownSent = false;
  setRuntimeToggleLabel(true);
  try {
    await api('/api/runtime/start', {method:'POST', headers:teacherAuthHeaders()});
  } catch (e) {
    showToast('监护启动失败，请重新登录后再试');
    return;
  }
  sendTeacherHeartbeat();
  showToast('午睡监护已开启');
  loadTeacher().catch(console.error);
}

function stopTeacherRuntime() {
  if (!confirm('关闭午睡监护会统一关闭全班床头板，并停止正在执行的干预。确认关闭？')) return;
  teacherRuntimeEnabled = false;
  teacherShutdownSent = true;
  setRuntimeToggleLabel(false);
  stopAllInterventions();
}

function toggleTeacherRuntime() {
  if (teacherRuntimeEnabled) {
    stopTeacherRuntime();
  } else {
    startTeacherRuntime();
  }
}

window.addEventListener('beforeunload', event => {
  if (!currentTeacher || !teacherRuntimeEnabled || teacherShutdownSent) return;
  event.preventDefault();
  event.returnValue = '离开教师端将统一关闭全班床头板，并停止正在执行的干预。';
  return event.returnValue;
});

window.addEventListener('pagehide', () => {
  if (!currentTeacher || !teacherRuntimeEnabled || teacherShutdownSent) return;
  teacherShutdownSent = true;
  stopAllInterventions({silent:true, keepalive:true});
});

function renderTeacherAuth() {
  root.innerHTML = `
    <section class="panel span-12" style="max-width:460px;margin:40px auto">
      <h2>${teacherAuthMode === 'login' ? '教师登录' : '教师注册'}</h2>
      <div class="row" style="margin-bottom:12px">
        <button class="${teacherAuthMode === 'login' ? 'primary' : ''}" onclick="teacherAuthMode='login';renderTeacherAuth()">登录</button>
        <button class="${teacherAuthMode === 'register' ? 'primary' : ''}" onclick="teacherAuthMode='register';renderTeacherAuth()">注册</button>
      </div>
      <div class="list">
        <input id="teacher-phone" placeholder="手机号" value="${teacherAuthMode === 'login' ? '13800000000' : ''}">
        <input id="teacher-password" placeholder="密码" type="password" value="${teacherAuthMode === 'login' ? '123456' : ''}">
        ${teacherAuthMode === 'register' ? '<input id="teacher-name" placeholder="教师姓名">' : ''}
        <button class="primary" onclick="submitTeacherAuth()">${teacherAuthMode === 'login' ? '登录' : '注册并进入班级'}</button>
        ${teacherAuthMode === 'login' ? '<div class="muted">已填入本机演示教师账号，可直接登录。</div>' : ''}
      </div>
    </section>`;
}

async function submitTeacherAuth() {
  const payload = {
    role: 'teacher',
    phone: document.getElementById('teacher-phone').value.trim(),
    password: document.getElementById('teacher-password').value,
    name: document.getElementById('teacher-name')?.value || '老师',
  };
  try {
    const result = await api(`/api/auth/${teacherAuthMode}`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    localStorage.setItem('nap_teacher_token', result.token);
    currentTeacher = result.user;
    await loadTeacher();
  } catch (e) {
    showToast(teacherAuthMode === 'login' ? '登录失败，请检查账号和密码' : '注册失败，请检查信息或更换手机号');
  }
}

async function ensureTeacherSession() {
  const token = localStorage.getItem('nap_teacher_token');
  if (!token) return false;
  try {
    const result = await api('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } });
    if (result.user?.role !== 'teacher') return false;
    currentTeacher = result.user;
    return true;
  } catch (e) {
    localStorage.removeItem('nap_teacher_token');
    return false;
  }
}

async function loginDefaultTeacher() {
  const result = await api('/api/auth/login', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({role:'teacher', phone:'13800000000', password:'123456'})
  });
  localStorage.setItem('nap_teacher_token', result.token);
  currentTeacher = result.user;
  await loadTeacher();
}

function logoutTeacher() {
  localStorage.removeItem('nap_teacher_token');
  currentTeacher = null;
  renderTeacherAuth();
}

async function syncDemoState() {
  try {
    const status = await api('/api/debug/demo/status');
    demoEnabled = status.enabled;
    if (demoEnabled) {
      document.documentElement.classList.add('demo-on');
    } else {
      document.documentElement.classList.remove('demo-on');
    }
  } catch (e) {
    console.warn('无法获取演示模式状态', e);
  }
}

function downloadReport(url) {
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function loadTeacher() {
  if (teacherRuntimeEnabled) {
    await api('/api/runtime/start', {method:'POST', headers:teacherAuthHeaders()});
  }
  try {
    const demoStatus = await api('/api/debug/demo/status');
    if (!demoStatus.enabled) await api('/api/debug/demo/start', {method:'POST', headers:teacherAuthHeaders()});
  } catch (e) {
    console.warn('无法自动启动演示数据', e);
  }
  await syncDemoState();
  setRuntimeToggleLabel(teacherRuntimeEnabled);
  sendTeacherHeartbeat();
  data = await api('/api/teacher/class-overview', { headers:teacherAuthHeaders() });
  if (!selectedChild && data.children[0]) selectedChild = data.children[0].id;
  renderTeacher();
}

function childById(id) {
  return data.children.find(c => c.id === id) || data.children[0] || null;
}

function reportStatusText(status) {
  return ({not_published:'今日未发布', published:'已发布，等待家长端接收', delivered:'已送达，等待家长查看', read:'家长已查看'}[status] || '今日未发布');
}

function executionStatusText(status, simulated = false) {
  const text = ({awaiting_approval:'等待教师确认',queued:'等待设备响应',received:'设备已接收',started:'正在执行',completed:'已完成',failed:'未执行成功',cancelled:'教师已取消',stopped:'教师已停止'}[status] || '暂无干预记录');
  return simulated ? `${text}（演示）` : text;
}

function selectChild(id) {
  if (layoutEditing) return;
  const previous = document.querySelector('.kid-tile.selected');
  if (previous) previous.classList.remove('selected');
  selectedChild = id;
  const current = document.querySelector(`.kid-tile[data-child-id="${id}"]`);
  if (current) current.classList.add('selected');
  loadDetail(id).catch(error => { console.error(error); showToast('详情加载失败，请刷新后重试'); });
}

async function toggleLayoutEditing() {
  const wasEditing = layoutEditing;
  layoutEditing = !layoutEditing;
  draggedChildId = null;
  renderTeacher();
  showToast(layoutEditing ? '位置调整已开启，请拖动孩子卡片' : '教室位置已锁定');
  if (wasEditing) await loadTeacher();
}

function startChildDrag(event, childId) {
  if (!layoutEditing) return;
  draggedChildId = childId;
  event.dataTransfer.effectAllowed = 'move';
}

async function dropChild(event, targetId) {
  event.preventDefault();
  if (!layoutEditing || !draggedChildId || draggedChildId === targetId) return;
  const from = data.children.findIndex(child => child.id === draggedChildId);
  const to = data.children.findIndex(child => child.id === targetId);
  const [moved] = data.children.splice(from, 1);
  data.children.splice(to, 0, moved);
  draggedChildId = null;
  renderTeacher();
  await api('/api/teacher/child-order', {
    method:'POST',
    headers:{...teacherAuthHeaders(), 'Content-Type':'application/json'},
    body:JSON.stringify({ordered_ids:data.children.map(child => child.id)})
  });
  showToast('教室位置已保存');
}

function showChildModal(html) {
  openDetailChildId = null;
  const modal = document.getElementById('child-modal');
  modal.innerHTML = `<div class="modal-card" onclick="event.stopPropagation()">${html}<button class="modal-close" onclick="closeChildModal()">×</button></div>`;
  modal.classList.remove('hidden');
  modal.classList.add('active');
  applyLanguage();
}

function closeChildModal(event) {
  if (event && event.target !== event.currentTarget) return;
  const modal = document.getElementById('child-modal');
  modal.classList.remove('active');
  modal.classList.add('hidden');
  modal.innerHTML = '';
  openDetailChildId = null;
  if (currentTeacher && !layoutEditing) loadTeacher().catch(console.error);
}

function renderTeacher() {
  const selected = childById(selectedChild);
  root.innerHTML = `
    <section class="panel span-12 panel-map">
      <div class="row" style="justify-content:space-between;margin-bottom:14px">
        <div><h2>班级午睡空间总览</h2><div class="muted">位置与教室床位对应，${layoutEditing ? '拖动卡片后自动保存' : '状态变化不会改变位置'}</div></div>
        <div class="row" style="gap:12px; align-items:center;">
          <button class="${layoutEditing ? 'primary' : 'soft'}" onclick="toggleLayoutEditing()">${layoutEditing ? '保存并锁定床位' : '调整床位位置'}</button>
          <div class="legend">
            <span><i class="dot" style="background:#16a34a"></i>已入睡</span>
            <span><i class="dot" style="background:#3b82f6"></i>浅睡/困倦</span>
            <span><i class="dot" style="background:#f59e0b"></i>需要安抚</span>
            <span><i class="dot" style="background:#94a3b8"></i>清醒</span>
            <span><i class="dot" style="background:#ef4444"></i>异常</span>
          </div>
          <span class="muted">${currentTeacher?.name || '教师'}</span>
          <button title="退出当前教师账号" onclick="logoutTeacher()">退出账号</button>
        </div>
      </div>
      <div class="nap-map" id="kid-map">${data.children.map(c => `
        <button type="button" class="kid-tile ${c.current_state} ${selectedChild === c.id ? 'selected' : ''}" data-child-id="${c.id}" draggable="${layoutEditing}" onmouseenter="hoveredChildId='${c.id}'; clearTimeout(teacherRefreshTimer)" onmouseleave="hoveredChildId=null" ondragstart="startChildDrag(event, '${c.id}')" ondragover="layoutEditing && event.preventDefault()" ondrop="dropChild(event, '${c.id}')" onclick="selectChild('${c.id}')">
          ${c.unread_parent_feedback_count ? `<span class="unread-badge">${c.unread_parent_feedback_count}</span>` : ''}
          <div class="kid-content">
          <div class="tile-icon" style="background:${stateColor(c.current_state)}">${stateIcon(c.current_state)}</div>
          <div class="tile-name">${c.name}</div>
          <div class="state ${c.current_state}">${stateText(c.current_state)}</div>
          <div class="tile-time">${fmtDur(c.sleep_duration_seconds) || '-'}</div>
                  </div>
        </button>`).join('') || '<div class="muted">暂未收到儿童午睡数据。</div>'}</div>
    </section>
    <section class="panel span-12">
      <div class="row" style="justify-content:space-between; gap:14px; flex-wrap:wrap;">
        <div>
          <h2>全班午睡报告</h2>
          <div class="muted">当前共 ${data.children.length} 名儿童。</div>
        </div>
        <div class="row" style="gap:12px; align-items:center;">
          <button class="primary" onclick="requestPublishAllReports()">发布全班报告</button>
          <div class="stat-row"><span>当前入睡</span><strong>${data.stats.sleeping_count || 0} 人</strong></div>
          <div class="stat-row"><span>平均午睡</span><strong>${fmtDur(data.stats.avg_sleep_seconds)}</strong></div>
        </div>
      </div>
      <div class="row" style="gap:14px; margin-top:16px; flex-wrap:wrap;">
        ${Object.entries(data.stats.state_distribution || {}).map(([state,count]) => `<div class="stat-row"><span>${stateText(state)}</span><strong>${count} 人</strong></div>`).join('')}
      </div>
      <div class="list" style="margin-top:18px;">
        ${data.pending_interventions.length ? data.pending_interventions.map(p => `<div class="item"><strong>${p.child_name}</strong><div class="muted">AI建议：${p.proposed_action.label || p.proposed_action.type}，预计执行在 ${fmtDateTime(p.deadline_ts * 1000)}</div></div>`).join('') : '<div class="muted">当前无待确认AI干预。</div>'}
      </div>
    </section>`;
  tickCountdowns();
  applyLanguage();
}

function renderDetailSkeleton(c) {
  if (!c) return '<div class="detail-head"><div><h2>儿童详情</h2><span class="muted">请选择孩子查看实时状态、记录和环境数据。</span></div></div>';
  return `<div class="detail-head"><div><h2>${c.name}</h2><span class="state ${c.current_state}">${stateText(c.current_state)}</span></div></div><div class="muted" style="margin-top:12px">正在读取详情...</div>`;
}

function renderAlerts() {
  const list = data.children
    .filter(c => ['alarm', 'need_help', 'sleepy'].includes(c.current_state))
    .sort((a,b) => (a.priority - b.priority) || a.name.localeCompare(b.name));
  return list.map(c => `<div class="item ${c.current_state === 'alarm' ? 'alarm' : 'need_help'}" onclick="selectChild('${c.id}')">
    <div class="row" style="justify-content:space-between"><strong>${c.name}</strong><span class="state ${c.current_state}">${stateText(c.current_state)}</span></div>
    <div class="muted">${c.current_state === 'alarm' ? '持续哭闹或环境异常，建议立即查看' : '翻动频繁，可能需要轻柔干预'} · ${fmtDur(c.sleep_duration_seconds)}</div>
  </div>`).join('') || '<div class="muted">当前没有异常提醒</div>';
}

function interventionHistory(interactions) {
  const types = [
    ['teacher_alert', '教师提醒', '#ef4444'],
    ['game', '手势小游戏', '#ea580c'],
    ['light', '呼吸灯', '#8aaa45'],
    ['story', '睡前故事', '#16a34a'],
    ['white_noise', '白噪声', '#2563eb'],
  ];
  const counts = Object.fromEntries(types.map(([type]) => [type, 0]));
  const statusRank = {queued:1, received:2, started:3, completed:4, failed:4, stopped:4, cancelled:4};
  const latestByPlan = {};
  (interactions || []).forEach(e => {
    const detail = e.detail || {};
    const action = detail.action || {};
    if (!action.type || !(action.type in counts)) return false;
    const isTrigger = ['ai_intervention_pending', 'teacher_manual_intervention', 'intervention_dispatched', 'intervention_device_feedback'].includes(e.type);
    if (!isTrigger) return;
    const planId = detail.plan_id || `${e.type}-${action.type}-${e.time}`;
    const status = detail.status || (e.type === 'ai_intervention_pending' ? 'awaiting_approval' : 'queued');
    const existing = latestByPlan[planId];
    const normalized = {...e, detail:{...detail, status}};
    if (!existing || (statusRank[status] || 1) >= (statusRank[existing.detail?.status] || 1)) latestByPlan[planId] = normalized;
  });
  const events = Object.values(latestByPlan).sort((a,b) => new Date(b.time) - new Date(a.time));
  events.forEach(e => {
    const action = e.detail?.action || {};
    if (action.type in counts) counts[action.type] += 1;
  });
  const max = Math.max(1, ...Object.values(counts));
  return {
    chart: types.map(([type, label, color]) => {
      const h = Math.max(8, Math.round((counts[type] / max) * 86));
      return `<div class="action-bar"><div class="action-fill" style="height:${h}px;background:${color}"></div><div class="action-name">${label}</div><div class="action-count">${counts[type]}次</div></div>`;
    }).join(''),
    events,
  };
}

function stopControlHtml(c) {
  return c.latest_execution && ['queued','received','started'].includes(c.latest_execution.status) && ['white_noise','story'].includes(c.latest_execution.action?.type)
    ? `<button class="danger" onclick="stopIntervention('${c.latest_execution.plan_id}')">停止当前播放</button>`
    : '';
}

async function refreshDetailStatus(id) {
  const d = await api(`/api/children/${id}/detail`, { headers:teacherAuthHeaders() });
  if (openDetailChildId !== id) return;
  const c = d.child;
  const state = document.getElementById('detail-state');
  if (state) { state.textContent = stateText(c.current_state); state.className = `state ${c.current_state}`; }
  const values = {
    'detail-last-seen': `最后更新 ${fmtDateTime(c.last_seen)}`,
    'detail-duration': fmtDur(c.sleep_duration_seconds),
    'detail-emotion': c.emotion || '-',
    'detail-report': reportStatusText(c.report_status),
    'detail-execution': c.latest_execution ? `${actionText(c.latest_execution.action)} · ${executionStatusText(c.latest_execution.status, c.latest_execution.simulated)}` : '暂无',
    'detail-environment': `${c.environment?.temperature ?? '-'}°C / ${c.environment?.humidity ?? '-'}`,
    'detail-vitals': `${c.environment?.heart_rate ?? '-'} / ${c.environment?.breath_rate ?? '-'}`,
  };
  Object.entries(values).forEach(([elementId, value]) => { const element = document.getElementById(elementId); if (element) element.textContent = value; });
  const stopControl = document.getElementById('detail-stop-control');
  if (stopControl) stopControl.innerHTML = stopControlHtml(c);
}

async function loadDetail(id) {
  openDetailChildId = id;
  const d = await api(`/api/children/${id}/detail`, { headers:teacherAuthHeaders() });
  const c = d.child;
  const bars = (d.samples || []).slice(0, 8).reverse().map(s => {
    const h = Math.max(12, Math.min(96, Number(s.motion || 0) / 6));
    return `<span class="bar" style="height:${h}px"></span>`;
  }).join('');
  const actionHistory = interventionHistory(d.interactions || []);
  const reportEventTypes = ['ai_intervention_pending', 'teacher_manual_intervention', 'intervention_dispatched', 'intervention_device_feedback', 'teacher_cancelled_intervention', 'teacher_overrode_intervention'];
  const meaningfulHistory = (d.interactions || []).filter(e => reportEventTypes.includes(e.type) && e.detail?.action);
  const pendingHtml = c.pending_intervention ? `
    <div class="ai-box">
      <div class="muted">5秒内未取消，系统将把建议发送至干预设备</div>
      <p><strong>${c.name}</strong> 当前建议：${c.pending_intervention.label}</p>
      <div class="row" style="gap:10px; flex-wrap:wrap; margin-top:12px">
        <span class="countdown" data-deadline="${c.pending_intervention.deadline_ts}">5s</span>
        <button class="danger" onclick="cancelIntervention('${c.pending_intervention.id}')">取消本次</button>
        <select id="override-${c.pending_intervention.id}" style="max-width:180px">
          <option value="white_noise">白噪声 + 呼吸灯</option>
          <option value="story">语音引导</option>
          <option value="game">小游戏</option>
        </select>
        <button class="primary" onclick="overrideIntervention('${c.pending_intervention.id}')">改为此方式</button>
      </div>
    </div>` : `<div class="ai-box"><div class="muted">当前没有待确认的干预建议</div></div>`;
  const html = `
    <div class="detail-head"><div><h2>${c.name}</h2><span id="detail-state" class="state ${c.current_state}">${stateText(c.current_state)}</span></div></div>
    <div class="row" style="justify-content:space-between;margin-top:8px"><div id="detail-last-seen" class="muted">最后更新 ${fmtDateTime(c.last_seen)}</div><div class="row"><button onclick="refreshDetailStatus('${c.id}')">刷新数据</button><button class="soft" onclick="requestPublishParentReport('${c.id}', '${c.name}')">发布今日报告</button></div></div>
    <div class="stat-row"><span>已持续</span><strong id="detail-duration">${fmtDur(c.sleep_duration_seconds)}</strong></div>
    <div class="stat-row"><span>情绪</span><strong id="detail-emotion">${c.emotion || '-'}</strong></div>
    <div class="stat-row"><span>家长报告</span><strong id="detail-report">${reportStatusText(c.report_status)}</strong></div>
    <div class="stat-row"><span>干预设备</span><strong id="detail-connection" class="connection-check" title="Intervention device connected">${c.execution_connected ? '✓' : '—'}</strong></div>
    <div class="stat-row"><span>最近干预</span><strong id="detail-execution">${c.latest_execution ? `${actionText(c.latest_execution.action)} · ${executionStatusText(c.latest_execution.status, c.latest_execution.simulated)}` : '暂无'}</strong></div>
    <div id="detail-stop-control" class="row" style="justify-content:flex-end;margin-top:10px">${stopControlHtml(c)}</div>
    <div class="stat-row"><span>环境</span><strong id="detail-environment">${c.environment?.temperature ?? '-'}°C / ${c.environment?.humidity ?? '-'}</strong></div>
    <div class="stat-row"><span>心率/呼吸</span><strong id="detail-vitals">${c.environment?.heart_rate ?? '-'} / ${c.environment?.breath_rate ?? '-'}</strong></div>
    <h3>状态变化趋势</h3><div class="bars">${bars || '<span class="muted">暂无趋势</span>'}</div>
    ${pendingHtml}
    <h3>立即干预</h3>
    <div class="muted">${c.execution_connected ? '✓' : '该孩子尚未连接干预设备。'}</div>
    <div class="action-grid" style="margin-top:12px">
      ${[
        ['teacher_alert','教师提醒','#ef4444','!'],
        ['game','手势小游戏','#ea580c','▣'],
        ['light','呼吸灯','#8aaa45','◌'],
        ['story','睡前故事','#16a34a','☰'],
        ['white_noise','白噪声','#2563eb','♪']
      ].map(([type,label,color,icon]) => `<button class="action-btn" onclick="requestManualIntervention('${c.id}', '${c.name}', '${type}', '${label}', ${c.execution_connected})"><span class="action-dot" style="background:${color}">${icon}</span>${label}</button>`).join('')}
    </div>
    <h3>干预完成统计</h3>
    <div class="action-bars">${actionHistory.chart}</div>
    <h3>历史记录</h3>
    <div class="list">${meaningfulHistory.slice(0,10).map(e => `<div class="item"><strong>${fmtDateTime(e.time)}</strong><div class="muted">${formatInteractionEvent(e)}</div></div>`).join('') || '<div class="muted">暂无历史记录</div>'}</div>
    `;
  showChildModal(html);
}

async function cancelIntervention(id) {
  try {
    await api(`/api/interventions/${id}/cancel`, { method:'POST', headers:teacherAuthHeaders() });
    await loadTeacher();
    showResultDialog('取消成功', '本次 AI 干预已取消，设备不会执行该方案。');
  } catch (e) {
    showResultDialog('未能取消', '该方案可能已经执行或网络暂时不可用，请刷新后查看最终记录。');
  }
}

async function overrideIntervention(id) {
  const type = document.getElementById(`override-${id}`).value;
  try {
    await api(`/api/interventions/${id}/override`, { method:'POST', headers:{...teacherAuthHeaders(), 'Content-Type':'application/json'}, body:JSON.stringify({ action_type:type, param:'manual' }) });
    await loadTeacher();
    showResultDialog('方案已更改', `已改为“${actionText({type})}”并发送，请在孩子详情查看设备状态。`);
  } catch (e) {
    showResultDialog('未能更改', '该方案可能已经执行，请查看历史记录确认最终执行方式。');
  }
}

function requestManualIntervention(childId, childName, type, label, connected) {
  const connectionCopy = connected
    ? '小晴已连接体验设备，确认后将立即启动对应干预。'
    : '该孩子尚未连接干预设备，确认后不会播放声音或打开画面。';
  showChildModal(`<div class="detail-head"><div><h2>确认立即干预</h2><div class="muted" style="margin-top:10px">将为 <strong>${childName}</strong> ${label}。${connectionCopy}</div></div></div><div class="row" style="justify-content:flex-end;margin-top:20px"><button onclick="closeChildModal()">取消</button><button class="primary" onclick="sendManualIntervention('${childId}', '${type}', '${label}')">确认并发送</button></div>`);
}

async function sendManualIntervention(childId, type, label) {
  try {
    const result = await api(`/api/children/${childId}/interventions`, {
      method:'POST',
      headers:{...teacherAuthHeaders(), 'Content-Type':'application/json'},
      body:JSON.stringify({action_type:type, param:'manual', label})
    });
    await loadTeacher();
    if (result.execution_connected) {
      showResultDialog('干预已发送', `${label}已发送至小晴的体验设备，可在孩子详情查看执行状态。`);
    } else {
      showResultDialog('未执行', '该孩子尚未连接干预设备，因此没有播放声音或打开画面。');
    }
  } catch (e) {
    showResultDialog('发送失败', '干预没有发送成功，请稍后重试。');
  }
}

async function stopIntervention(planId) {
  try {
    await api(`/api/interventions/${planId}/stop`, { method:'POST', headers:teacherAuthHeaders() });
    await loadTeacher();
    showResultDialog('已停止', '当前音频播放已停止。');
  } catch (e) {
    showResultDialog('未能停止', '任务可能已经结束，请刷新详情确认最终状态。');
  }
}

function showResultDialog(title, body) {
  showChildModal(`<div class="detail-head"><div><h2>${title}</h2><div class="muted" style="margin-top:10px">${body}</div></div></div><div class="row" style="justify-content:flex-end;margin-top:20px"><button class="primary" onclick="closeChildModal()">知道了</button></div>`);
}

function requestPublishParentReport(childId, childName) {
  showChildModal(`<div class="detail-head"><div><h2>发布今日报告</h2><div class="muted" style="margin-top:10px">确认将 <strong>${childName}</strong> 当前已完成的午睡报告发送给绑定家长？同一天再次发布会更新原报告。</div></div></div><div class="row" style="justify-content:flex-end;margin-top:20px"><button onclick="closeChildModal()">暂不发布</button><button class="primary" onclick="publishParentReport('${childId}', '${childName}')">确认发布</button></div>`);
}

function requestPublishAllReports() {
  showChildModal(`<div class="detail-head"><div><h2>发布全班报告</h2><div class="muted" style="margin-top:10px">将为全班孩子生成当前午睡报告并发送给绑定家长；同一天再次发布会更新原报告。</div></div></div><div class="row" style="justify-content:flex-end;margin-top:20px"><button onclick="closeChildModal()">取消</button><button class="primary" onclick="publishAllReports()">确认发布全班</button></div>`);
}

async function publishAllReports() {
  try {
    const result = await api('/api/teacher/publish-all-reports', { method:'POST', headers:teacherAuthHeaders() });
    await loadTeacher();
    showResultDialog('全班报告已发布', `已发布 ${result.published_count} 份，已通知 ${result.recipient_count} 个家长账号。`);
  } catch (e) {
    showResultDialog('批量发布失败', '全班报告未完成发布，请检查网络或重新登录后再试。');
  }
}

async function publishParentReport(childId, childName) {
  try {
    const result = await api(`/api/teacher/${childId}/publish-report`, {
      method:'POST',
      headers:{...teacherAuthHeaders(), 'Content-Type':'application/json'},
      body:JSON.stringify({})
    });
    if (result.report.recipient_count > 0) {
      showResultDialog('发布成功', `${childName} 的今日报告已发给 ${result.report.recipient_count} 个绑定家长账号，可在孩子详情查看送达和已读状态。`);
    } else {
      showResultDialog('报告已保存，但尚未送达', `${childName} 当前没有绑定家长账号。请让家长在家长端选择并绑定 ${childName} 后再发布。`);
    }
  } catch (e) {
    showResultDialog('发布失败', '报告未发送，请检查网络或重新登录后再试。');
  }
}

function teacherAuthHeaders() {
  const token = localStorage.getItem('nap_teacher_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function tickCountdowns() {
  document.querySelectorAll('[data-deadline]').forEach(el => {
    const remain = Math.max(0, Math.ceil((Number(el.dataset.deadline) * 1000 - Date.now()) / 1000));
    el.textContent = `${remain}s`;
  });
}
setInterval(tickCountdowns, 250);
function refreshTeacherTiles(nextData) {
  data = nextData;
  (nextData.children || []).forEach(c => {
    const tile = document.querySelector(`.kid-tile[data-child-id="${c.id}"]`);
    if (!tile) return;
    tile.className = `kid-tile ${c.current_state} ${selectedChild === c.id ? 'selected' : ''}`;
    tile.setAttribute('draggable', layoutEditing ? 'true' : 'false');
    const content = tile.querySelector('.kid-content');
    if (content) content.innerHTML = `
      <div class="tile-icon" style="background:${stateColor(c.current_state)}">${stateIcon(c.current_state)}</div>
      <div class="tile-name">${c.name}</div>
      <div class="state ${c.current_state}">${stateText(c.current_state)}</div>
      <div class="tile-time">${fmtDur(c.sleep_duration_seconds) || '-'}</div>`;
  });
  applyLanguage();
}
new EventSource('/api/events').onmessage = event => {
  if (!currentTeacher || layoutEditing) return;
  if (openDetailChildId) return;
  if (hoveredChildId) return;
  clearTimeout(teacherRefreshTimer);
  teacherRefreshTimer = setTimeout(async () => {
    try {
      const nextData = await api('/api/teacher/class-overview', { headers:teacherAuthHeaders() });
      refreshTeacherTiles(nextData);
    } catch (e) { console.error(e); }
  }, 450);
};
ensureTeacherSession().then(ok => ok ? loadTeacher() : loginDefaultTeacher()).catch(() => renderTeacherAuth());
"""


PARENT_SCRIPT = r"""
const root = document.getElementById('parent-root');
let childId = new URLSearchParams(location.search).get('child_id') || localStorage.getItem('nap_child_id') || '';
let activeTab = 'today';
let authMode = 'login';
let currentUser = null;
let childOptions = [];
let currentReportPublished = false;

function authHeaders() {
  const token = localStorage.getItem('nap_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function setTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.app-screen').forEach(el => el.classList.toggle('active', el.dataset.screen === tab));
  document.querySelectorAll('.bottom-tabs button').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
  if (tab === 'today') markCurrentReportRead().catch(console.error);
}

async function markCurrentReportRead() {
  if (!currentUser || !childId || !currentReportPublished || document.visibilityState !== 'visible') return;
  await api(`/api/parent/${childId}/report-read`, { method:'POST', headers:authHeaders() });
}

function listOrEmpty(items, emptyText) {
  return items.length ? items.join('') : `<div class="muted">${emptyText}</div>`;
}

function childOptionMarkup(selectedId = '') {
  return childOptions.map(child => `<option value="${child.id}" ${child.id === selectedId ? 'selected' : ''}>${child.name}（${child.id}）</option>`).join('');
}

async function loadChildOptions() {
  try {
    const result = await api('/api/children/options');
    childOptions = result.children || [];
  } catch (e) {
    childOptions = [];
  }
}

function renderAuth() {
  root.innerHTML = `
    <section class="app-card auth-card">
      <h2>${authMode === 'login' ? '家长登录' : '家长注册'}</h2>
      <div class="auth-switch">
        <button class="${authMode === 'login' ? 'active' : ''}" onclick="authMode='login';renderAuth()">登录</button>
        <button class="${authMode === 'register' ? 'active' : ''}" onclick="authMode='register';renderAuth()">注册</button>
      </div>
      <input id="auth-phone" placeholder="手机号" value="${authMode === 'login' ? '13900000015' : ''}">
      <input id="auth-password" placeholder="密码" type="password" value="${authMode === 'login' ? '123456' : ''}">
      ${authMode === 'register' ? `
        <input id="auth-name" placeholder="家长姓名">
        <select id="auth-child"><option value="">请选择孩子</option>${childOptionMarkup(childId)}</select>
      ` : ''}
      <button class="primary" onclick="submitAuth()">${authMode === 'login' ? '登录' : '注册并绑定孩子'}</button>
      <div class="muted">${authMode === 'login' ? '已填入小晴家长演示账号，可直接登录。' : '家长端只接收已绑定孩子的最新午睡报告和历史记录。'}</div>
    </section>`;
}

async function submitAuth() {
  const payload = {
    role: 'parent',
    phone: document.getElementById('auth-phone').value.trim(),
    password: document.getElementById('auth-password').value,
  };
  if (authMode === 'register') {
    payload.name = document.getElementById('auth-name').value || '家长';
    payload.child_id = document.getElementById('auth-child').value;
  }
  try {
    const result = await api(`/api/auth/${authMode}`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    if (result.user?.role !== 'parent') throw new Error('parent account required');
    localStorage.setItem('nap_token', result.token);
    if (result.user?.child_id) {
      childId = result.user.child_id;
      localStorage.setItem('nap_child_id', childId);
    }
    currentUser = result.user;
    await loadParent();
  } catch (e) {
    showToast(authMode === 'login' ? '登录失败，请检查家长账号和密码' : '注册失败，请检查信息或更换手机号');
  }
}

async function ensureParentSession() {
  const token = localStorage.getItem('nap_token');
  if (!token) return false;
  try {
    const result = await api('/api/auth/me', { headers: authHeaders() });
    if (result.user?.role !== 'parent') return false;
    currentUser = result.user;
    if (currentUser?.child_id) {
      childId = currentUser.child_id;
      localStorage.setItem('nap_child_id', childId);
    }
    return true;
  } catch (e) {
    localStorage.removeItem('nap_token');
    return false;
  }
}

async function loginDefaultParent() {
  const result = await api('/api/auth/login', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({role:'parent', phone:'13900000015', password:'123456'})
  });
  localStorage.setItem('nap_token', result.token);
  currentUser = result.user;
  childId = result.user.child_id;
  localStorage.setItem('nap_child_id', childId);
  await loadParent();
}

function logoutParent() {
  localStorage.removeItem('nap_token');
  currentUser = null;
  renderAuth();
}

function showParentDialog(html) {
  const modal = document.getElementById('child-modal');
  modal.innerHTML = `<div class="modal-card" onclick="event.stopPropagation()">${html}<button class="modal-close" onclick="closeParentDialog()">×</button></div>`;
  modal.classList.remove('hidden');
  modal.classList.add('active');
}

function closeParentDialog(event) {
  if (event && event.target !== event.currentTarget) return;
  const modal = document.getElementById('child-modal');
  modal.classList.remove('active');
  modal.classList.add('hidden');
  modal.innerHTML = '';
}

function openBindingDialog() {
  showParentDialog(`<h2>选择孩子</h2><div class="muted" style="margin-bottom:12px">请选择要查看午睡报告的孩子。</div><select id="binding-child">${childOptionMarkup(childId)}</select><div class="row" style="justify-content:flex-end;margin-top:18px"><button onclick="closeParentDialog()">取消</button><button class="primary" onclick="saveBinding()">确认</button></div>`);
}

async function saveBinding() {
  const newChildId = document.getElementById('binding-child').value;
  const result = await api('/api/parent/bind-child', {
    method:'POST',
    headers:{...authHeaders(), 'Content-Type':'application/json'},
    body:JSON.stringify({child_id:newChildId})
  });
  currentUser = result.user;
  childId = result.user.child_id;
  localStorage.setItem('nap_child_id', childId);
  closeParentDialog();
  await loadParent();
  showToast(`已绑定 ${result.user.child_name}`);
}

async function loadParent() {
  let report = {}, history = { records: [] };
  try {
    [report, history] = await Promise.all([
      api(`/api/parent/${childId}/today-report`, { headers:authHeaders() }),
      api(`/api/parent/${childId}/sleep-growth`, { headers:authHeaders() })
    ]);
  } catch (e) {
    root.innerHTML = `<section class="app-card"><h2>加载失败</h2><div class="muted">当前孩子数据不可用，请检查 child_id 或后端是否已启动。</div></section>`;
    return;
  }
  const child = { name: report.child_name || currentUser?.child_name || '孩子', current_state: report.current_state || 'unknown', last_seen: report.last_seen };
  currentReportPublished = Boolean(report.published);
  const usableQuality = value => value && !['暂无','暂无数据','暂无评价','暂无完整午睡记录','待老师发布'].includes(value);
  const quality = usableQuality(report.quality) ? report.quality : usableQuality(history.records[0]?.quality) ? history.records[0].quality : '平稳';
  const historyItems = history.records.slice(-8).reverse().map(r => `<div class="item"><strong>${fmtDateTime(r.sleep_start)}</strong><div class="muted">${fmtDur(r.duration_seconds)} / ${usableQuality(r.quality) ? r.quality : quality}</div></div>`);
  const reportItems = [
    `<div class="item"><strong>入睡时间</strong><div class="muted">${fmtDateTime(report.sleep_start)}</div></div>`,
    `<div class="item"><strong>起床时间</strong><div class="muted">${fmtDateTime(report.wake_time)}</div></div>`,
    `<div class="item"><strong>午睡时长</strong><div class="muted">${fmtDur(report.duration_seconds)}</div></div>`,
    `<div class="item"><strong>睡眠质量</strong><div class="muted">${quality}</div></div>`,
  ];
  const suggestion = report.suggestion || { title: '暂无AI建议', body: '老师端生成午睡数据后，这里会自动显示作息建议。' };
  root.innerHTML = `
    <div class="phone-app">
      <section class="app-hero">
        <div class="app-hero-top">
          <div>
            <div class="muted" style="color:rgba(255,255,255,.78)">${report.published ? `最近发布 · ${fmtTime(report.published_at)}` : '等待老师发布今日报告'}</div>
            <div class="app-child">${child.name || '孩子'}</div>
          </div>
          <div><div class="app-status">${stateText(child.current_state)}</div><div class="row" style="gap:6px;margin-top:8px"><button style="padding:7px 9px;border:0;background:rgba(255,255,255,.16);color:white" onclick="openBindingDialog()">选择孩子</button><button style="padding:7px 9px;border:0;background:rgba(255,255,255,.16);color:white" onclick="logoutParent()">退出账号</button></div></div>
        </div>
        <div class="app-quality">
          <div><strong>${quality}</strong><span>睡眠质量</span></div>
          <div style="text-align:right"><strong>${fmtDur(report.duration_seconds)}</strong><span>午睡时长</span></div>
        </div>
      </section>

      <section class="app-screen active" data-screen="today">
        <div class="app-card">
          <h2>今日报告</h2>
          <div class="app-metrics">
            <div class="app-metric"><span class="muted">入睡</span><b>${fmtTime(report.sleep_start)}</b></div>
            <div class="app-metric"><span class="muted">起床</span><b>${fmtTime(report.wake_time)}</b></div>
            <div class="app-metric"><span class="muted">状态</span><b>${stateText(child.current_state)}</b></div>
            <div class="app-metric"><span class="muted">发布</span><b>${fmtTime(report.published_at)}</b></div>
          </div>
        </div>
        <div class="app-card" style="margin-top:14px">
          <h2>报告明细</h2>
          <div class="app-feed">${listOrEmpty(reportItems, '今日暂无报告')}</div>
        </div>
        <div class="app-card" style="margin-top:14px">
          <h2>AI作息建议</h2>
          <div class="item"><strong>${suggestion.title}</strong><div class="muted">${suggestion.body}</div></div>
        </div>
      </section>

      <section class="app-screen" data-screen="growth">
        <div class="app-card">
          <h2>历史午睡记录</h2>
          <div class="app-feed">${listOrEmpty(historyItems, '暂无历史午睡记录')}</div>
        </div>
      </section>

      <nav class="bottom-tabs">
        <button data-tab="today" class="active" onclick="setTab('today')">报告</button>
        <button data-tab="growth" onclick="setTab('growth')">记录</button>
      </nav>
    </div>`;
  setTab(activeTab);
  applyLanguage();
}
// Keep the parent UI stable while the demo stream is running; reports refresh when the page is reopened.
new EventSource('/api/events').onmessage = () => {};
document.addEventListener('visibilitychange', () => activeTab === 'today' && markCurrentReportRead().catch(console.error));
loadChildOptions().then(() => ensureParentSession()).then(ok => ok ? loadParent() : loginDefaultParent()).catch(() => renderAuth());
"""


@app.route("/")
def home():
  frontend = react_frontend_or_none()
  if frontend:
    return frontend
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>幼儿午睡智能管理系统</title>
  <style>
    body { margin:0; min-height:100vh; display:grid; place-items:center; padding:24px; background:#f6f2e6; color:#2a342d; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif; }
    main { width:min(520px, 100%); padding:26px; border-radius:20px; background:#fffdf8; border:1px solid #e3d9cb; box-shadow:0 12px 30px rgba(35,46,36,.08); }
    h1 { margin:0 0 10px; font-size:26px; }
    p { color:#687465; line-height:1.7; }
    .links { display:grid; gap:12px; margin-top:20px; }
    a { display:block; padding:14px 16px; border-radius:14px; text-align:center; text-decoration:none; font-weight:800; background:#4a755c; color:white; }
    a.soft { background:#e6efe5; color:#315f4a; }
  </style>
</head>
<body>
  <main>
    <h1>幼儿午睡智能管理系统</h1>
    <p>教师端用于班级午睡监护和报告发布，家长端用于查看每日报告、历史记录和作息建议。</p>
    <div class="links">
      <a href="/teacher">打开教师端</a>
      <a href="/parent">打开家长端</a>
      <a class="soft" href="/teacher/install">安装教师端入口</a>
      <a class="soft" href="/parent/install">安装家长端入口</a>
    </div>
  </main>
</body>
</html>""", 200


@app.route("/teacher")
def teacher_dashboard():
  frontend = react_frontend_or_none()
  if frontend:
    return frontend
    return dashboard_html("教师端", "teacher-root", TEACHER_SCRIPT, "teacher-page")


@app.route("/assets/<path:filename>")
def frontend_asset(filename):
  return send_from_directory(FRONTEND_DIST / "assets", filename)


@app.route("/teacher/install")
def teacher_install_page():
    return install_page_html("午睡教师端", "班级午睡地图、AI干预确认、报告发布。", "/teacher", "teacher")


@app.route("/parent")
def parent_dashboard():
  frontend = react_frontend_or_none()
  if frontend:
    return frontend
    return dashboard_html("家长端", "parent-root", PARENT_SCRIPT, "parent-page")


@app.route("/parent/install")
def parent_install_page():
    return install_page_html("午睡家长端", "接收老师发布的每日午睡报告、查看记录和作息建议。", "/parent", "parent")


@app.route("/interventions/breathing-light")
def breathing_light_intervention():
  return send_from_directory(
      Path(__file__).resolve().parent / "interventions" / "breathing-light",
      "index.html",
  )


@app.route("/monitor/camera")
def camera_monitor_page():
  return send_from_directory(
      Path(__file__).resolve().parent / "monitoring" / "camera",
      "index.html",
  )


@app.route("/interventions/gesture-drawing")
def gesture_drawing_intervention():
  return send_from_directory(
      Path(__file__).resolve().parent / "interventions" / "gesture-drawing",
      "index.html",
  )


@app.route("/interventions/assets/<intervention>/<path:filename>")
def intervention_asset(intervention, filename):
  """Serve media used by the browser-based intervention pages."""
  folders = {
      "breathing-light": "breathing-light",
      "gesture-drawing": "gesture-drawing",
  }
  folder = folders.get(intervention)
  if folder is None:
    return jsonify({"error": "unknown intervention"}), 404
  base_dir = Path(__file__).resolve().parent / "interventions" / folder
  return send_from_directory(base_dir, filename)


def install_page_html(app_name: str, description: str, target_url: str, app_role: str) -> str:
    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#4a755c">
  <link rel="manifest" href="/manifest.webmanifest?app=__APP_ROLE__">
  <title>安装__APP_NAME__</title>
  <style>
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; display:grid; place-items:center; padding:22px; background:#e9efe8; color:#26342b; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif; }
    .phone { width:min(430px, 100%); border-radius:28px; background:#fffdf8; border:1px solid #dce5da; box-shadow:0 18px 46px rgba(31,48,34,.16); overflow:hidden; }
    .hero { padding:28px 22px; color:#fffdf8; background:linear-gradient(135deg,#315f4a,#7b8f6b); }
    h1 { margin:0; font-size:26px; letter-spacing:0; }
    p { margin:10px 0 0; line-height:1.7; color:rgba(255,255,255,.84); }
    .body { padding:22px; display:grid; gap:12px; }
    button, a { width:100%; display:block; text-align:center; border:0; border-radius:16px; padding:14px 16px; font:inherit; font-weight:800; text-decoration:none; }
    button { background:#4a755c; color:white; }
    a { background:#eef4e9; color:#315f4a; }
    .muted { color:#6f796d; font-size:13px; line-height:1.6; }
  </style>
</head>
<body>
  <main class="phone">
    <section class="hero">
      <h1>__APP_NAME__</h1>
      <p>__DESCRIPTION__</p>
    </section>
    <section class="body">
      <button id="install-btn">安装到手机桌面</button>
      <a href="__TARGET_URL__">直接打开</a>
      <div class="muted" id="hint">如果按钮暂时不可用，请用手机浏览器菜单里的“添加到主屏幕”。正式异地安装需要把服务部署到 HTTPS 地址。</div>
    </section>
  </main>
  <script>
    let deferredPrompt = null;
    const btn = document.getElementById('install-btn');
    const hint = document.getElementById('hint');
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.getRegistrations().then(items => items.forEach(item => item.unregister())).catch(() => {});
    }
    window.addEventListener('beforeinstallprompt', event => {
      event.preventDefault();
      deferredPrompt = event;
      btn.disabled = false;
      hint.textContent = '可以安装了。点击按钮后选择“安装”。';
    });
    btn.addEventListener('click', async () => {
      if (!deferredPrompt) {
        location.href = '__TARGET_URL__';
        return;
      }
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
    });
  </script>
</body>
</html>"""
    return (
        html.replace("__APP_ROLE__", app_role)
        .replace("__APP_NAME__", app_name)
        .replace("__DESCRIPTION__", description)
        .replace("__TARGET_URL__", target_url)
    )


@app.route("/manifest.webmanifest")
def manifest():
    app_role = request.args.get("app", "teacher")
    is_parent = app_role == "parent"
    return jsonify(
        {
            "name": "幼儿午睡家长端" if is_parent else "幼儿午睡教师端",
            "short_name": "午睡家长端" if is_parent else "午睡教师端",
            "start_url": "/parent" if is_parent else "/teacher",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f6f2e6",
            "theme_color": "#4a755c",
            "orientation": "portrait" if is_parent else "any",
            "icons": [
                {
                    "src": f"/app-icon.svg?app={app_role}",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        }
    )


@app.route("/app-icon.svg")
def app_icon():
    app_role = request.args.get("app", "teacher")
    label = "家" if app_role == "parent" else "师"
    color = "#315f4a" if app_role == "parent" else "#4a755c"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="112" fill="#f6f2e6"/>
<circle cx="256" cy="256" r="174" fill="{color}"/>
<text x="256" y="305" text-anchor="middle" font-size="172" font-family="Arial, 'Microsoft YaHei', sans-serif" font-weight="800" fill="#fffdf8">{label}</text>
</svg>"""
    return Response(svg, mimetype="image/svg+xml")


@app.route("/sw.js")
def service_worker():
    script = """
self.addEventListener('install', event => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {});
"""
    return Response(script, mimetype="application/javascript")


@app.route("/api/auth/register", methods=["POST"])
def register():
    payload = normalize_payload(request.json)
    phone = (payload.get("phone") or "").strip()
    password = payload.get("password") or ""
    role = payload.get("role") or "parent"
    name = payload.get("name") or ("老师" if role == "teacher" else "家长")
    child_id = payload.get("child_id") or ""
    child_name = payload.get("child_name") or ""
    if not phone or not password:
        return {"status": "error", "msg": "phone and password are required"}, 400
    if role not in ("teacher", "parent"):
        return {"status": "error", "msg": "role must be teacher or parent"}, 400
    with lock:
        existing = next((u for u in users.values() if u["phone"] == phone and u["role"] == role), None)
        if existing:
            return {"status": "error", "msg": "user already exists"}, 409
        if role == "parent":
            resolved = resolve_child_binding(child_id, child_name)
            if not resolved:
                return {"status": "error", "msg": "please select a valid child"}, 400
            child_id, child_name = resolved
            ensure_child(child_id, {"child_name": child_name})
        user_id = uuid.uuid4().hex
        user = {
            "id": user_id,
            "phone": phone,
            "password_hash": generate_password_hash(password),
            "role": role,
            "name": name,
            "child_id": child_id if role == "parent" else None,
            "child_name": child_name if role == "parent" else None,
        }
        users[user_id] = user
        token = uuid.uuid4().hex
        sessions[token] = user_id
        save_persistent_state()
    return jsonify({"status": "ok", "token": token, "user": public_user(user)})


@app.route("/api/auth/login", methods=["POST"])
def login():
    payload = normalize_payload(request.json)
    phone = (payload.get("phone") or "").strip()
    password = payload.get("password") or ""
    role = payload.get("role") or "parent"
    with lock:
        user = next(
            (
                u for u in users.values()
                if u["phone"] == phone
                and u["role"] == role
                and (
                    check_password_hash(u["password_hash"], password)
                    if u.get("password_hash")
                    else u.get("password") == password
                )
            ),
            None,
        )
        if not user:
            return {"status": "error", "msg": "invalid credentials"}, 401
        token = uuid.uuid4().hex
        sessions[token] = user["id"]
    return jsonify({"status": "ok", "token": token, "user": public_user(user)})


@app.route("/api/auth/me")
def auth_me():
    user = auth_user()
    if not user:
        return {"status": "anonymous"}, 401
    return jsonify({"status": "ok", "user": public_user(user)})


@app.route("/api/children/options")
def child_options():
    with lock:
        options = {item["id"]: item["name"] for item in DEMO_CHILDREN}
        options.update({child_id: child.get("name") or child_id for child_id, child in children.items() if child_id != DEFAULT_CHILD_ID})
        return jsonify({"children": [{"id": child_id, "name": name} for child_id, name in options.items()]})


@app.route("/api/parent/bind-child", methods=["POST"])
def bind_parent_child():
    user = auth_user()
    if not user or user.get("role") != "parent":
        return {"status": "unauthorized", "msg": "parent login required"}, 401
    payload = normalize_payload(request.json)
    with lock:
        resolved = resolve_child_binding(payload.get("child_id") or "", payload.get("child_name") or "")
        if not resolved:
            return {"status": "error", "msg": "child not found"}, 404
        user["child_id"], user["child_name"] = resolved
        ensure_child(user["child_id"], {"child_name": user["child_name"]})
        save_persistent_state()
    return jsonify({"status": "ok", "user": public_user(user)})


@app.route("/data", methods=["POST"])
def data():
    global last_data, last_time
    raw_body = request.get_data(as_text=True)
    normalized = normalize_payload(request.json)
    ts = now_ts()
    child_id = child_id_from(normalized)
    with lock:
        if not runtime_active or now_ts() < runtime_pause_until:
            return {"status": "stopped", "msg": "teacher monitoring is off"}, 409
        last_data = normalized
        last_time = ts
        child = ensure_child(child_id, normalized)
        old_state = child.get("state", "unknown")
        state, decision_metadata = classify_sensor_state(child_id, normalized)
        child.update(
            {
                "state": state,
                "emotion": normalized.get("emotion") or child.get("emotion"),
                "motion_frequency": normalized.get("motion") or normalized.get("motion_frequency"),
                "environment": parse_environment(normalized),
                "last_seen": iso(ts),
            }
        )
        update_sleep_transition(child_id, old_state, state, ts)
        sample = {
            "time": iso(ts),
            "child_id": child_id,
            "state": state,
            "hr": normalized.get("hr"),
            "br": normalized.get("br"),
            "mic": normalized.get("mic"),
            "motion": normalized.get("motion") or normalized.get("motion_frequency"),
            "environment": child["environment"],
            "decision": decision_metadata,
        }
        sensor_history[child_id].appendleft(sample)
        add_interaction(child_id, "sensor_update", sample)
        publish("child_state_updated", build_child_summary(child_id))
        maybe_create_ai_intervention(child_id, state, "sensor_state_monitor", decision_metadata)
    print("\n======================")
    print("收到ESP32原始请求体:")
    print(raw_body)
    print("标准化数据:")
    print(normalized)
    print("======================\n")
    return {
        "status": "ok",
        "msg": "received",
        "child_id": child_id,
        "classified_state": state,
        "decision_source": decision_metadata.get("source"),
    }, 200


@app.route("/data", methods=["GET"])
def data_get():
    with lock:
        if last_data is None:
            return {"status": "no data yet"}, 404
        return last_data, 200


@app.route("/api/device/camera-observation", methods=["POST"])
def camera_observation():
    payload = normalize_payload(request.json)
    child_id = child_id_from(payload)
    observation = {
        "time": iso(now_ts()),
        "child_id": child_id,
        "motion_ratio": number(payload.get("motion_ratio")),
        "gesture": str(payload.get("gesture") or "none")[:40],
        "hands_detected": int(number(payload.get("hands_detected")) or 0),
        "source": str(payload.get("source") or "browser_camera")[:60],
    }
    with lock:
        camera_observations[child_id].appendleft(observation)
        add_interaction(child_id, "camera_observation", observation)
        latest_sensor = dict(sensor_history[child_id][0]) if sensor_history[child_id] else {}
        latest_sensor["state"] = ensure_child(child_id).get("state", "unknown")
        state, decision_metadata = classify_sensor_state(child_id, latest_sensor)
        child = ensure_child(child_id)
        old_state = child.get("state", "unknown")
        child["state"] = state
        child["last_seen"] = observation["time"]
        update_sleep_transition(child_id, old_state, state, now_ts())
        add_interaction(child_id, "multimodal_state", {"state": state, "decision": decision_metadata})
        publish("camera_observation", {"child_id": child_id, "observation": observation, "decision": decision_metadata})
        publish("child_state_updated", build_child_summary(child_id))
        maybe_create_ai_intervention(child_id, state, "multimodal_state_monitor", decision_metadata)
    return jsonify(
        {
            "status": "ok",
            "child_id": child_id,
            "classified_state": state,
            "decision_source": decision_metadata.get("source"),
            "trend": decision_metadata.get("trend"),
        }
    )


@app.route("/api/ai/decision", methods=["POST"])
def ai_decision():
    payload = normalize_payload(request.json)
    child_id = child_id_from(payload)
    state = payload.get("state") or "unknown"
    proposed_action = payload.get("proposed_action") or {}
    if (not proposed_action or proposed_action.get("type") in (None, "", "none")) and state in ("sleepy", "need_help", "alarm"):
        proposed_action = demo_action_for_state(state)
    sensor = payload.get("sensor") or {}
    llm_result = payload.get("llm_result") or {}
    ts = now_ts()
    with intervention_cv:
        if not runtime_active or now_ts() < runtime_pause_until:
            return jsonify({"status": "stopped", "execute": False, "msg": "teacher monitoring is off"}), 409
        child = ensure_child(child_id, payload)
        old_state = child.get("state", "unknown")
        child["state"] = state
        child["last_seen"] = iso(ts)
        child["environment"] = {**child.get("environment", {}), **parse_environment(sensor)}
        child["motion_frequency"] = sensor.get("motion") or child.get("motion_frequency")
        update_sleep_transition(child_id, old_state, state, ts)
        add_interaction(child_id, "ai_state", {"state": state, "sensor": sensor})
        if not proposed_action or proposed_action.get("type") in (None, "", "none"):
            publish("child_state_updated", build_child_summary(child_id))
            return jsonify({"status": "no_intervention", "execute": False})
        plan_id = uuid.uuid4().hex
        plan = {
            "id": plan_id,
            "child_id": child_id,
            "child_name": child.get("name"),
            "state": state,
            "proposed_action": proposed_action,
            "final_action": None,
            "llm_result": llm_result,
            "status": "pending",
            "created_at": iso(ts),
            "deadline_ts": ts + 5,
            "resolved_at": None,
            "origin": "ai",
            "execution_status": "awaiting_approval",
            "execution_updated_at": iso(ts),
            "execution_feedback": None,
        }
        interventions[plan_id] = plan
        add_interaction(child_id, "ai_intervention_pending", {"plan_id": plan_id, "action": proposed_action})
        publish("ai_intervention_pending", plan)
        while plan["status"] == "pending":
            remaining = plan["deadline_ts"] - now_ts()
            if remaining <= 0:
                break
            intervention_cv.wait(timeout=remaining)
        if plan["status"] == "pending":
            plan["status"] = "auto_approved"
            plan["final_action"] = proposed_action
            plan["resolved_at"] = iso(now_ts())
        add_interaction(child_id, "ai_intervention_resolved", {"plan_id": plan_id, "status": plan["status"], "action": plan["final_action"]})
        publish("ai_intervention_resolved", plan)
        should_dispatch = plan["status"] != "cancelled" and bool(plan.get("final_action"))
        if should_dispatch:
            dispatch_intervention(plan)
        return jsonify(
            {
                "status": plan["status"],
                "plan_id": plan_id,
                "execute": False,
                "dispatched": should_dispatch,
                "dispatch_owner": "server",
                "action": plan["final_action"],
            }
        )


@app.route("/api/teacher/class-overview")
def teacher_class_overview():
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with lock:
        ensure_class_roster()
        summaries = sorted((build_child_summary(cid) for cid in children), key=lambda c: (c["seat_index"], c["name"]))
        state_counts = Counter(c["current_state"] for c in summaries)
        durations = [r["duration_seconds"] for records in sleep_records.values() for r in records if r.get("duration_seconds") is not None]
        pending = [p for p in interventions.values() if p["status"] == "pending"]
        return jsonify(
            {
                "children": summaries,
                "pending_interventions": sorted(pending, key=lambda p: p["deadline_ts"]),
                "stats": {
                    "state_distribution": dict(state_counts),
                    "sleeping_count": state_counts.get("sleeping", 0),
                    "avg_sleep_seconds": int(sum(durations) / len(durations)) if durations else None,
                },
            }
        )


def build_child_report(child_id: str) -> dict:
    child = ensure_child(child_id)
    records = sleep_records[child_id][-30:]
    summary = build_child_summary(child_id)
    return {
        "child_id": child_id,
        "child_name": child.get("name"),
        "generated_at": iso(now_ts()),
        "current_state": summary.get("current_state"),
        "emotion": child.get("emotion"),
        "sleep_start": child.get("sleep_start"),
        "wake_time": child.get("wake_time"),
        "duration_seconds": summary.get("sleep_duration_seconds") or (records[-1].get("duration_seconds") if records else None),
        "sleep_quality": child.get("sleep_quality"),
        "teacher_summary": summary,
        "environment": child.get("environment") or {},
        "pending_intervention": get_pending_intervention(child_id),
        "sleep_records": records,
        "interactions": list(interactions[child_id])[:100],
        "parent_feedback": parent_feedback[child_id][-30:],
    }


def parent_suggestion_for(child_id: str) -> dict:
    records = sleep_records[child_id][-14:]
    child = ensure_child(child_id)
    current_duration = None
    if child_id in active_sleep_starts:
        current_duration = int(now_ts() - active_sleep_starts[child_id])
    elif records:
        current_duration = records[-1].get("duration_seconds")
    durations = [r.get("duration_seconds") for r in records if isinstance(r.get("duration_seconds"), (int, float))]
    avg = sum(durations) / len(durations) if durations else None
    quality = child.get("sleep_quality")
    if current_duration is None and not durations:
        title = "等待今日午睡报告"
        body = "老师发布今日午睡报告后，这里会结合午睡时长、睡眠质量和近期趋势生成作息建议。"
        level = "pending"
    elif current_duration is not None and current_duration < 1800:
        title = "午睡偏短，今晚建议提前入睡"
        body = "今天午睡不足 30 分钟，晚间可以提前 15-20 分钟进入洗漱、讲故事和关灯流程，减少睡前兴奋活动。"
        level = "attention"
    elif current_duration is not None and current_duration > 7200:
        title = "午睡偏长，今晚观察入睡时间"
        body = "今天午睡超过 2 小时，晚间可以保持安静活动，但不必过早上床；如果夜间入睡延后，明天可适当缩短午睡。"
        level = "watch"
    elif avg is not None and avg < 2400:
        title = "近期午睡略短，建议稳定午休前节奏"
        body = "最近午睡平均时长偏短，可以在午饭后固定 10 分钟安静阅读或轻音乐，帮助身体形成午休信号。"
        level = "attention"
    elif avg is not None and avg > 6600:
        title = "近期午睡较长，留意夜间作息"
        body = "最近午睡平均时长较长，如果晚上入睡困难，可以和老师沟通午睡唤醒时间，避免白天睡眠挤占夜间睡眠。"
        level = "watch"
    elif quality in ("易醒", "一般"):
        title = "睡眠质量一般，今晚保持低刺激"
        body = "今天午睡质量一般，晚间建议减少屏幕和剧烈游戏，保持卧室光线偏暗、声音稳定。"
        level = "watch"
    else:
        title = "作息较稳定，继续保持"
        body = "今天午睡表现平稳，晚间按平时节奏入睡即可，继续保持固定的睡前仪式。"
        level = "good"
    return {
        "title": title,
        "body": body,
        "level": level,
        "avg_duration_seconds": int(avg) if avg is not None else None,
        "source": "rules",
    }


def ai_parent_suggestion_for(child_id: str) -> dict:
    fallback = parent_suggestion_for(child_id)
    records = sleep_records[child_id][-14:]
    if not DASHSCOPE_API_KEY or not records:
        return fallback

    child = ensure_child(child_id)
    context = {
        "recent_sleep_records": [
            {
                "duration_seconds": item.get("duration_seconds"),
                "quality": item.get("quality"),
                "sleep_start": item.get("sleep_start"),
                "wake_time": item.get("wake_time"),
            }
            for item in records
        ],
        "current_environment": child.get("environment") or {},
        "recent_parent_feedback": [
            {
                "body_condition": item.get("body_condition"),
                "last_night_sleep": item.get("last_night_sleep"),
            }
            for item in parent_feedback[child_id][-3:]
        ],
    }
    prompt = f"""
You generate a cautious, practical evening routine suggestion for the parent of a kindergarten child.
Use only the non-identifying nap summary below. Do not diagnose illness or make medical claims.
Return JSON only: {{"title": "Chinese title under 24 characters", "body": "Chinese advice in 1-2 sentences", "level": "good|watch|attention"}}.
Context:
{json.dumps(context, ensure_ascii=False)}
""".strip()
    try:
        result = call_llm_json(prompt)
        title = str(result.get("title") or "").strip()
        body = str(result.get("body") or "").strip()
        level = result.get("level") if result.get("level") in ("good", "watch", "attention") else fallback["level"]
        if not title or not body:
            return fallback
        return {
            "title": title[:48],
            "body": body[:300],
            "level": level,
            "avg_duration_seconds": fallback.get("avg_duration_seconds"),
            "source": "llm",
            "model": DASHSCOPE_MODEL,
        }
    except Exception as exc:
        return {**fallback, "source": "rules_fallback", "llm_error": type(exc).__name__}


def build_parent_report_snapshot(child_id: str, publisher: dict) -> dict:
    child = ensure_child(child_id)
    summary = build_child_summary(child_id)
    records = sleep_records[child_id]
    latest = records[-1] if records else {}
    duration = summary.get("sleep_duration_seconds")
    if duration is None:
        duration = latest.get("duration_seconds")
    sleep_start = child.get("sleep_start") or latest.get("sleep_start")
    wake_time = child.get("wake_time") or latest.get("wake_time")
    quality = child.get("sleep_quality") or latest.get("quality")
    if duration is None:
        quality = quality or "暂无完整午睡记录"
    elif not quality:
        quality = "进行中" if child.get("state") == "sleeping" else "暂无评价"
    return {
        "report_id": uuid.uuid4().hex,
        "child_id": child_id,
        "child_name": child.get("name"),
        "published": True,
        "published_at": iso(now_ts()),
        "published_by": publisher.get("name") or "老师",
        "recipient_count": sum(1 for user in users.values() if user.get("role") == "parent" and user.get("child_id") == child_id),
        "delivered_at": None,
        "read_at": None,
        "current_state": summary.get("current_state"),
        "last_seen": child.get("last_seen"),
        "sleep_start": sleep_start,
        "wake_time": wake_time,
        "duration_seconds": duration,
        "quality": quality,
        "emotion": child.get("emotion"),
        "environment": child.get("environment") or {},
        "teacher_summary": summary,
        "suggestion": ai_parent_suggestion_for(child_id),
        "interventions": visible_intervention_events(child_id),
    }


def store_published_report(child_id: str, teacher: dict) -> dict:
    report = build_parent_report_snapshot(child_id, teacher)
    previous = published_reports[child_id][-1] if published_reports[child_id] else None
    if previous and previous.get("published_at", "")[:10] == report["published_at"][:10]:
        published_reports[child_id][-1] = report
    else:
        published_reports[child_id].append(report)
    published_reports[child_id] = published_reports[child_id][-90:]
    add_interaction(child_id, "report_published", {"report_id": report["report_id"], "teacher": teacher.get("name")})
    return report


def class_report() -> dict:
    with lock:
        return {
            "generated_at": iso(now_ts()),
            "children": [build_child_summary(cid) for cid in children],
            "pending_interventions": [p for p in interventions.values() if p["status"] == "pending"],
            "sleep_record_count": sum(len(records) for records in sleep_records.values()),
        }


@app.route("/api/children/<child_id>/detail")
def child_detail(child_id):
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with lock:
        ensure_child(child_id)
        child = children[child_id]
        if child.get("unread_parent_feedback_count"):
            child["unread_parent_feedback_count"] = 0
        return jsonify(
            {
                "child": build_child_summary(child_id),
                "samples": list(sensor_history[child_id])[:100],
                "sleep_records": sleep_records[child_id][-30:],
                "interactions": list(interactions[child_id])[:100],
                "parent_feedback": parent_feedback[child_id][-30:],
            }
        )


@app.route("/api/interventions/<plan_id>/cancel", methods=["POST"])
def cancel_intervention(plan_id):
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with intervention_cv:
        plan = interventions.get(plan_id)
        if not plan:
            return {"status": "not_found"}, 404
        if plan["status"] != "pending":
            return {"status": "already_resolved", "plan": plan}, 409
        plan["status"] = "cancelled"
        plan["final_action"] = None
        plan["resolved_at"] = iso(now_ts())
        plan["execution_status"] = "cancelled"
        plan["execution_updated_at"] = plan["resolved_at"]
        plan["execution_feedback"] = {"status": "cancelled", "time": plan["resolved_at"], "source": "teacher"}
        add_interaction(plan["child_id"], "teacher_cancelled_intervention", {"plan_id": plan_id})
        publish("teacher_intervention_cancelled", plan)
        intervention_cv.notify_all()
        return jsonify({"status": "ok", "plan": plan})


@app.route("/api/interventions/<plan_id>/override", methods=["POST"])
def override_intervention(plan_id):
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    payload = normalize_payload(request.json)
    action = {
        "type": payload.get("action_type") or payload.get("type"),
        "param": payload.get("param"),
        "label": payload.get("label") or payload.get("action_type") or payload.get("type"),
        "source": "teacher",
    }
    if not action["type"]:
        return {"status": "error", "msg": "action_type is required"}, 400
    dispatch_now = False
    with intervention_cv:
        plan = interventions.get(plan_id)
        if not plan:
            return {"status": "not_found"}, 404
        if plan["status"] != "pending":
            return {"status": "already_resolved", "plan": plan}, 409
        plan["status"] = "overridden"
        plan["final_action"] = action
        plan["resolved_at"] = iso(now_ts())
        add_interaction(plan["child_id"], "teacher_overrode_intervention", {"plan_id": plan_id, "action": action})
        publish("teacher_intervention_overridden", plan)
        dispatch_now = plan.get("origin") == "demo"
        intervention_cv.notify_all()
    if dispatch_now:
        with lock:
            dispatch_intervention(plan)
    return jsonify({"status": "ok", "plan": plan, "dispatched": dispatch_now})


@app.route("/api/children/<child_id>/interventions", methods=["POST"])
def create_manual_intervention(child_id):
    teacher = auth_user()
    if not teacher or teacher.get("role") != "teacher":
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    payload = normalize_payload(request.json)
    action_type = payload.get("action_type") or payload.get("type")
    if action_type not in ACTION_LABELS:
        return {"status": "error", "msg": "unsupported action_type"}, 400
    ts = now_ts()
    with lock:
        child = ensure_child(child_id)
        action = {
            "type": action_type,
            "param": payload.get("param") or "manual",
            "label": payload.get("label") or ACTION_LABELS[action_type],
            "source": "teacher",
        }
        plan_id = uuid.uuid4().hex
        plan = {
            "id": plan_id,
            "child_id": child_id,
            "child_name": child.get("name"),
            "state": child.get("state"),
            "proposed_action": action,
            "final_action": action,
            "llm_result": None,
            "status": "teacher_approved",
            "created_at": iso(ts),
            "deadline_ts": None,
            "resolved_at": iso(ts),
            "origin": "manual",
            "execution_status": "queued",
            "execution_updated_at": iso(ts),
            "execution_feedback": None,
        }
        interventions[plan_id] = plan
        add_interaction(child_id, "teacher_manual_intervention", {"plan_id": plan_id, "action": action, "teacher": teacher.get("name")})
        dispatch_intervention(plan)
    return jsonify({"status": "accepted", "execution_connected": has_local_intervention_endpoint(child_id), "plan": plan}), 202


@app.route("/api/device/interventions/<plan_id>/feedback", methods=["GET", "POST"])
def intervention_device_feedback(plan_id):
    payload = normalize_payload(request.json) if request.method == "POST" else normalize_payload(request.args.to_dict())
    status = payload.get("status") or "started"
    if status not in ("received", "started", "completed", "failed", "stopped"):
        return {"status": "error", "msg": "invalid feedback status"}, 400
    plan = record_execution_feedback(
        plan_id,
        status,
        {
            "source": payload.get("source") or "device",
            "message": payload.get("message") or "",
        },
    )
    if not plan:
        return {"status": "not_found"}, 404
    return jsonify({"status": "ok", "plan_id": plan_id, "execution_status": plan.get("execution_status")})


@app.route("/api/device/interventions/<plan_id>/control")
def intervention_device_control(plan_id):
    """Small polling endpoint for browser-based intervention pages."""
    with lock:
        plan = interventions.get(plan_id)
        if not plan:
            return {"status": "not_found"}, 404
        action = plan.get("final_action") or plan.get("proposed_action") or {}
        response = jsonify(
            {
                "status": "ok",
                "plan_id": plan_id,
                "execution_status": plan.get("execution_status"),
                "plan_status": plan.get("status"),
                "action_type": action.get("type"),
                "stop_requested": plan.get("execution_status") in ("stopped", "cancelled", "failed"),
            }
        )
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Cache-Control"] = "no-store"
        return response


@app.route("/api/interventions/<plan_id>/stop", methods=["POST"])
def stop_running_intervention(plan_id):
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with lock:
        plan = interventions.get(plan_id)
        if not plan:
            return {"status": "not_found"}, 404
        action = plan.get("final_action") or plan.get("proposed_action") or {}
        if action.get("type") in ("light", "game"):
            plan = record_execution_feedback(plan_id, "stopped", {"source": "teacher", "reason": "teacher_stopped_browser_page"})
            return jsonify({"status": "ok", "plan_id": plan_id, "execution_status": plan.get("execution_status")})
        if action.get("type") not in ("white_noise", "story"):
            return {"status": "not_supported", "msg": "intervention type cannot be stopped"}, 409
        process = running_processes.get(plan_id)
        if not process or process.poll() is not None:
            return {"status": "not_running"}, 409
        process.terminate()
    record_execution_feedback(plan_id, "stopped", {"source": "teacher", "reason": "teacher_stopped"})
    return jsonify({"status": "ok", "plan_id": plan_id, "execution_status": "stopped"})


@app.route("/api/teacher/<child_id>/publish-report", methods=["POST"])
def publish_parent_report(child_id):
    teacher = auth_user()
    if not teacher or teacher.get("role") != "teacher":
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with lock:
        ensure_child(child_id)
        report = store_published_report(child_id, teacher)
        save_persistent_state()
    publish("parent_report_published", {"child_id": child_id, "report_id": report["report_id"]})
    return jsonify({"status": "ok", "report": report})


@app.route("/api/teacher/publish-all-reports", methods=["POST"])
def publish_all_parent_reports():
    teacher = auth_user()
    if not teacher or teacher.get("role") != "teacher":
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    reports = []
    with lock:
        ensure_class_roster()
        for child_id in sorted(children, key=lambda cid: child_positions.get(cid, 9999)):
            reports.append(store_published_report(child_id, teacher))
        save_persistent_state()
    publish("class_reports_published", {"count": len(reports), "child_ids": [report["child_id"] for report in reports]})
    return jsonify(
        {
            "status": "ok",
            "published_count": len(reports),
            "recipient_count": sum(report["recipient_count"] for report in reports),
            "skipped_count": 0,
            "skipped_child_ids": [],
        }
    )


@app.route("/api/teacher/child-order", methods=["POST"])
def update_child_order():
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    ordered_ids = (normalize_payload(request.json).get("ordered_ids") or [])
    if not isinstance(ordered_ids, list):
        return {"status": "error", "msg": "ordered_ids must be a list"}, 400
    with lock:
        known_ids = set(children)
        requested = [str(child_id) for child_id in ordered_ids if str(child_id) in known_ids]
        remainder = sorted(known_ids - set(requested), key=lambda child_id: child_positions.get(child_id, 9999))
        for index, child_id in enumerate(requested + remainder):
            child_positions[child_id] = index
        save_persistent_state()
    publish("child_order_updated", {"ordered_ids": requested + remainder})
    return jsonify({"status": "ok", "ordered_ids": requested + remainder})


@app.route("/api/parent/<child_id>/today-report")
def parent_today_report(child_id):
    if not is_bound_parent(child_id):
        return {"status": "unauthorized", "msg": "bound parent login required"}, 401
    if not demo_mode_enabled():
        start_demo_mode()
    with lock:
        ensure_child(child_id)
        if published_reports[child_id]:
            report = published_reports[child_id][-1]
            if not report.get("delivered_at"):
                report["delivered_at"] = iso(now_ts())
                save_persistent_state()
                publish("parent_report_delivered", {"child_id": child_id, "report_id": report["report_id"]})
            summary = build_child_summary(child_id)
            latest_record = sleep_records[child_id][-1] if sleep_records[child_id] else {}
            report["current_state"] = summary.get("current_state") or report.get("current_state")
            report["last_seen"] = summary.get("last_seen") or report.get("last_seen")
            report["duration_seconds"] = summary.get("sleep_duration_seconds") or report.get("duration_seconds") or latest_record.get("duration_seconds")
            report["sleep_start"] = summary.get("sleep_start") or report.get("sleep_start") or latest_record.get("sleep_start")
            if report.get("quality") in (None, "暂无", "暂无数据", "暂无评价", "暂无完整午睡记录"):
                quality_candidates = [children[child_id].get("sleep_quality"), latest_record.get("quality")]
                report["quality"] = next((value for value in quality_candidates if value and value not in ("暂无", "暂无数据", "暂无评价", "暂无完整午睡记录")), "平稳")
            return jsonify(report)
        child = children[child_id]
        return jsonify(
            {
                "child_id": child_id,
                "child_name": child.get("name"),
                "published": False,
                "published_at": None,
                "current_state": "unknown",
                "last_seen": None,
                "sleep_start": None,
                "wake_time": None,
                "duration_seconds": None,
                "quality": "待老师发布",
                "suggestion": {
                    "title": "等待今日午睡报告",
                    "body": "老师完成午睡观察并发布后，报告和 AI 作息建议会自动出现在这里。",
                    "level": "pending",
                    "avg_duration_seconds": None,
                },
            }
        )


@app.route("/api/parent/<child_id>/report-read", methods=["POST"])
def mark_parent_report_read(child_id):
    if not is_bound_parent(child_id):
        return {"status": "unauthorized", "msg": "bound parent login required"}, 401
    with lock:
        if not published_reports[child_id]:
            return {"status": "not_found", "msg": "no published report"}, 404
        report = published_reports[child_id][-1]
        if not report.get("read_at"):
            report["read_at"] = iso(now_ts())
            save_persistent_state()
            publish("parent_report_read", {"child_id": child_id, "report_id": report["report_id"]})
    return jsonify({"status": "ok", "read_at": report["read_at"]})


@app.route("/api/parent/<child_id>/report")
def parent_child_report(child_id):
    with lock:
        report = build_child_report(child_id)
    if request.args.get("format") == "csv":
        lines = [
            "key,value",
            f"child_id,{report['child_id']}",
            f"child_name,{report['child_name']}",
            f"generated_at,{report['generated_at']}",
            f"current_state,{report['current_state']}",
            f"emotion,{report['emotion']}",
            f"sleep_start,{report['sleep_start']}",
            f"wake_time,{report['wake_time']}",
            f"sleep_quality,{report['sleep_quality']}",
        ]
        body = "\n".join(lines)
        return Response(body, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=parent-report-{child_id}.csv"})
    return Response(json.dumps(report, ensure_ascii=False), mimetype="application/json")


@app.route("/api/teacher/class-report")
def teacher_class_report():
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    report = class_report()
    if request.args.get("format") == "csv":
        lines = ["child_id,name,current_state,sleep_start,wake_time,sleep_quality"]
        for child in report["children"]:
            lines.append(
                ",".join([
                    child["id"],
                    child["name"],
                    child["current_state"],
                    child.get("sleep_start", ""),
                    child.get("wake_time", ""),
                    child.get("sleep_quality", ""),
                ])
            )
        body = "\n".join(lines)
        return Response(body, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=teacher-class-report.csv"})
    return Response(json.dumps(report, ensure_ascii=False), mimetype="application/json")


@app.route("/api/teacher/<child_id>/report")
def teacher_child_report(child_id):
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with lock:
        report = build_child_report(child_id)
    if request.args.get("format") == "csv":
        lines = [
            "key,value",
            f"child_id,{report['child_id']}",
            f"child_name,{report['child_name']}",
            f"generated_at,{report['generated_at']}",
            f"current_state,{report['current_state']}",
            f"emotion,{report['emotion']}",
            f"sleep_start,{report['sleep_start']}",
            f"wake_time,{report['wake_time']}",
            f"sleep_quality,{report['sleep_quality']}",
        ]
        body = "\n".join(lines)
        return Response(body, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=teacher-report-{child_id}.csv"})
    return Response(json.dumps(report, ensure_ascii=False), mimetype="application/json")


@app.route("/api/parent/<child_id>/sleep-growth")
def parent_sleep_growth(child_id):
    if not is_bound_parent(child_id):
        return {"status": "unauthorized", "msg": "bound parent login required"}, 401
    with lock:
        records = [
            {
                "report_id": report["report_id"],
                "sleep_start": report.get("sleep_start"),
                "wake_time": report.get("wake_time"),
                "duration_seconds": report.get("duration_seconds"),
                "quality": report.get("quality"),
                "published_at": report.get("published_at"),
            }
            for report in published_reports[child_id][-60:]
        ]
        durations = [r["duration_seconds"] for r in records if r.get("duration_seconds") is not None]
        return jsonify(
            {
                "child_id": child_id,
                "records": records,
                "weekly_avg_seconds": int(sum(durations[-7:]) / len(durations[-7:])) if durations[-7:] else None,
                "monthly_avg_seconds": int(sum(durations[-30:]) / len(durations[-30:])) if durations[-30:] else None,
            }
        )


@app.route("/api/parent/<child_id>/ai-suggestions")
def parent_ai_suggestions(child_id):
    if not is_bound_parent(child_id):
        return {"status": "unauthorized", "msg": "bound parent login required"}, 401
    with lock:
        records = sleep_records[child_id][-14:]
        feedback = parent_feedback[child_id][-3:]
        suggestions = []
        if not records:
            suggestions.append("暂未形成足够午睡历史，建议连续观察 3-5 天后查看趋势。")
        else:
            avg = sum(r.get("duration_seconds", 0) for r in records) / len(records)
            if avg < 1800:
                suggestions.append("近期午睡时长偏短，可尝试提前 10-15 分钟进入安静活动。")
            elif avg > 7200:
                suggestions.append("近期午睡时长较长，请结合夜间入睡时间观察是否影响晚睡。")
            else:
                suggestions.append("近期午睡时长处于较稳定区间，继续保持固定作息。")
        if feedback:
            suggestions.append("教师端已同步家长提交的身体和昨晚睡眠情况，会结合午睡表现观察。")
        return jsonify({"child_id": child_id, "suggestions": suggestions})


@app.route("/api/parent/<child_id>/feedback", methods=["POST"])
def submit_parent_feedback(child_id):
    if not is_bound_parent(child_id):
        return {"status": "unauthorized", "msg": "bound parent login required"}, 401
    payload = normalize_payload(request.json)
    item = {
        "id": uuid.uuid4().hex,
        "child_id": child_id,
        "body_condition": payload.get("body_condition") or "",
        "last_night_sleep": payload.get("last_night_sleep") or "",
        "note": payload.get("note") or "",
        "time": iso(now_ts()),
    }
    with lock:
        child = ensure_child(child_id)
        child["unread_parent_feedback_count"] = child.get("unread_parent_feedback_count", 0) + 1
        parent_feedback[child_id].append(item)
        add_interaction(child_id, "parent_feedback", item)
        publish("parent_feedback_submitted", item)
    return jsonify({"status": "ok", "feedback": item})


@app.route("/api/parent/<child_id>/interactions")
def parent_interactions(child_id):
    if not is_bound_parent(child_id):
        return {"status": "unauthorized", "msg": "bound parent login required"}, 401
    with lock:
        latest = published_reports[child_id][-1] if published_reports[child_id] else {}
        return jsonify({"child_id": child_id, "records": latest.get("interventions", [])})


@app.route("/api/debug/demo/start", methods=["POST"])
def debug_demo_start():
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with lock:
        if not runtime_active or now_ts() < runtime_pause_until:
            return {"status": "stopped", "msg": "teacher monitoring is off"}, 409
    started = start_demo_mode()
    return jsonify({"status": "ok", "enabled": demo_mode_enabled(), "started": started})


@app.route("/api/debug/demo/stop", methods=["POST"])
def debug_demo_stop():
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    stop_demo_mode()
    return jsonify({"status": "ok", "enabled": demo_mode_enabled()})


@app.route("/api/debug/demo/status")
def debug_demo_status():
    return jsonify({"enabled": demo_mode_enabled(), "children": [c["id"] for c in DEMO_CHILDREN]})


@app.route("/api/debug/demo/trigger", methods=["POST"])
def debug_demo_trigger():
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with lock:
        if not runtime_active or now_ts() < runtime_pause_until:
            return {"status": "stopped", "msg": "teacher monitoring is off"}, 409
    if not demo_mode_enabled():
        start_demo_mode()
        time.sleep(0.1)
    with lock:
        target = random.choice([child for child in DEMO_CHILDREN if child["id"] != LOCAL_INTERVENTION_CHILD_ID])
        child = ensure_child(target["id"], target)
        old_state = child.get("state", "unknown")
        ts = now_ts()
        child.update(
            {
                "name": target["name"],
                "state": "alarm",
                "emotion": "轻微不安",
                "motion_frequency": random.randint(420, 680),
                "environment": {
                    "temperature": round(random.uniform(24.0, 27.0), 1),
                    "humidity": random.randint(45, 64),
                    "noise": round(random.uniform(0.42, 0.78), 2),
                    "brightness": random.randint(35, 120),
                    "heart_rate": random.randint(96, 118),
                    "breath_rate": random.randint(22, 30),
                },
                "last_seen": iso(ts),
            }
        )
        update_sleep_transition(target["id"], old_state, "alarm", ts)
        add_interaction(target["id"], "demo_manual_alarm", {"source": "debug_button"})
        publish("child_state_updated", build_child_summary(target["id"]))
        plan = create_demo_intervention(target["id"], "alarm")
    return jsonify({"status": "ok", "child_id": target["id"], "plan": plan})


@app.route("/api/events")
def events():
    subscriber = queue.Queue(maxsize=100)
    with lock:
        event_subscribers.append(subscriber)

    def stream():
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                try:
                    event = subscriber.get(timeout=20)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            with lock:
                if subscriber in event_subscribers:
                    event_subscribers.remove(subscriber)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/runtime/heartbeat", methods=["POST"])
def teacher_runtime_heartbeat():
    global last_teacher_heartbeat, runtime_active
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with lock:
        last_teacher_heartbeat = now_ts()
        runtime_active = now_ts() >= runtime_pause_until
    return jsonify({"status": "ok", "active": runtime_active})


@app.route("/api/runtime/start", methods=["POST"])
def start_teacher_runtime():
    global last_teacher_heartbeat, runtime_active, runtime_pause_until
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with lock:
        ensure_class_roster()
        runtime_pause_until = 0.0
        last_teacher_heartbeat = now_ts()
        runtime_active = True
    publish("runtime_started", {"time": iso(now_ts())})
    return jsonify({"status": "ok", "active": True})


@app.route("/api/runtime/stop-all", methods=["POST"])
def stop_all_interventions():
    global runtime_pause_until
    if not is_teacher():
        return {"status": "unauthorized", "msg": "teacher login required"}, 401
    with lock:
        runtime_pause_until = now_ts() + 15
    stop_active_runtime("teacher_stopped_all")
    publish("all_interventions_stopped", {"time": iso(now_ts())})
    return jsonify({"status": "ok", "stopped": True, "pause_seconds": 15})


@app.route("/api/runtime/status")
def runtime_status():
    with lock:
        response = jsonify(
            {
                "active": runtime_active,
                "paused": now_ts() < runtime_pause_until,
                "seconds_since_teacher": round(now_ts() - last_teacher_heartbeat, 1) if last_teacher_heartbeat else None,
            }
        )
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response


@app.route("/health")
def health():
    with lock:
        ensure_class_roster()
        return jsonify(
            {
                "status": "ok",
                "runtime_active": runtime_active,
                "cloud_runtime_always_on": CLOUD_RUNTIME_ALWAYS_ON,
                "children_count": len(children),
                "reports_count": sum(len(items) for items in published_reports.values()),
                "demo_enabled": demo_mode_enabled(),
            }
        )


@app.route("/api/spec")
def api_spec():
    return jsonify(
        {
            "pages": ["/teacher", "/parent"],
            "demo": ["POST /api/debug/demo/start", "POST /api/debug/demo/stop", "POST /api/debug/demo/trigger"],
            "rest": [
                "POST /data",
                "POST /api/ai/decision",
                "GET /api/teacher/class-overview",
                "POST /api/teacher/<child_id>/publish-report",
                "POST /api/teacher/publish-all-reports",
                "GET /api/children/<child_id>/detail",
                "POST /api/interventions/<plan_id>/cancel",
                "POST /api/interventions/<plan_id>/override",
                "POST /api/interventions/<plan_id>/stop",
                "POST /api/runtime/stop-all",
                "POST /api/children/<child_id>/interventions",
                "GET|POST /api/device/interventions/<plan_id>/feedback",
                "GET /api/parent/<child_id>/today-report",
                "GET /api/parent/<child_id>/sleep-growth",
                "GET /api/parent/<child_id>/ai-suggestions",
                "POST /api/parent/<child_id>/feedback",
            ],
            "realtime": "GET /api/events (SSE)",
        }
    )


@app.route("/page_event", methods=["GET"])
def page_event():
    return last_page_event, 200


def set_page_event(page: str, event: str):
    global last_page_event
    with lock:
        last_page_event = {"page": page, "event": event, "time": now_ts(), "id": last_page_event["id"] + 1}
        add_interaction(DEFAULT_CHILD_ID, f"{page}_{event}", {"page": page, "event": event})
        publish("page_event", last_page_event)


@app.route("/game_camera", methods=["GET"])
def game_camera():
    set_page_event("game", "camera_opened")
    return {"status": "ok", "page": "game", "event": "camera_opened"}, 200


@app.route("/white_camera", methods=["GET"])
def white_camera():
    set_page_event("white", "camera_opened")
    return {"status": "ok", "page": "white", "event": "camera_opened"}, 200


@app.route("/game_end", methods=["GET"])
def game_end():
    set_page_event("game", "closed")
    return {"status": "ok", "page": "game", "event": "closed"}, 200


@app.route("/white_end", methods=["GET"])
def white_end():
    set_page_event("white", "closed")
    return {"status": "ok", "page": "white", "event": "closed"}, 200


@app.route("/status", methods=["GET"])
def status():
    with lock:
        return {
            "status": "ok" if last_data is not None else "no data yet",
            "last_data": last_data,
            "seconds_ago": round(now_ts() - last_time, 2) if last_time else None,
            "page_event": last_page_event,
            "children": list(children.keys()),
            "demo_enabled": demo_mode_enabled(),
            "pending_interventions": [p for p in interventions.values() if p["status"] == "pending"],
            "active_executions": [
                p for p in interventions.values()
                if p.get("execution_status") in ("queued", "received", "started")
            ],
        }


threading.Thread(target=runtime_watchdog, daemon=True).start()


if __name__ == "__main__":
    print("Flask启动中...")
    port = int(os.getenv("PORT", "5000"))
    print(f"监听: http://0.0.0.0:{port}")
    print(f"教师端: http://127.0.0.1:{port}/teacher")
    print(f"家长端: http://127.0.0.1:{port}/parent")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
