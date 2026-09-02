"""Stage 4.7 — storage-level test for the real AccountStorage.
wipe_account_data, confirming it actually calls the real per-document
delete (reusing Stage 3.6's tested logic, not a second untested path)
and bulk-deletes boards/todos/chat_sessions.
"""
import httpx
import pytest

from app.core import documents_storage as documents_storage_module
from app.core.account_storage import AccountStorage


class _FakeDocumentsStorage:
    def __init__(self, documents):
        self._documents = documents
        self.delete_calls: list[str] = []

    async def list_documents(self, *, user_jwt, user_id):
        return self._documents

    async def delete_document(self, *, user_jwt, document_id):
        self.delete_calls.append(document_id)
        return True


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.delete_calls: list[tuple[str, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        if request.method == "DELETE" and path.startswith("/rest/v1/"):
            table = path.removeprefix("/rest/v1/")
            self.delete_calls.append((table, params.get("user_id", "")))
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected {request.method} {path}")


def _patch_client(monkeypatch, transport: _FakeTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


@pytest.fixture(autouse=True)
def _reset_documents_storage():
    yield
    documents_storage_module.set_documents_storage(
        documents_storage_module.SupabaseDocumentsStorage()
    )


@pytest.mark.asyncio
async def test_wipe_deletes_every_document_then_bulk_deletes_the_rest(monkeypatch):
    fake_docs = _FakeDocumentsStorage([{"id": "doc-1"}, {"id": "doc-2"}])
    documents_storage_module.set_documents_storage(fake_docs)
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)

    storage = AccountStorage()
    result = await storage.wipe_account_data(user_jwt="t", user_id="u1")

    assert result == {"documents_deleted": 2}
    assert fake_docs.delete_calls == ["doc-1", "doc-2"]
    assert ("boards", "eq.u1") in transport.delete_calls
    assert ("todos", "eq.u1") in transport.delete_calls
    assert ("chat_sessions", "eq.u1") in transport.delete_calls
    assert ("clusters", "eq.u1") in transport.delete_calls


@pytest.mark.asyncio
async def test_wipe_on_an_already_empty_account_deletes_nothing_and_does_not_error(monkeypatch):
    fake_docs = _FakeDocumentsStorage([])
    documents_storage_module.set_documents_storage(fake_docs)
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)

    storage = AccountStorage()
    result = await storage.wipe_account_data(user_jwt="t", user_id="u1")

    assert result == {"documents_deleted": 0}
    assert fake_docs.delete_calls == []
    # The four bulk deletes still run (harmless no-ops against an
    # already-empty account) rather than being skipped conditionally.
    assert len(transport.delete_calls) == 4
