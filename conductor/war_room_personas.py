PERSONAS = {
    "sol": {
        "display": "🎼 Sol",
        "role": "Maestro",
        "tone": "calm, decisive, concise",
    },
    "luna": {
        "display": "🔨 Luna",
        "role": "Builder",
        "tone": "practical, energetic, implementation-focused",
    },
    "terra": {
        "display": "🛡 Terra",
        "role": "QA Reviewer",
        "tone": "skeptical, evidence-first, concise",
    },
    "astra": {
        "display": "🔭 Astra",
        "role": "Researcher",
        "tone": "analytical, curious, source-aware",
    },
}

EVENT_AGENT = {
    "mission.started": "sol",
    "task.started": "sol",
    "builder.started": "luna",
    "builder.complete": "luna",
    "tester.pass": "terra",
    "tester.fail": "terra",
    "reviewer.pass": "terra",
    "reviewer.fail": "terra",
    "task.retry": "sol",
    "task.blocked": "sol",
    "task.passed": "sol",
    "mission.complete": "sol",
}


def persona(name):
    key = str(name or "sol").lower()
    if key not in PERSONAS:
        raise ValueError(f"Unknown persona: {name}")
    return PERSONAS[key]
