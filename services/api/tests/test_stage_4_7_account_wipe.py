"""Stage 4.7 — account data wipe (DELETE /api/v1/account).

Exit criteria (from the settings page's delete-account flow): every
document/board/card/todo/chat-session row the caller owns is gone
afterward, the account can still sign in (this route never touches
auth.users), and calling it again on an already-empty account doesn't
error.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import account_storage as storage_module
from app.core import auth as auth_module
from app.main import app

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_SUB = "11111111-1111-1111-1111-111111111111"


class _StubJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._key)


class _FakeAccountStorage:
    def __init__(self):
        self.result_to_return = {"documents_deleted": 0}
        self.wipe_calls: list[str] = []

    async def wipe_account_data(self, *, user_jwt, user_id):
        self.wipe_calls.append(user_id)
        return self.result_to_return


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    yield
    auth_module.set_jwks_client(None)
    storage_module.set_account_storage(storage_module.AccountStorage())


@pytest.fixture
def client():
    return TestClient(app)


def auth_headers(private_key, sub=TEST_SUB):
    payload = {
        "iss": TEST_ISSUER,
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    return {"Authorization": f"Bearer {token}"}


def test_wipe_account_deletes_data_and_returns_summary(client, keypair):
    private_key, _ = keypair
    fake = _FakeAccountStorage()
    fake.result_to_return = {"documents_deleted": 3}
    storage_module.set_account_storage(fake)

    response = client.delete("/api/v1/account", headers=auth_headers(private_key))

    assert response.status_code == 200
    assert response.json() == {"documents_deleted": 3}
    assert fake.wipe_calls == [TEST_SUB]


def test_wipe_account_on_already_empty_account_is_not_an_error(client, keypair):
    private_key, _ = keypair
    fake = _FakeAccountStorage()
    fake.result_to_return = {"documents_deleted": 0}
    storage_module.set_account_storage(fake)

    response = client.delete("/api/v1/account", headers=auth_headers(private_key))

    assert response.status_code == 200
    assert response.json() == {"documents_deleted": 0}


def test_wipe_account_requires_auth(client):
    storage_module.set_account_storage(_FakeAccountStorage())
    assert client.delete("/api/v1/account").status_code == 401
