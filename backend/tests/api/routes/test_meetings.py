"""REST API tests for the /meetings endpoints.

Covers the full meeting lifecycle over HTTP (create -> get by code -> join ->
messages -> flag -> end) plus the documented failure paths: invalid code 404,
full meeting 400, non-participant 403, unknown message 404. The realtime
in-meeting behavior is covered separately in tests/ws/.
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import MeetingMessage, MessageType
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import random_email

API = f"{settings.API_V1_STR}/meetings"


def _create_meeting(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    r = client.post(f"{API}/", headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"]
    assert body["status"] == "waiting"
    return body


class TestMeetingLifecycle:
    def test_create_and_get_by_code(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        r = client.get(f"{API}/{meeting['code']}", headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["id"] == meeting["id"]

    def test_get_invalid_code_404(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        r = client.get(f"{API}/XXX-0000", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_join_activates_meeting(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        normal_user_token_headers: dict[str, str],
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        r = client.post(
            f"{API}/{meeting['code']}/join", headers=normal_user_token_headers
        )
        assert r.status_code == 201
        assert r.json()["status"] == "active"

    def test_join_invalid_code_404(
        self, client: TestClient, normal_user_token_headers: dict[str, str]
    ) -> None:
        r = client.post(f"{API}/XXX-0000/join", headers=normal_user_token_headers)
        assert r.status_code == 404

    def test_join_full_meeting_400(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        r = client.post(
            f"{API}/{meeting['code']}/join", headers=normal_user_token_headers
        )
        assert r.status_code == 201
        third_headers = authentication_token_from_email(
            client=client, email=random_email(), db=db
        )
        r = client.post(f"{API}/{meeting['code']}/join", headers=third_headers)
        assert r.status_code == 400

    def test_end_meeting_by_host(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        r = client.post(
            f"{API}/{meeting['id']}/end", headers=superuser_token_headers
        )
        assert r.status_code == 200

    def test_end_meeting_by_outsider_403(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        outsider = authentication_token_from_email(
            client=client, email=random_email(), db=db
        )
        r = client.post(f"{API}/{meeting['id']}/end", headers=outsider)
        assert r.status_code == 403

    def test_meeting_history_lists_created_meeting(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        r = client.get(f"{API}/", headers=superuser_token_headers)
        assert r.status_code == 200
        assert meeting["id"] in [m["id"] for m in r.json()["data"]]


def _persist_message(
    db: Session, meeting_id: str, sender_id: str, content: str
) -> MeetingMessage:
    msg = MeetingMessage(
        meeting_id=uuid.UUID(meeting_id),
        sender_id=uuid.UUID(sender_id),
        content=content,
        msg_type=MessageType.sign_translation,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


class TestMessagesAndFlagging:
    def test_messages_listing_requires_participant(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        outsider = authentication_token_from_email(
            client=client, email=random_email(), db=db
        )
        r = client.get(f"{API}/{meeting['id']}/messages", headers=outsider)
        assert r.status_code == 403

    def test_messages_listing_returns_persisted_message(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        msg = _persist_message(
            db, meeting["id"], meeting["host_id"], "hello world"
        )
        r = client.get(
            f"{API}/{meeting['id']}/messages", headers=superuser_token_headers
        )
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()["data"]]
        assert str(msg.id) in ids

    def test_flag_message_sets_flagged_at(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        msg = _persist_message(
            db, meeting["id"], meeting["host_id"], "wrong translation"
        )
        r = client.post(
            f"{API}/{meeting['id']}/messages/{msg.id}/flag",
            headers=superuser_token_headers,
            json={"reason": "should say hello"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["flagged_at"] is not None

    def test_flag_by_non_participant_403(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        msg = _persist_message(db, meeting["id"], meeting["host_id"], "x")
        outsider = authentication_token_from_email(
            client=client, email=random_email(), db=db
        )
        r = client.post(
            f"{API}/{meeting['id']}/messages/{msg.id}/flag",
            headers=outsider,
            json={},
        )
        assert r.status_code == 403

    def test_flag_unknown_message_404(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
    ) -> None:
        meeting = _create_meeting(client, superuser_token_headers)
        r = client.post(
            f"{API}/{meeting['id']}/messages/{uuid.uuid4()}/flag",
            headers=superuser_token_headers,
            json={},
        )
        assert r.status_code == 404
