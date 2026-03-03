/**
 * AudioWorklet processor for capturing mic input as PCM16 chunks.
 *
 * Runs in a separate thread (AudioWorkletGlobalScope).
 * Buffers Float32 samples and posts them to the main thread
 * when the buffer reaches ~250ms of audio at 16kHz (4000 samples).
 */
class PcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this._buffer = new Float32Array(4000)
    this._offset = 0
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || input.length === 0) return true

    const channel = input[0]
    if (!channel) return true

    let i = 0
    while (i < channel.length) {
      const remaining = this._buffer.length - this._offset
      const toCopy = Math.min(remaining, channel.length - i)
      this._buffer.set(channel.subarray(i, i + toCopy), this._offset)
      this._offset += toCopy
      i += toCopy

      if (this._offset >= this._buffer.length) {
        // Send a copy of the buffer to the main thread
        this.port.postMessage(this._buffer.slice())
        this._offset = 0
      }
    }

    return true
  }
}

registerProcessor("pcm-processor", PcmProcessor)
