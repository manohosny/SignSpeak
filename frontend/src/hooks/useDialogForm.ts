import { useCallback, useState } from "react"

interface UseDialogFormOptions {
  form?: { reset: () => void }
}

export function useDialogForm({ form }: UseDialogFormOptions = {}) {
  const [isOpen, setIsOpen] = useState(false)

  const open = useCallback(() => setIsOpen(true), [])

  const close = useCallback(() => {
    setIsOpen(false)
    form?.reset()
  }, [form])

  const onOpenChange = useCallback(
    (value: boolean) => {
      if (!value) {
        form?.reset()
      }
      setIsOpen(value)
    },
    [form],
  )

  return { isOpen, open, close, onOpenChange }
}
