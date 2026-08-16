"""Google OAuth login (M-Auth-2). Never calls Google - `oauth.google`'s
Authlib methods are monkeypatched so tests exercise only our endpoints."""

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
