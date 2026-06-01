import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

/**
 * SignSpeak wordmark.
 *
 * Text-based for now — design assets to replace this can be wired in by
 * importing the SVGs and rendering an `<img>` per `variant`. The brand
 * colour comes from the Tailwind theme so dark/light modes follow the
 * rest of the app automatically.
 */
export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "icon" ? (
      <span
        role="img"
        aria-label="SignSpeak"
        className={cn(
          "inline-flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground font-bold",
          className,
        )}
      >
        S
      </span>
    ) : (
      // No aria-label needed: the visible text content is the brand name,
      // so screen readers will announce it natively.
      <span
        className={cn(
          "font-semibold tracking-tight text-foreground",
          variant === "responsive" &&
            "text-base group-data-[collapsible=icon]:hidden",
          variant === "full" && "text-xl",
          className,
        )}
      >
        SignSpeak
      </span>
    )

  if (!asLink) return content

  return (
    <Link to="/" className="inline-flex items-center">
      {content}
    </Link>
  )
}
