"""Google OAuth login (M-Auth-2). Never calls Google - `oauth.google`'s
Authlib methods are monkeypatched so tests exercise only our endpoints."""

from authlib.integrations.base_client.errors import MismatchingStateError, OAuthError
from starlette.responses import RedirectResponse

from app.api.v1.auth import oauth


def test_google_login_redirects_to_google(client, monkeypatch) -> None:
    async def fake_authorize_redirect(request, redirect_uri):
        assert redirect_uri == "http://localhost:8000/api/v1/auth/google/callback"
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?state=fake")

    monkeypatch.setattr(oauth.google, "authorize_redirect", fake_authorize_redirect)

    response = client.get("/api/v1/auth/google/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"].startswith("https://accounts.google.com/")


def _fake_token(email: str = "newgoogleuser@example.com", name: str = "Ada Lovelace") -> dict:
    return {
        "access_token": "fake-access-token",
        "userinfo": {"email": email, "name": name, "email_verified": True},
    }


def test_callback_creates_user_and_sets_session_cookie(client, monkeypatch) -> None:
    async def fake_authorize_access_token(request):
        return _fake_token("newgoogleuser@example.com")

    monkeypatch.setattr(oauth.google, "authorize_access_token", fake_authorize_access_token)

    response = client.get("/api/v1/auth/google/callback", follow_redirects=False)
    assert response.status_code in (302, 307), response.text
    assert "ds_session" in response.cookies

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "newgoogleuser@example.com"
    assert body["role"] == "user"
    assert body["email_verified"] is True


def test_callback_finds_existing_user_by_email(client, monkeypatch) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "existing@example.com", "password": "correcthorsebattery"},
    )

    async def fake_authorize_access_token(request):
        return _fake_token("existing@example.com")

    monkeypatch.setattr(oauth.google, "authorize_access_token", fake_authorize_access_token)

    response = client.get("/api/v1/auth/google/callback", follow_redirects=False)
    assert response.status_code in (302, 307)

    me = client.get("/api/v1/auth/me")
    assert me.json()["email"] == "existing@example.com"


def test_callback_consent_denied_fails_cleanly(client, monkeypatch) -> None:
    async def fake_authorize_access_token(request):
        raise OAuthError(error="access_denied", description="The user denied consent")

    monkeypatch.setattr(oauth.google, "authorize_access_token", fake_authorize_access_token)

    response = client.get("/api/v1/auth/google/callback")
    assert response.status_code == 400
    assert "ds_session" not in response.cookies


def test_callback_invalid_state_fails_cleanly(client, monkeypatch) -> None:
    async def fake_authorize_access_token(request):
        raise MismatchingStateError()

    monkeypatch.setattr(oauth.google, "authorize_access_token", fake_authorize_access_token)

    response = client.get("/api/v1/auth/google/callback")
    assert response.status_code == 400


def test_callback_google_api_error_fails_cleanly(client, monkeypatch) -> None:
    async def fake_authorize_access_token(request):
        raise OAuthError(error="server_error", description="Google's token endpoint errored")

    monkeypatch.setattr(oauth.google, "authorize_access_token", fake_authorize_access_token)

    response = client.get("/api/v1/auth/google/callback")
    assert response.status_code == 400
