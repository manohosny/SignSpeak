import { useCallback, useRef, useState } from "react"

import { createWavBlobUrl } from "@/lib/audio"

/**
 * Plays WAV audio received from TTS.
 *
 * Uses HTMLAudioElement with a persistent element that gets "unlocked"
 * during a user gesture. Once unlocked, subsequent plays work even
 * from WebSocket callbacks.
 */
export function useAudioPlayer() {
  const [isPlaying, setIsPlaying] = useState(false)
  const queueRef = useRef<string[]>([])
  const playingRef = useRef(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const unlockedRef = useRef(false)

  const getAudio = useCallback(() => {
    if (!audioRef.current) {
      audioRef.current = new Audio()
    }
    return audioRef.current
  }, [])

  const playNext = useCallback(() => {
    if (queueRef.current.length === 0) {
      playingRef.current = false
      setIsPlaying(false)
      return
    }

    playingRef.current = true
    setIsPlaying(true)

    const url = queueRef.current.shift()!
    const audio = getAudio()

    audio.onended = () => {
      URL.revokeObjectURL(url)
      playNext()
    }

    audio.onerror = () => {
      console.error("[AudioPlayer] playback error for", url)
      URL.revokeObjectURL(url)
      playNext()
    }

    audio.src = url
    audio.play().catch((err) => {
      console.error("[AudioPlayer] play() rejected:", err)
      URL.revokeObjectURL(url)
      playNext()
    })
  }, [getAudio])

  const playAudio = useCallback(
    (wavData: ArrayBuffer) => {
      console.log(
        "[AudioPlayer] received audio:",
        wavData.byteLength,
        "bytes, unlocked:",
        unlockedRef.current,
      )
      const url = createWavBlobUrl(wavData)
      queueRef.current.push(url)
      if (!playingRef.current) {
        playNext()
      }
    },
    [playNext],
  )

  const stopAudio = useCallback(() => {
    const audio = audioRef.current
    if (audio) {
      audio.pause()
      audio.onended = null
      audio.onerror = null
    }
    for (const url of queueRef.current) {
      URL.revokeObjectURL(url)
    }
    queueRef.current = []
    playingRef.current = false
    setIsPlaying(false)
  }, [])

  // Call during a user gesture (e.g. mic button click) to unlock
  // audio playback for subsequent programmatic play() calls.
  const unlockAudio = useCallback(() => {
    if (unlockedRef.current) return
    const audio = getAudio()
    // Play a silent data URI to satisfy autoplay policy
    audio.src =
      "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA="
    audio
      .play()
      .then(() => {
        unlockedRef.current = true
        console.log("[AudioPlayer] unlocked via user gesture")
      })
      .catch(() => {
        console.warn("[AudioPlayer] unlock failed — audio may not play")
      })
  }, [getAudio])

  return { playAudio, isPlaying, stopAudio, unlockAudio }
}
