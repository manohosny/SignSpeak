import { useCallback, useEffect, useRef, useState } from "react"

/**
 * Plays WAV audio received from TTS via the Web Audio API.
 *
 * Uses AudioContext + decodeAudioData + AudioBufferSourceNode instead of
 * HTMLAudioElement. Once the AudioContext is resume()'d during a user
 * gesture, all subsequent programmatic plays work — even from WebSocket
 * callbacks — without needing per-play gesture authorization.
 *
 * Registers document-level event listeners that auto-unlock the
 * AudioContext on the user's very first interaction with the page.
 */
export function useAudioPlayer() {
  const ctxRef = useRef<AudioContext | null>(null)
  const queueRef = useRef<ArrayBuffer[]>([])
  const playingRef = useRef(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [hasPendingAudio, setHasPendingAudio] = useState(false)

  const getCtx = useCallback(() => {
    if (!ctxRef.current) {
      ctxRef.current = new AudioContext()
    }
    return ctxRef.current
  }, [])

  const playNext = useCallback(async () => {
    const ctx = getCtx()
    if (queueRef.current.length === 0 || ctx.state !== "running") {
      playingRef.current = false
      setIsPlaying(false)
      if (queueRef.current.length === 0) {
        setHasPendingAudio(false)
      }
      return
    }

    playingRef.current = true
    setIsPlaying(true)

    const wavData = queueRef.current.shift()!
    if (queueRef.current.length === 0) {
      setHasPendingAudio(false)
    }
    try {
      const audioBuffer = await ctx.decodeAudioData(wavData)
      const source = ctx.createBufferSource()
      source.buffer = audioBuffer
      source.connect(ctx.destination)
      source.onended = () => playNext()
      source.start()
    } catch (err) {
      console.error("[AudioPlayer] decode/play error:", err)
      playNext()
    }
  }, [getCtx])

  const playAudio = useCallback(
    (wavData: ArrayBuffer) => {
      const ctx = getCtx()
      console.log(
        "[AudioPlayer] received audio:",
        wavData.byteLength,
        "bytes, ctx state:",
        ctx.state,
      )
      queueRef.current.push(wavData)

      if (ctx.state !== "running") {
        setHasPendingAudio(true)
      }

      if (!playingRef.current) {
        playNext()
      }
    },
    [getCtx, playNext],
  )

  const stopAudio = useCallback(() => {
    queueRef.current = []
    playingRef.current = false
    setIsPlaying(false)
    setHasPendingAudio(false)
  }, [])

  // Resume AudioContext during a user gesture (click, tap, keypress, etc.).
  // Once resumed, it stays running for the lifetime of the page.
  const unlockAudio = useCallback(() => {
    const ctx = getCtx()
    if (ctx.state === "suspended") {
      ctx.resume().then(() => {
        console.log("[AudioPlayer] AudioContext resumed")
        setHasPendingAudio(false)
        // Drain any audio that was queued while suspended
        if (queueRef.current.length > 0 && !playingRef.current) {
          playNext()
        }
      })
    }
  }, [getCtx, playNext])

  // Auto-unlock: register document-level listeners that fire on the
  // user's very first interaction (click, tap, keypress, etc.).
  // { capture: true } ensures we see events even if children stopPropagation.
  // { once: true } auto-removes each listener after first fire.
  useEffect(() => {
    const handler = () => unlockAudio()
    const events = ["click", "touchstart", "keydown", "pointerdown"]
    for (const evt of events) {
      document.addEventListener(evt, handler, { once: true, capture: true })
    }
    return () => {
      for (const evt of events) {
        document.removeEventListener(evt, handler, { capture: true })
      }
    }
  }, [unlockAudio])

  return { playAudio, isPlaying, stopAudio, unlockAudio, hasPendingAudio }
}
