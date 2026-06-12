"""Route-level Direction B flow: binary keypoint frames over the real
WebSocket -> segmentation -> recognition (mock engine) -> sign_text messages
with the confidence/message_id contract -> TTS to the speaker.

This is the flagship sign-to-speech path exercised through the actual
/ws/{meeting_id} route (auth handshake, binary dispatch, persistence to the
test database), complementing the handler-level tests in
test_sign_keypoint_handler.py. The browser side of the contract (zod schemas
accepting optional confidence/message_id) is tested in the frontend suite.
"""

import uuid

import numpy as np
from fastapi.testclient import TestClient

from app.models import User
from app.ws.keypoint_frame import NUM_KEYPOINTS, pack_keypoint_frame
from tests.ws.conftest import make_token


def _signing_clip(t: int) -> bytes:
    """T frames that pass the rest-pose filter and the recognition gates:
    wrists above the hip line, all-keypoint confidence 0.9."""
    rng = np.random.default_rng(7)
    kp = rng.uniform(0.2, 0.8, (t, NUM_KEYPOINTS, 2)).astype(np.float32)
    sc = np.full((t, NUM_KEYPOINTS), 0.9, dtype=np.float32)
    kp[:, 9, 1] = 0.1   # left wrist top
    kp[:, 10, 1] = 0.1  # right wrist top
    kp[:, 11, 1] = 0.9  # left hip bottom
    kp[:, 12, 1] = 0.9  # right hip bottom
    return pack_keypoint_frame(kp, sc, 640, 480)


def test_keypoint_stream_to_recognized_sentence_and_tts(
    ws_client: TestClient,
    meeting_id: uuid.UUID,
    speaker_user: User,
    reader_user: User,
) -> None:
    mid = str(meeting_id)
    with ws_client.websocket_connect(f"/ws/{mid}") as ws_speaker:
        ws_speaker.send_json({"type": "auth", "token": make_token(speaker_user.id)})
        assert ws_speaker.receive_json()["type"] == "auth_ok"

        with ws_client.websocket_connect(f"/ws/{mid}") as ws_reader:
            ws_reader.send_json({"type": "auth", "token": make_token(reader_user.id)})
            assert ws_reader.receive_json()["type"] == "auth_ok"
            ws_reader.receive_json()  # user_joined (speaker)
            ws_speaker.receive_json()  # user_joined (reader)

            # One binary frame holding 24 signing frames (> MIN_FRAMES=18),
            # then the stop cue that flushes and finalizes the sentence.
            ws_reader.send_bytes(_signing_clip(24))
            ws_reader.send_json(
                {"type": "control", "action": "sign_segment_end"}
            )

            # Partial: the sentence building up, word recognized by the mock
            # engine, carrying the segment's hand-confidence as evidence.
            partial = ws_reader.receive_json()
            assert partial["type"] == "sign_text"
            assert partial["is_partial"] is True
            assert partial["content"] == "Mock: hello how are you"
            assert 0.8 <= partial["confidence"] <= 1.0

            # Final: gloss smoothed to English (mock), persisted, and the
            # message_id of the DB row attached for the flag-feedback action.
            final = ws_reader.receive_json()
            assert final["type"] == "sign_text"
            assert "is_partial" not in final
            assert final["content"] == "Mock: I want to bake a cake"
            assert 0.8 <= final["confidence"] <= 1.0
            uuid.UUID(final["message_id"])  # persisted row id, valid UUID

            # The speaker hears the sentence: TTS stream starts.
            assert ws_speaker.receive_json()["type"] == "tts_start"


def test_reader_text_override_reaches_speaker_with_tts(
    ws_client: TestClient,
    meeting_id: uuid.UUID,
    speaker_user: User,
    reader_user: User,
) -> None:
    """The human-in-the-loop path: a reader whose signs are gated can type;
    the text is forwarded to the speaker, echoed back, spoken, persisted."""
    mid = str(meeting_id)
    with ws_client.websocket_connect(f"/ws/{mid}") as ws_speaker:
        ws_speaker.send_json({"type": "auth", "token": make_token(speaker_user.id)})
        assert ws_speaker.receive_json()["type"] == "auth_ok"

        with ws_client.websocket_connect(f"/ws/{mid}") as ws_reader:
            ws_reader.send_json({"type": "auth", "token": make_token(reader_user.id)})
            assert ws_reader.receive_json()["type"] == "auth_ok"
            ws_reader.receive_json()  # user_joined (speaker)
            ws_speaker.receive_json()  # user_joined (reader)

            ws_reader.send_json(
                {"type": "text_message", "content": "I will type instead"}
            )

            speaker_msg = ws_speaker.receive_json()
            assert speaker_msg["type"] == "text_message"
            assert speaker_msg["content"] == "I will type instead"

            echo = ws_reader.receive_json()
            assert echo["type"] == "text_message"
            assert echo["content"] == "I will type instead"

            assert ws_speaker.receive_json()["type"] == "tts_start"
