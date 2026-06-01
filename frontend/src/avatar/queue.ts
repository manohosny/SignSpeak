// Serial FIFO animation queue for the signing avatar.
//
// CWASA renders one SiGML document at a time. Without sequencing, a burst of
// incoming glosses would overwrite each other and only the last would be
// signed. This queue plays every gloss in arrival order: it starts the next
// item only once the current one finishes, where "finishes" is CWASA's
// `animidle` event (with a watchdog timeout as a safety net).

import { logError } from "@/lib/logger"

import { onAnimIdle, playSigml, stop } from "./driver"

export interface AvatarQueueItem {
  /** GlossEntry id — used to dedupe re-delivered entries. */
  id: string
  /** Assembled SiGML document to hand to CWASA. */
  sigml: string
  /** Plain-text gloss, surfaced to the aria-live caption while signing. */
  glossText: string
}

interface AvatarQueueDeps {
  playSigml: (sigml: string) => void
  stop: () => void
  onAnimIdle: (fn: () => void) => void
}

export interface AvatarQueue {
  /** Wire the CWASA completion hook and start draining. Call once, post-init. */
  initAvatarQueue: () => void
  /** Append an item; no-op if its id was already seen. */
  enqueueSigml: (item: AvatarQueueItem) => void
  /** Stop playback and discard everything pending (unmount / meeting end). */
  clearAvatarQueue: () => void
  /** Observe the item currently being signed (null when idle). */
  subscribeCurrent: (fn: (item: AvatarQueueItem | null) => void) => () => void
}

// Cap on pending (not-yet-playing) items. Sign language is real-time, so when
// the speaker outruns the avatar we keep the newest messages and drop the
// oldest rather than letting latency grow without bound.
export const MAX_QUEUE = 12

// Watchdog budget. Playback normally advances on CWASA's `animidle` event; if
// that never arrives (e.g. animgen stalls) this timeout drains the queue so
// the avatar can't deadlock. Sized from the SiGML's sign count.
const BASE_TIMEOUT_MS = 1500
const PER_SIGN_MS = 2200

function estimateMs(sigml: string): number {
  const signCount = (sigml.match(/<hns_sign\b/g) ?? []).length
  return BASE_TIMEOUT_MS + PER_SIGN_MS * Math.max(1, signCount)
}

export function createAvatarQueue(deps: AvatarQueueDeps): AvatarQueue {
  const pending: AvatarQueueItem[] = []
  const seenIds = new Set<string>()
  const subscribers = new Set<(item: AvatarQueueItem | null) => void>()
  let playing: AvatarQueueItem | null = null
  let watchdog: ReturnType<typeof setTimeout> | null = null
  let ready = false
  let wired = false
  // Bumped by clearAvatarQueue() so any in-flight completion — a watchdog
  // timer, or a spurious `animidle` from the programmatic stop — is recognised
  // as stale and ignored instead of advancing the wrong item.
  let generation = 0

  function emitCurrent(): void {
    for (const fn of subscribers) fn(playing)
  }

  function clearWatchdog(): void {
    if (watchdog !== null) {
      clearTimeout(watchdog)
      watchdog = null
    }
  }

  function finishCurrent(gen: number): void {
    if (gen !== generation) return // stale completion from a cleared run
    if (playing === null) return // already finished (idle event / watchdog race)
    clearWatchdog()
    playing = null
    pumpQueue()
    if (playing === null) emitCurrent() // queue drained -> notify idle
  }

  function pumpQueue(): void {
    if (!ready || playing !== null) return
    const item = pending.shift()
    if (item === undefined) return
    playing = item
    emitCurrent()
    const gen = generation
    try {
      deps.playSigml(item.sigml)
    } catch (err) {
      // A scheduling failure must not stall the queue — treat it as an
      // instant completion and move on to the next item.
      logError("Avatar queue: playSigml threw", { err, id: item.id })
      finishCurrent(gen)
      return
    }
    watchdog = setTimeout(() => finishCurrent(gen), estimateMs(item.sigml))
  }

  function initAvatarQueue(): void {
    if (!wired) {
      deps.onAnimIdle(() => finishCurrent(generation))
      wired = true
    }
    ready = true
    pumpQueue()
  }

  function enqueueSigml(item: AvatarQueueItem): void {
    if (seenIds.has(item.id)) return
    seenIds.add(item.id)
    if (pending.length >= MAX_QUEUE) pending.shift() // drop oldest pending
    pending.push(item)
    pumpQueue()
  }

  function clearAvatarQueue(): void {
    generation++
    pending.length = 0
    clearWatchdog()
    playing = null
    emitCurrent()
    deps.stop()
  }

  function subscribeCurrent(
    fn: (item: AvatarQueueItem | null) => void,
  ): () => void {
    subscribers.add(fn)
    fn(playing)
    return () => {
      subscribers.delete(fn)
    }
  }

  return { initAvatarQueue, enqueueSigml, clearAvatarQueue, subscribeCurrent }
}

// App-wide singleton, wired to the real CWASA driver.
const avatarQueue = createAvatarQueue({ playSigml, stop, onAnimIdle })

export const initAvatarQueue = avatarQueue.initAvatarQueue
export const enqueueSigml = avatarQueue.enqueueSigml
export const clearAvatarQueue = avatarQueue.clearAvatarQueue
export const subscribeCurrent = avatarQueue.subscribeCurrent
