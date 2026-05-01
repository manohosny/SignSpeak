import { expect, test } from "@playwright/test"

test.describe("Meeting page", () => {
  test("creates and loads meeting without media errors", async ({ page }) => {
    const consoleErrors: string[] = []
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text())
      }
    })

    // Navigate to dashboard
    await page.goto("/")

    // Create a meeting through the UI
    await page.getByRole("button", { name: "New Meeting" }).click()
    await page.getByRole("button", { name: "Create" }).click()

    // Wait for meeting to be created (dialog title changes)
    await expect(page.getByText("Meeting Created")).toBeVisible()

    // Join the meeting
    await page.getByRole("button", { name: "Join Meeting" }).click()

    // Should navigate to /meeting/{code}
    await page.waitForURL(/\/meeting\//)

    // Verify we reach the waiting room state
    await expect(
      page.getByText("Waiting for partner to join..."),
    ).toBeVisible({ timeout: 10_000 })

    // Verify no error state
    await expect(page.getByText("Something went wrong")).not.toBeVisible()

    // Verify no media-related console errors (NotAllowedError, permission denied)
    const mediaErrors = consoleErrors.filter(
      (e) =>
        e.includes("NotAllowedError") || e.includes("permission denied"),
    )
    expect(mediaErrors).toHaveLength(0)
  })

  test("fake media device provides working audio stream", async ({ page }) => {
    await page.goto("/")

    const result = await page.evaluate(async (): Promise<
      | { success: true; tracks: { kind: string; readyState: string }[] }
      | { success: false; error: string }
    > => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1 },
        })
        const tracks = stream.getTracks()
        const trackInfo = tracks.map((t) => ({
          kind: t.kind,
          readyState: t.readyState,
        }))
        tracks.forEach((t) => t.stop())
        return { success: true, tracks: trackInfo }
      } catch (err) {
        return {
          success: false,
          error: err instanceof Error ? err.message : String(err),
        }
      }
    })

    expect(result.success).toBe(true)
    if (!result.success) throw new Error("getUserMedia failed")
    expect(result.tracks).toHaveLength(1)
    expect(result.tracks[0].kind).toBe("audio")
    expect(result.tracks[0].readyState).toBe("live")
  })
})
