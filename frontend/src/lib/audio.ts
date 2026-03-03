/**
 * Convert Float32 audio samples [-1.0, 1.0] to PCM16 little-endian bytes.
 * This is the format the backend expects over WebSocket binary frames.
 */
export function float32ToPcm16(float32: Float32Array): ArrayBuffer {
  const pcm16 = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32[i]))
    pcm16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff
  }
  return pcm16.buffer
}

/**
 * Create a playable blob URL from WAV bytes received from TTS.
 * The backend sends complete WAV files (with RIFF headers),
 * so we just wrap them in a Blob.
 */
export function createWavBlobUrl(wavBytes: ArrayBuffer): string {
  const blob = new Blob([wavBytes], { type: "audio/wav" })
  return URL.createObjectURL(blob)
}
