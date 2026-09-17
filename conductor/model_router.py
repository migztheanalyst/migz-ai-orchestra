import sys

MODEL_ROUTES = {
    "fast": "qwen2.5-coder:3b",
    "triage": "qwen2.5-coder:3b",
    "coding": "qwen2.5-coder:7b",
    "review": "qwen2.5-coder:7b",
    "reasoning": "qwen3.5:4b",
    "general": "qwen3.5:4b",
}

FALLBACK_ROUTES = {
    "reasoning": "qwen2.5-coder:7b",
    "general": "qwen2.5-coder:7b",
}

ROLE_CANDIDATES = {
    "fast": ["qwen2.5-coder:3b"],
    "triage": ["qwen2.5-coder:3b"],
    "coding": ["qwen2.5-coder:7b", "qwen2.5-coder:3b"],
    "review": ["qwen2.5-coder:7b", "qwen2.5-coder:3b"],
    "reasoning": ["qwen3.5:4b", "qwen2.5-coder:7b", "qwen2.5-coder:3b"],
    "general": ["qwen3.5:4b", "qwen2.5-coder:7b", "qwen2.5-coder:3b"],
    "advisory": ["qwen3.5:4b", "qwen2.5-coder:7b", "qwen2.5-coder:3b"],
}


def model_candidates(role: str):
    role = role.strip().lower()
    if role not in ROLE_CANDIDATES:
        valid = ", ".join(sorted(ROLE_CANDIDATES))
        raise ValueError(f"Unknown role '{role}'. Valid roles: {valid}")
    return list(ROLE_CANDIDATES[role])


def route_model(role: str, available_models=None) -> str:
    role = role.strip().lower()

    if role not in MODEL_ROUTES:
        valid = ", ".join(sorted(MODEL_ROUTES))
        raise ValueError(
            f"Unknown role '{role}'. Valid roles: {valid}"
        )

    selected = MODEL_ROUTES[role]
    if available_models is not None and selected not in set(available_models):
        fallback = FALLBACK_ROUTES.get(role, "qwen2.5-coder:3b")
        if fallback not in set(available_models):
            raise RuntimeError(f"No healthy local model for role: {role}")
        return fallback
    return selected


def route_healthy_model(role: str, installed_models, healthy_models=None, latency_seconds=None, max_latency_seconds=None) -> str:
    """Select the first installed and live-healthy model for a role.

    ``route_model`` remains V1-compatible and installation-aware.  New runtime
    callers should use this function after provider preflight so an installed
    but unhealthy model is never silently treated as healthy.
    """
    candidates = model_candidates(role)
    installed = set(installed_models or ())
    healthy = set(healthy_models if healthy_models is not None else installed)
    for model in candidates:
        if model not in installed or model not in healthy:
            continue
        if max_latency_seconds is not None and latency_seconds and latency_seconds > max_latency_seconds:
            continue
        return model
    raise RuntimeError(f"No healthy model for role: {role}")

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 conductor/model_router.py <role>")
        raise SystemExit(1)

    role = sys.argv[1]

    try:
        model = route_model(role)
    except ValueError as exc:
        print(f"ROUTER: FAIL")
        print(exc)
        raise SystemExit(1)

    print(f"ROLE  : {role}")
    print(f"MODEL : {model}")
    print("ROUTER: PASS")

if __name__ == "__main__":
    main()
