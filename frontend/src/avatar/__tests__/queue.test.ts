import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { type AvatarQueueItem, createAvatarQueue, MAX_QUEUE } from "../queue"

// Build a queue item whose SiGML carries exactly one <hns_sign>, so the
// watchdog estimate is deterministic (BASE + 1 * PER_SIGN).
function makeItem(id: string): AvatarQueueItem {
  return {
    id,
    sigml: `<sigml><hns_sign gloss="${id}"/></sigml>`,
    glossText: id,
  }
}

// A fresh queue plus its fake driver dependencies. `fireAnimIdle` replays the
// completion event CWASA would emit; the handler is captured at init time.
function setup() {
  const playSigml = vi.fn<(sigml: string) => void>()
  const stop = vi.fn<() => void>()
  let idleHandler: (() => void) | null = null
  const onAnimIdle = vi.fn((fn: () => void) => {
    idleHandler = fn
  })

  const queue = createAvatarQueue({ playSigml, stop, onAnimIdle })

  return {
    queue,
    playSigml,
    stop,
    onAnimIdle,
    fireAnimIdle: () => {
      if (!idleHandler) throw new Error("animidle handler not registered")
      idleHandler()
    },
    playedIds: () =>
      playSigml.mock.calls.map(([doc]) => /gloss="(\w+)"/.exec(doc)?.[1]),
  }
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe("createAvatarQueue", () => {
  it("does not play anything before the queue is initialised", () => {
    const { queue, playSigml } = setup()
    queue.enqueueSigml(makeItem("A"))
    expect(playSigml).not.toHaveBeenCalled()
  })

  it("drains items buffered before init once initialised", () => {
    const { queue, playSigml } = setup()
    queue.enqueueSigml(makeItem("A"))
    queue.initAvatarQueue()
    expect(playSigml).toHaveBeenCalledTimes(1)
    expect(playSigml).toHaveBeenCalledWith(makeItem("A").sigml)
  })

  it("signs queued items in FIFO order, one at a time, advancing on animidle", () => {
    const { queue, fireAnimIdle, playedIds } = setup()
    queue.initAvatarQueue()
    queue.enqueueSigml(makeItem("A"))
    queue.enqueueSigml(makeItem("B"))
    queue.enqueueSigml(makeItem("C"))

    expect(playedIds()).toEqual(["A"]) // only the first plays immediately
    fireAnimIdle()
    expect(playedIds()).toEqual(["A", "B"])
    fireAnimIdle()
    expect(playedIds()).toEqual(["A", "B", "C"])
  })

  it("deduplicates items that share an id", () => {
    const { queue, playSigml } = setup()
    queue.initAvatarQueue()
    queue.enqueueSigml(makeItem("A"))
    queue.enqueueSigml(makeItem("A"))
    expect(playSigml).toHaveBeenCalledTimes(1)
  })

  it("drops the oldest pending item when the queue overflows", () => {
    const { queue, fireAnimIdle, playedIds } = setup()
    queue.initAvatarQueue()
    // First item starts playing; the rest fill the pending queue.
    queue.enqueueSigml(makeItem("first"))
    for (let i = 0; i < MAX_QUEUE + 1; i++) {
      queue.enqueueSigml(makeItem(`n${i}`))
    }
    // Drain everything.
    for (let i = 0; i < MAX_QUEUE + 2; i++) fireAnimIdle()

    const played = playedIds()
    expect(played).toContain("first")
    expect(played).toContain(`n${MAX_QUEUE}`) // newest survived
    expect(played).not.toContain("n0") // oldest pending was dropped
  })

  it("advances via the watchdog timeout when no animidle event arrives", () => {
    const { queue, playedIds } = setup()
    queue.initAvatarQueue()
    queue.enqueueSigml(makeItem("A"))
    queue.enqueueSigml(makeItem("B"))

    expect(playedIds()).toEqual(["A"])
    vi.advanceTimersByTime(60_000) // well past any per-sign estimate
    expect(playedIds()).toEqual(["A", "B"])
  })

  it("does not double-advance when animidle and the watchdog both fire", () => {
    const { queue, fireAnimIdle, playedIds } = setup()
    queue.initAvatarQueue()
    queue.enqueueSigml(makeItem("A"))
    queue.enqueueSigml(makeItem("B"))

    fireAnimIdle() // B starts
    vi.advanceTimersByTime(60_000) // stale watchdog for A must be a no-op
    expect(playedIds()).toEqual(["A", "B"])
  })

  it("ignores a stale watchdog completion after clearAvatarQueue", () => {
    const { queue, playedIds } = setup()
    queue.initAvatarQueue()
    queue.enqueueSigml(makeItem("A")) // A plays, watchdog armed
    queue.clearAvatarQueue() // bumps generation
    queue.enqueueSigml(makeItem("B")) // B plays
    vi.advanceTimersByTime(60_000) // A's stale watchdog must not finish B

    expect(playedIds()).toEqual(["A", "B"])
  })

  it("clearAvatarQueue stops playback and discards pending items", () => {
    const { queue, stop, fireAnimIdle, playedIds } = setup()
    queue.initAvatarQueue()
    queue.enqueueSigml(makeItem("A"))
    queue.enqueueSigml(makeItem("B"))
    queue.enqueueSigml(makeItem("C"))

    queue.clearAvatarQueue()
    expect(stop).toHaveBeenCalledTimes(1)
    fireAnimIdle() // any pending CWASA event must not resurrect B or C
    expect(playedIds()).toEqual(["A"])
  })

  it("keeps the queue moving when scheduling a SiGML doc throws", () => {
    const { queue, playSigml, fireAnimIdle, playedIds } = setup()
    playSigml.mockImplementationOnce(() => {
      throw new Error("CWASA scheduling failure")
    })
    queue.initAvatarQueue()
    queue.enqueueSigml(makeItem("A")) // throws
    queue.enqueueSigml(makeItem("B"))

    // A failed instantly; B should still get its turn.
    fireAnimIdle()
    expect(playedIds()).toContain("B")
  })

  it("notifies subscribers of the current item and null when idle", () => {
    const { queue, fireAnimIdle } = setup()
    const seen: (string | null)[] = []
    queue.subscribeCurrent((item) => seen.push(item?.glossText ?? null))
    queue.initAvatarQueue()
    queue.enqueueSigml(makeItem("A"))
    fireAnimIdle() // queue drained -> idle

    expect(seen).toContain("A")
    expect(seen[seen.length - 1]).toBeNull()
  })

  it("stops notifying after a subscriber unsubscribes", () => {
    const { queue } = setup()
    const seen: (string | null)[] = []
    const unsubscribe = queue.subscribeCurrent((item) =>
      seen.push(item?.glossText ?? null),
    )
    unsubscribe()
    queue.initAvatarQueue()
    queue.enqueueSigml(makeItem("A"))

    expect(seen).not.toContain("A")
  })
})
