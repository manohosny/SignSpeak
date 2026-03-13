import { useCallback, useRef, useState } from "react"

import { float32ToPcm16 } from "@/lib/audio"

interface UseAudioRecorderOptions {
  onAudioChunk: (pcm16: ArrayBuffer) => void
  onVadChange?: (speaking: boolean) => void
  enabled: boolean
  vadEnabled?: boolean
}

export function useAudioRecorder({
  onAudioChunk,
  onVadChange,
  enabled,
  vadEnabled = true,
}: UseAudioRecorderOptions) {
  const [isRecording, setIsRecording] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const audioContextRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const onChunkRef = useRef(onAudioChunk)
  const onVadChangeRef = useRef(onVadChange)
  onChunkRef.current = onAudioChunk
  onVadChangeRef.current = onVadChange

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
      const worklet = new AudioWorkletNode(ctx, "pcm-processor", {
        processorOptions: {
          vadEnabled,
          speechThreshold: 0.01,
          silenceThreshold: 0.006,
          hangoverMs: 320,
        },
      })

      worklet.port.onmessage = (event: MessageEvent) => {
        const data = event.data
        // VAD status message (object with type field)
        if (data && typeof data === "object" && data.type === "vad") {
          setIsSpeaking(data.speaking)
          onVadChangeRef.current?.(data.speaking)
          return
        }
        // Audio data (Float32Array)
        if (data instanceof Float32Array) {
          const pcm16 = float32ToPcm16(data)
          onChunkRef.current(pcm16)
        }
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
  }, [enabled, vadEnabled])

  const stopRecording = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => {
      t.stop()
    })
    streamRef.current = null

    audioContextRef.current?.close()
    audioContextRef.current = null

    setIsRecording(false)
    setIsSpeaking(false)
  }, [])

  return { isRecording, isSpeaking, startRecording, stopRecording, error }
}
