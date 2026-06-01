import { Link } from "@tanstack/react-router"
import { AlertCircle } from "lucide-react"
import type { ReactNode } from "react"
import { ErrorBoundary, type FallbackProps } from "react-error-boundary"

import { Button } from "@/components/ui/button"
import { logError } from "@/lib/logger"

function MeetingFallback({ error, resetErrorBoundary }: FallbackProps) {
  return (
    <div
      role="alert"
      className="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center"
    >
      <AlertCircle className="h-10 w-10 text-destructive" aria-hidden="true" />
      <h2 className="text-2xl font-bold">Something went wrong</h2>
      <p className="max-w-md text-muted-foreground">
        {error instanceof Error ? error.message : "Unexpected error in meeting"}
      </p>
      <div className="flex gap-2">
        <Button onClick={resetErrorBoundary}>Rejoin meeting</Button>
        <Button variant="outline" asChild>
          <Link to="/">Back to dashboard</Link>
        </Button>
      </div>
    </div>
  )
}

interface MeetingErrorBoundaryProps {
  children: ReactNode
  /**
   * Reset key bumped externally to force a fresh mount of the children.
   * `react-error-boundary` reset is value-equality based, so any new
   * value (including 0 → 1) triggers it; a fresh-array-each-render
   * bug isn't a concern here because the array is constructed only on
   * `resetKey` changes.
   */
  resetKey: number
  /** Fired when the user clicks "Rejoin meeting"; bump the resetKey here. */
  onReset?: () => void
}

export function MeetingErrorBoundary({
  children,
  resetKey,
  onReset,
}: MeetingErrorBoundaryProps) {
  return (
    <ErrorBoundary
      FallbackComponent={MeetingFallback}
      resetKeys={[resetKey]}
      onReset={onReset}
      onError={(error) => {
        logError("[MeetingErrorBoundary] caught", { error })
      }}
    >
      {children}
    </ErrorBoundary>
  )
}
