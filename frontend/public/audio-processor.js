/**
 * AudioWorklet processor for capturing mic input as PCM16 chunks.
 *
 * Runs in a separate thread (AudioWorkletGlobalScope).
 * Buffers Float32 samples and posts them to the main thread
 * when the buffer reaches ~250ms of audio at 16kHz (4000 samples).
 *
 * Includes optional Voice Activity Detection (VAD) that suppresses
 * silent chunks and signals speech boundaries to the main thread.
 */

// VAD states
const SILENT = 0
const SPEECH = 1
const HANGOVER = 2

class PcmProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()

    const opts = (options && options.processorOptions) || {}
    this._vadEnabled = opts.vadEnabled !== false // default: on
    this._speechThreshold = opts.speechThreshold || 0.01
    this._silenceThreshold = opts.silenceThreshold || 0.006
    // Hangover frames: how many 128-sample frames of silence before
    // transitioning from SPEECH → SILENT. At 16kHz, each frame = 8ms.
    // Default ~320ms = 40 frames.
    const hangoverMs = opts.hangoverMs || 320
    this._hangoverFrames = Math.ceil(hangoverMs / 8)

    // Pre-roll: ring buffer of recent frames to prepend when speech starts.
    // ~160ms = 20 frames, captures unvoiced consonants before vocal energy.
    this._preRollCapacity = 20
    this._preRollRing = []
    this._preRollIndex = 0

    // VAD state
    this._state = SILENT
    this._hangoverCount = 0
    this._lastReportedSpeaking = false

    // Audio output buffer (same as before: 4000 samples = 250ms at 16kHz)
    this._buffer = new Float32Array(4000)
    this._offset = 0
  }

  /**
   * Compute RMS energy of a Float32Array segment.
   */
  _rms(samples) {
    let sum = 0
    for (let i = 0; i < samples.length; i++) {
      sum += samples[i] * samples[i]
    }
    return Math.sqrt(sum / samples.length)
  }

  /**
   * Send a VAD state change notification to the main thread.
   */
  _notifyVad(speaking) {
    if (speaking !== this._lastReportedSpeaking) {
      this._lastReportedSpeaking = speaking
      this.port.postMessage({ type: "vad", speaking })
    }
  }

  /**
   * Flush pre-roll ring buffer contents into the output buffer.
   * Called when speech starts, to include audio just before the onset.
   */
  _flushPreRoll() {
    const len = this._preRollRing.length
    if (len === 0) return

    // Read ring buffer in order: oldest first
    const start =
      len < this._preRollCapacity ? 0 : this._preRollIndex % len
    for (let i = 0; i < len; i++) {
      const frame = this._preRollRing[(start + i) % len]
      this._appendToBuffer(frame)
    }
    // Clear ring buffer after flush
    this._preRollRing = []
    this._preRollIndex = 0
  }

  /**
   * Append samples to the output buffer, posting when full.
   */
  _appendToBuffer(samples) {
    let i = 0
    while (i < samples.length) {
      const remaining = this._buffer.length - this._offset
      const toCopy = Math.min(remaining, samples.length - i)
      this._buffer.set(samples.subarray(i, i + toCopy), this._offset)
      this._offset += toCopy
      i += toCopy

      if (this._offset >= this._buffer.length) {
        this.port.postMessage(this._buffer.slice())
        this._offset = 0
      }
    }
  }

  /**
   * Store a frame in the pre-roll ring buffer (used during SILENT state).
   */
  _pushPreRoll(frame) {
    if (this._preRollRing.length < this._preRollCapacity) {
      this._preRollRing.push(frame.slice())
    } else {
      this._preRollRing[this._preRollIndex % this._preRollCapacity] =
        frame.slice()
    }
    this._preRollIndex = (this._preRollIndex + 1) % this._preRollCapacity
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || input.length === 0) return true

    const channel = input[0]
    if (!channel) return true

    // No VAD: send everything (original behavior)
    if (!this._vadEnabled) {
      this._appendToBuffer(channel)
      return true
    }

    // VAD-enabled path
    const rms = this._rms(channel)

    switch (this._state) {
      case SILENT:
        if (rms >= this._speechThreshold) {
          // Speech onset — flush pre-roll, switch to SPEECH
          this._state = SPEECH
          this._hangoverCount = 0
          this._notifyVad(true)
          this._flushPreRoll()
          this._appendToBuffer(channel)
        } else {
          // Still silent — store in pre-roll ring
          this._pushPreRoll(channel)
        }
        break

      case SPEECH:
        this._appendToBuffer(channel)
        if (rms < this._silenceThreshold) {
          // Possible end of speech — enter hangover
          this._state = HANGOVER
          this._hangoverCount = 1
        }
        break

      case HANGOVER:
        // Always send audio during hangover (natural pauses between words)
        this._appendToBuffer(channel)
        if (rms >= this._speechThreshold) {
          // Speech resumed — back to SPEECH
          this._state = SPEECH
          this._hangoverCount = 0
        } else {
          this._hangoverCount++
          if (this._hangoverCount >= this._hangoverFrames) {
            // Hangover expired — speech truly ended
            this._state = SILENT
            this._hangoverCount = 0
            this._notifyVad(false)
          }
        }
        break
    }

    return true
  }
}

registerProcessor("pcm-processor", PcmProcessor)
