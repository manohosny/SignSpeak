"""Low-level audio format conversions for the ML pipeline.

Browser AudioWorklet sends PCM16 bytes over WebSocket.
NeMo STT expects float32 numpy arrays (16kHz mono).
Kokoro TTS outputs float32 arrays (24kHz mono).
Browser playback expects WAV-framed bytes.
"""

import io
import wave

import numpy as np


def pcm16_bytes_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """Convert raw PCM 16-bit signed little-endian bytes to float32 numpy array.

    Input:  bytes (PCM16 LE, mono, 16kHz)
    Output: np.ndarray float32, values in [-1.0, 1.0]
    """
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


def float32_to_pcm16_bytes(audio: np.ndarray) -> bytes:
    """Convert float32 numpy array back to PCM 16-bit bytes.

    Input:  np.ndarray float32, values in [-1.0, 1.0]
    Output: bytes (PCM16 LE)
    """
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767).astype(np.int16).tobytes()


def float32_to_wav_bytes(
    audio: np.ndarray,
    sample_rate: int = 24000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Convert float32 numpy array to complete WAV file bytes.

    The browser can play this natively via <audio> or Web Audio API.

    Input:  np.ndarray float32, values in [-1.0, 1.0]
    Output: bytes (complete WAV file)
    """
    audio = np.clip(audio, -1.0, 1.0)
    pcm_data = (audio * 32767).astype(np.int16).tobytes()

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)

    return buffer.getvalue()
