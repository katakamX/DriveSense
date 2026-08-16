import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def stub_mailgun(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Never hit the real Mailgun API from the test suite.

    Patches the name as imported into `app.core.otp`, not the definition
    site in `app.core.mailgun` - that's the reference `issue_otp` actually
    calls.
    """
    sent: list[tuple[str, str]] = []

    async def fake_send_otp_email(to_email: str, code: str) -> None:
        sent.append((to_email, code))

    monkeypatch.setattr("app.core.otp.send_otp_email", fake_send_otp_email)
    return sent


def test_register_issues_otp(client: TestClient, stub_mailgun: list[tuple[str, str]]) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "otp@example.com", "password": "correcthorse"}
    )
    assert response.status_code == 201
    assert len(stub_mailgun) == 1
    assert stub_mailgun[0][0] == "otp@example.com"
    assert len(stub_mailgun[0][1]) == 6


def test_verify_otp_with_correct_code_marks_verified(
    client: TestClient, stub_mailgun: list[tuple[str, str]]
) -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "verify@example.com", "password": "correcthorse"}
    )
    _, code = stub_mailgun[0]

    response = client.post(
        "/api/v1/auth/verify-otp", json={"email": "verify@example.com", "code": code}
    )
    assert response.status_code == 200, response.text
    assert response.json()["email_verified"] is True


def test_verify_otp_with_wrong_code_rejected(
    client: TestClient, stub_mailgun: list[tuple[str, str]]
) -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "badcode@example.com", "password": "correcthorse"}
    )

    response = client.post(
        "/api/v1/auth/verify-otp", json={"email": "badcode@example.com", "code": "000000"}
    )
    assert response.status_code == 400


def test_verify_otp_unknown_email_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/verify-otp", json={"email": "nobody@example.com", "code": "123456"}
    )
    assert response.status_code == 400


def test_resend_otp_invalidates_previous_code(
    client: TestClient, stub_mailgun: list[tuple[str, str]]
) -> None:
    client.post(
        "/api/v1/auth/register", json={"email": "resend@example.com", "password": "correcthorse"}
    )
    first_code = stub_mailgun[0][1]

    response = client.post("/api/v1/auth/resend-otp", json={"email": "resend@example.com"})
    assert response.status_code == 204
    assert len(stub_mailgun) == 2
    second_code = stub_mailgun[1][1]

    stale = client.post(
        "/api/v1/auth/verify-otp", json={"email": "resend@example.com", "code": first_code}
    )
    assert stale.status_code == 400

    fresh = client.post(
        "/api/v1/auth/verify-otp", json={"email": "resend@example.com", "code": second_code}
    )
    assert fresh.status_code == 200


def test_resend_otp_unknown_email_returns_204_without_leaking(client: TestClient) -> None:
    response = client.post("/api/v1/auth/resend-otp", json={"email": "nobody@example.com"})
    assert response.status_code == 204
