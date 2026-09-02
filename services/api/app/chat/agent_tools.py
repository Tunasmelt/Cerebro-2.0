"""Stage 4.5 — kanban agent tool-calling (stretch, not gated).

A chat turn that can act, not just answer: the model is given one real
tool, `create_kanban_card`, and a listing of the caller's own boards; if
it decides the message calls for a card, it emits a function_call step,
this module executes it for real through the existing, RLS-scoped
`KanbanStorage.create_card` (Stage 4.2 — same ownership enforcement
every other kanban mutation already relies on, not a new bypass path),
and the result is sent back to the model for a final text reply. This is
a deliberately separate, non-streaming entry point
(`chat/generate.py`'s `run_interaction`) — not a variant of
`chat/stream.py`'s normal path — same reasoning Stage 5.6's playground
run already used: a tool-calling turn is a different, larger surface to
secure than the fixed retrieve-then-answer shape of a normal chat turn.

Scoped to exactly one tool and one round trip (at most one function_call
is executed) — a stretch feature, not the start of an open-ended agent
loop. A message that doesn't call for a card just gets a normal text
reply with no tool call at all.
"""
from dataclasses import dataclass, field
from typing import Any

from app.chat import generate as generate_module
from app.chat.generate import GenerateError
from app.core.kanban_storage import KanbanStorage, get_kanban_storage

CREATE_CARD_TOOL = "create_kanban_card"

TOOLS: list[dict] = [
    {
        "type": "function",
        "name": CREATE_CARD_TOOL,
        "description": (
            "Create a card on one of the user's own kanban boards. Only call "
            "this when the user is clearly asking for a task/card to be "
            "added, not for a general question."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "board_id": {
                    "type": "string",
                    "description": "The id of the board to add the card to, from the boards listed above.",
                },
                "column_name": {
                    "type": "string",
                    "description": "Which column to add the card to. Defaults to the board's first column if omitted.",
                },
                "title": {"type": "string", "description": "Short card title."},
                "description": {
                    "type": "string",
                    "description": "Card description. Empty string if nothing more to say.",
                },
            },
            "required": ["board_id", "title"],
        },
    }
]

AGENT_SYSTEM_HEADER = (
    "You are Cerebro's kanban assistant. You may call create_kanban_card "
    "when the user is clearly asking for a task or card to be added — "
    "never for a general question, and never more than one card per "
    "message. If no card is warranted, just reply normally in text."
)


@dataclass
class AgentTurnResult:
    response: str
    created_cards: list[dict[str, Any]] = field(default_factory=list)


def _extract_text(interaction: dict) -> str:
    parts = []
    for step in interaction.get("steps", []):
        if step.get("type") == "model_output":
            for block in step.get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    parts.append(block["text"])
    return "".join(parts)


def _find_function_call(interaction: dict) -> dict | None:
    for step in interaction.get("steps", []):
        if step.get("type") == "function_call":
            return step
    return None


async def run_agent_turn(
    *, user_jwt: str, user_id: str, message: str, kanban_storage: KanbanStorage | None = None
) -> AgentTurnResult:
    storage = kanban_storage or get_kanban_storage()
    boards = await storage.list_boards(user_jwt=user_jwt, user_id=user_id)
    boards_listing = "\n".join(
        f"- id={b['id']} title={b['title']!r} columns={b['columns']}" for b in boards
    ) or "(the user has no boards yet)"
    system_instruction = f"{AGENT_SYSTEM_HEADER}\n\nThe user's boards:\n{boards_listing}"

    try:
        interaction = await generate_module.run_interaction(
            system_instruction=system_instruction, input_data=message, tools=TOOLS
        )
    except GenerateError as exc:
        return AgentTurnResult(response=f"(agent error: {exc.message})")

    call = _find_function_call(interaction)
    if call is None or call.get("name") != CREATE_CARD_TOOL:
        return AgentTurnResult(response=_extract_text(interaction))

    args = call.get("arguments", {})
    board = next((b for b in boards if b["id"] == args.get("board_id")), None)
    if board is None:
        # Model hallucinated or misquoted a board id — fail closed rather
        # than guessing which board the user meant.
        return AgentTurnResult(
            response="I couldn't find that board, so I didn't create a card."
        )
    column_name = args.get("column_name") or board["columns"][0]

    created_card = await storage.create_card(
        user_jwt=user_jwt,
        user_id=user_id,
        board_id=board["id"],
        column_name=column_name,
        title=args.get("title", ""),
        description=args.get("description", ""),
        document_id=None,
    )
    if created_card is None:
        return AgentTurnResult(response="I couldn't create that card.")

    function_result = {
        "type": "function_result",
        "name": CREATE_CARD_TOOL,
        "call_id": call.get("id"),
        "result": [{"type": "text", "text": f"Created card {created_card['id']!r}."}],
    }
    try:
        follow_up = await generate_module.run_interaction(
            system_instruction=system_instruction,
            input_data=[function_result],
            tools=TOOLS,
            previous_interaction_id=interaction.get("id"),
        )
    except GenerateError as exc:
        return AgentTurnResult(
            response=f"Created the card, but couldn't confirm it in text: {exc.message}",
            created_cards=[created_card],
        )

    return AgentTurnResult(
        response=_extract_text(follow_up) or f"Created \"{created_card['title']}\".",
        created_cards=[created_card],
    )
