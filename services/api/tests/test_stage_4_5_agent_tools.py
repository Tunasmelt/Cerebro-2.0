"""Stage 4.5 (stretch) — kanban agent tool-calling. Exercises
run_agent_turn against a fake KanbanStorage and a monkeypatched
generate_module.run_interaction (no real network), proving: a message
with no card intent gets a plain text reply and creates nothing; a
message that triggers create_kanban_card actually creates a card via the
real, RLS-scoped KanbanStorage.create_card and reports it back; a
hallucinated board id fails closed instead of guessing; and a
GenerateError at either the first call or the function_result follow-up
never raises past this module.
"""
from typing import Any

import pytest

from app.chat import generate as generate_module
from app.chat.agent_tools import CREATE_CARD_TOOL, run_agent_turn
from app.chat.generate import GenerateError


class _FakeKanbanStorage:
    def __init__(self, *, boards: list[dict]):
        self.boards = boards
        self.created_cards: list[dict[str, Any]] = []

    async def list_boards(self, *, user_jwt, user_id):
        return self.boards

    async def create_card(
        self, *, user_jwt, user_id, board_id, column_name, title, description, document_id
    ):
        card = {
            "id": f"card-{len(self.created_cards) + 1}",
            "board_id": board_id,
            "column_name": column_name,
            "title": title,
            "description": description,
        }
        self.created_cards.append(card)
        return card

    async def create_board(self, *, user_jwt, user_id, title):
        raise NotImplementedError

    async def get_board_with_cards(self, *, user_jwt, board_id):
        raise NotImplementedError

    async def update_card(self, *, user_jwt, card_id, updates):
        raise NotImplementedError

    async def delete_card(self, *, user_jwt, card_id):
        raise NotImplementedError


def _text_only_interaction(text: str) -> dict:
    return {
        "id": "interaction-1",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}],
    }


def _function_call_interaction(*, board_id: str, title: str, column_name: str | None = None) -> dict:
    args: dict[str, Any] = {"board_id": board_id, "title": title}
    if column_name:
        args["column_name"] = column_name
    return {
        "id": "interaction-1",
        "steps": [
            {"type": "function_call", "name": CREATE_CARD_TOOL, "arguments": args, "id": "call-1"}
        ],
    }


@pytest.mark.asyncio
async def test_no_tool_call_returns_plain_text_and_creates_nothing(monkeypatch):
    async def fake_run_interaction(*, system_instruction, input_data, tools=None, previous_interaction_id=None):
        return _text_only_interaction("just a normal answer")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)
    storage = _FakeKanbanStorage(boards=[{"id": "b1", "title": "Board", "columns": ["Backlog"]}])

    result = await run_agent_turn(
        user_jwt="t", user_id="u1", message="what's on my board?", kanban_storage=storage
    )

    assert result.response == "just a normal answer"
    assert result.created_cards == []
    assert storage.created_cards == []


@pytest.mark.asyncio
async def test_tool_call_creates_real_card_and_confirms_in_follow_up(monkeypatch):
    calls = []

    async def fake_run_interaction(*, system_instruction, input_data, tools=None, previous_interaction_id=None):
        calls.append({"input_data": input_data, "previous_interaction_id": previous_interaction_id})
        if previous_interaction_id is None:
            return _function_call_interaction(board_id="b1", title="Buy milk")
        return _text_only_interaction('Created "Buy milk".')

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)
    storage = _FakeKanbanStorage(boards=[{"id": "b1", "title": "Board", "columns": ["Backlog", "Done"]}])

    result = await run_agent_turn(
        user_jwt="t", user_id="u1", message="add a card to buy milk", kanban_storage=storage
    )

    assert len(storage.created_cards) == 1
    assert storage.created_cards[0]["title"] == "Buy milk"
    assert storage.created_cards[0]["column_name"] == "Backlog"
    assert result.created_cards == storage.created_cards
    assert result.response == 'Created "Buy milk".'
    # Follow-up call carried the function_result, not the raw message again.
    assert calls[1]["input_data"][0]["type"] == "function_result"
    assert calls[1]["input_data"][0]["call_id"] == "call-1"
    assert calls[1]["previous_interaction_id"] == "interaction-1"


@pytest.mark.asyncio
async def test_hallucinated_board_id_fails_closed(monkeypatch):
    async def fake_run_interaction(*, system_instruction, input_data, tools=None, previous_interaction_id=None):
        return _function_call_interaction(board_id="does-not-exist", title="Buy milk")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)
    storage = _FakeKanbanStorage(boards=[{"id": "b1", "title": "Board", "columns": ["Backlog"]}])

    result = await run_agent_turn(
        user_jwt="t", user_id="u1", message="add a card", kanban_storage=storage
    )

    assert storage.created_cards == []
    assert "couldn't find that board" in result.response


@pytest.mark.asyncio
async def test_generate_error_on_first_call_does_not_raise(monkeypatch):
    async def fake_run_interaction(*, system_instruction, input_data, tools=None, previous_interaction_id=None):
        raise GenerateError("generate_call_failed", "upstream boom")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)
    storage = _FakeKanbanStorage(boards=[])

    result = await run_agent_turn(
        user_jwt="t", user_id="u1", message="add a card", kanban_storage=storage
    )

    assert "upstream boom" in result.response
    assert result.created_cards == []


@pytest.mark.asyncio
async def test_generate_error_on_follow_up_still_reports_created_card(monkeypatch):
    async def fake_run_interaction(*, system_instruction, input_data, tools=None, previous_interaction_id=None):
        if previous_interaction_id is None:
            return _function_call_interaction(board_id="b1", title="Buy milk")
        raise GenerateError("generate_call_failed", "upstream boom")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)
    storage = _FakeKanbanStorage(boards=[{"id": "b1", "title": "Board", "columns": ["Backlog"]}])

    result = await run_agent_turn(
        user_jwt="t", user_id="u1", message="add a card", kanban_storage=storage
    )

    assert len(storage.created_cards) == 1
    assert result.created_cards == storage.created_cards
    assert "upstream boom" in result.response


@pytest.mark.asyncio
async def test_omitted_column_name_defaults_to_boards_first_column(monkeypatch):
    async def fake_run_interaction(*, system_instruction, input_data, tools=None, previous_interaction_id=None):
        if previous_interaction_id is None:
            return _function_call_interaction(board_id="b1", title="Buy milk")
        return _text_only_interaction("done")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)
    storage = _FakeKanbanStorage(
        boards=[{"id": "b1", "title": "Board", "columns": ["Todo", "Doing", "Done"]}]
    )

    await run_agent_turn(user_jwt="t", user_id="u1", message="add a card", kanban_storage=storage)

    assert storage.created_cards[0]["column_name"] == "Todo"
