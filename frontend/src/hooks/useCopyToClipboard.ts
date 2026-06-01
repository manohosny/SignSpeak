// source: https://usehooks-ts.com/react-hook/use-copy-to-clipboard
import { useCallback, useState } from "react"

import { logWarn } from "@/lib/logger"

type CopiedValue = string | null

type CopyFn = (text: string) => Promise<boolean>

export function useCopyToClipboard(): [CopiedValue, CopyFn] {
  const [copiedText, setCopiedText] = useState<CopiedValue>(null)

  const copy: CopyFn = useCallback(async (text) => {
    if (!navigator?.clipboard) {
      logWarn("Clipboard not supported")
      return false
    }

    try {
      await navigator.clipboard.writeText(text)
      setCopiedText(text)

      setTimeout(() => setCopiedText(null), 2000)

      return true
    } catch (error) {
      logWarn("Copy failed", { error })
      setCopiedText(null)
      return false
    }
  }, [])

  return [copiedText, copy]
}
