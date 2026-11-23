"""Deterministic step renderer. The exact text a user sees for a step."""


def step_markdown(step):
    lines = [
        f"**Шаг {step['num']}/{step['total']} · Модуль {step['module']}: {step['module_title']}**",
        "",
        f"**Что делать:** {step['action']}",
    ]
    if step.get("gui"):
        lines += ["", f"**Куда нажать:** {step['gui']}"]
    if step.get("command"):
        lines += ["", "```bash", step["command"], "```"]
    if step.get("check"):
        lines += ["", f"**Готово, если:** {step['check']}"]
    if step.get("pitfalls"):
        lines += ["", "**Важно:** " + "; ".join(step["pitfalls"])]
    return "\n".join(lines)


def step_brief(step):
    """One-line context handed to the LLM."""
    parts = [f"Шаг {step['num']}/{step['total']} (id {step['id']}), модуль {step['module']}: {step['module_title']}"]
    parts.append(f"Действие: {step['action']}")
    if step.get("command"):
        parts.append(f"Команда: {step['command']}")
    if step.get("gui"):
        parts.append(f"GUI: {step['gui']}")
    if step.get("check"):
        parts.append(f"Критерий: {step['check']}")
    return "\n".join(parts)
