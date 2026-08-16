"""Authlib OAuth client registration for Google sign-in (M-Auth-2).

Authlib owns the authorization-code exchange and the CSRF `state` check
(`app.api.v1.auth` never touches either directly) - a hand-rolled version of
either is exactly the kind of thing that's easy to get subtly wrong.
"""

from authlib.integrations.starlette_client import OAuth

from app.config import get_settings

settings = get_settings()

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
