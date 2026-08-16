from fastapi.testclient import TestClient


def test_register_creates_user_and_sets_cookie(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "ada@example.com", "password": "longenoughpw"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert body["email_verified"] is False
    assert "ds_session" in response.cookies


def test_register_duplicate_email_conflicts(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "dup@example.com", "password": "pw12345678"}
    )

    response = client.post(
        "/api/v1/auth/register", json={"email": "dup@example.com", "password": "otherpassword"}
    )
    assert response.status_code == 409


def test_login_with_correct_password_succeeds(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "login@example.com", "password": "correcthorse"}
    )

    response = client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": "correcthorse"}
    )
    assert response.status_code == 200, response.text
    assert "ds_session" in response.cookies


def test_login_with_wrong_password_rejected(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "wrong@example.com", "password": "correcthorse"}
    )

    response = client.post(
        "/api/v1/auth/login", json={"email": "wrong@example.com", "password": "wrongpassword"}
    )
    assert response.status_code == 401


def test_login_unknown_email_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )
    assert response.status_code == 401


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user_after_login(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "me@example.com", "password": "correcthorse"}
    )

    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


def test_logout_clears_session(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "logout@example.com", "password": "correcthorse"}
    )
    assert client.get("/api/v1/auth/me").status_code == 200

    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204

    assert client.get("/api/v1/auth/me").status_code == 401
