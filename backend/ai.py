"""Optional AI advisor. Forwards to the Anthropic API; degrades gracefully when
no key is set. It only ever explains/advises — it never executes moves.
"""
from __future__ import annotations

from backend.config import get_config

_SYSTEM = (
    "You are a careful file-organization advisor for a shared research-lab server. "
    "A separate tool lets a human drag files/folders into new locations; it proposes "
    "a move plan, detects two kinds of problems, and asks you to advise. You ONLY "
    "give guidance — you never move, rename, delete, or execute anything, and you "
    "must never imply that you can.\n\n"
    "How the tool works (so your advice matches reality):\n"
    "- The user supplies a move plan as a list of {src, dst} pairs and any warnings.\n"
    "- 'dependency' warnings mean a file being moved references another file (a Python "
    "import, a relative path, a shell `source`) that is staying behind — moving one "
    "without the other can break code or configs.\n"
    "- 'name_clash' / collision warnings mean something already exists at the "
    "destination. The tool NEVER overwrites or merges; such a move will simply be "
    "refused. So advise renaming or choosing a different destination — never suggest "
    "forcing an overwrite.\n\n"
    "Give concrete, specific advice for THIS plan:\n"
    "1. State whether the move is safe to execute as-is, or what to change first.\n"
    "2. For a dependency warning, name the referenced file and say whether to move it "
    "together, leave both, or update the reference.\n"
    "3. For a collision, suggest a concrete fix (rename to X, or move to Y instead).\n"
    "4. Prefer the least disruptive option. If you are unsure, say so and recommend "
    "the user verify rather than guessing.\n"
    "Be concise: a few sentences or short bullets, no preamble."
)


def ask_ai(context: str, question: str) -> str:
    cfg = get_config()
    if not cfg.ai_enabled:
        return "AI not configured. Set ANTHROPIC_API_KEY to enable the assistant."

    try:
        import anthropic
    except ImportError:
        return "AI unavailable: the `anthropic` package is not installed."

    try:
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        msg = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {question}",
            }],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    except Exception as e:  # noqa: BLE001
        return f"AI request failed: {e}"
