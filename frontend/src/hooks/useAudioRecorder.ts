import { useCallback, useRef, useState } from "react"

import { float32ToPcm16 } from "@/lib/audio"

interface UseAudioRecorderOptions {
  onAudioChunk: (pcm16: ArrayBuffer) => void
  enabled: boolean
}

export function useAudioRecorder({
  onAudioChunk,
  enabled,
}: UseAudioRecorderOptions) {
  const [isRecording, setIsRecording] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const audioContextRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const onChunkRef = useRef(onAudioChunk)
  onChunkRef.current = onAudioChunk

  const startRecording = useCallback(async () => {
    if (!enabled) return
    setError(null)

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      })
      streamRef.current = stream

      const ctx = new AudioContext({ sampleRate: 16000 })
      audioContextRef.current = ctx

      await ctx.audioWorklet.addModule("/audio-processor.js")

      const source = ctx.createMediaStreamSource(stream)
      const worklet = new AudioWorkletNode(ctx, "pcm-processor")

      worklet.port.onmessage = (event: MessageEvent<Float32Array>) => {
        const pcm16 = float32ToPcm16(event.data)
        onChunkRef.current(pcm16)
      }

      source.connect(worklet)
      worklet.connect(ctx.destination)

      setIsRecording(true)
    } catch (err) {
      const msg =
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "Microphone permission denied"
          : "Failed to start recording"
      setError(msg)
    }
  }, [enabled])

  const stopRecording = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => {
      t.stop()
    })
    streamRef.current = null

    audioContextRef.current?.close()
    audioContextRef.current = null

    setIsRecording(false)
  }, [])

  return { isRecording, startRecording, stopRecording, error }
}
