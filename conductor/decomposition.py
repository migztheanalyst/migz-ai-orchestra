DEFAULT_MAX_CHARS = 1200
DEFAULT_MAX_PARTS = 64


def split_objective(objective, max_chars=DEFAULT_MAX_CHARS, max_parts=DEFAULT_MAX_PARTS):
    """Split a large objective without losing text or creating an unbounded child."""
    text = " ".join(str(objective).split()).strip()
    if not text:
        raise ValueError("objective required")
    if not isinstance(max_chars, int) or max_chars < 64:
        raise ValueError("max_chars must be an integer >= 64")
    if not isinstance(max_parts, int) or max_parts < 1:
        raise ValueError("max_parts must be a positive integer")

    parts = []
    remaining = text
    while remaining:
        if len(parts) >= max_parts:
            raise ValueError("objective exceeds bounded decomposition limit")
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
        cut = remaining.rfind(". ", 0, max_chars + 1)
        if cut < max_chars // 3:
            cut = remaining.rfind("; ", 0, max_chars + 1)
        if cut < max_chars // 3:
            cut = remaining.rfind(" ", 0, max_chars + 1)
        if cut <= 0:
            cut = max_chars
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip(" .;")
    return parts


def should_decompose(error_text):
    text = str(error_text).lower()
    markers = (
        "output truncated", "done_reason", "context length", "context window",
        "too many file writes", "request too large", "token limit",
        "maximum context", "max context", "prompt is too long",
    )
    return any(marker in text for marker in markers)


def bounded_subtasks(title, objective, role="coding", parent_task_id=None, reason="oversized objective"):
    parts = split_objective(objective)
    return [
        {
            "title": f"{title} [{i}/{len(parts)}]",
            "objective": part,
            "role": role,
            "parent_task_id": parent_task_id,
            "parent_objective": str(objective).strip(),
            "decomposition_index": i,
            "decomposition_total": len(parts),
            "decomposition_reason": reason,
        }
        for i, part in enumerate(parts, 1)
    ]
