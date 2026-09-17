from war_room_personas import EVENT_AGENT, persona

MODES = {"quiet", "normal", "warroom"}

QUIET_TYPES = {
    "mission.started", "task.blocked", "task.passed", "mission.complete",
}
NORMAL_TYPES = QUIET_TYPES | {
    "task.started", "builder.complete", "tester.pass", "tester.fail",
    "reviewer.pass", "reviewer.fail", "task.retry",
}

TEMPLATES = {
    "mission.started": "بدأت المهمة. هوزع التنفيذ وأبلغك بأي blocker مهم.",
    "task.started": "مسكت المهمة وبدأت التنفيذ المعزول.",
    "builder.started": "داخلة على التنفيذ دلوقتي.",
    "builder.complete": "خلصت التنفيذ الأولي ورميته للاختبارات.",
    "tester.pass": "الاختبارات الأساسية عدّت ✅",
    "tester.fail": "في اختبار وقع ❌ ومش هعدّيه قبل الإصلاح.",
    "reviewer.pass": "المراجعة المستقلة PASS ✅",
    "reviewer.fail": "المراجعة رفضت النسخة الحالية. محتاجة تعديل.",
    "task.retry": "هنعيد المحاولة بناءً على الفشل الفعلي، مش بشكل عشوائي.",
    "task.blocked": "المهمة BLOCKED واحتاجت تصعيد بدل التخمين.",
    "task.passed": "✅ المهمة اتقفلت باختبارات ومراجعة موثقة.",
    "mission.complete": "🎯 المهمة الكاملة انتهت.",
}


class ConversationDirector:
    def __init__(self, mode="normal"):
        self.set_mode(mode)

    def set_mode(self, mode):
        mode = str(mode).lower().strip()
        if mode not in MODES:
            raise ValueError("Mode must be quiet, normal, or warroom")
        self.mode = mode
        return mode

    def should_surface(self, event):
        if event.get("visibility") == "quiet":
            return True
        if self.mode == "quiet":
            return event.get("type") in QUIET_TYPES
        if self.mode == "normal":
            return event.get("type") in NORMAL_TYPES
        return True

    def render(self, event):
        if not self.should_surface(event):
            return None
        agent_key = event.get("agent") or EVENT_AGENT.get(event.get("type"), "sol")
        p = persona(agent_key)
        body = event.get("summary") or TEMPLATES.get(event.get("type"), event.get("type", "Update"))
        reaction = None
        if self.mode == "warroom" and event.get("type") in {"tester.fail", "reviewer.fail"}:
            reaction = "👀"
        return {
            "agent": agent_key,
            "display": p["display"],
            "role": p["role"],
            "text": body,
            "reaction": reaction,
            "reply_to": event.get("reply_to"),
            "typing_ms": 700 if self.mode == "warroom" else 0,
            "task_id": event.get("task_id"),
            "event_id": event.get("id"),
        }
