import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { ApiError, OpenAPI } from "./client"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import "./index.css"
import {
  clearLocalSession,
  hasSessionMarker,
  refreshTokens,
} from "./lib/auth-tokens"
import { routeTree } from "./routeTree.gen"

OpenAPI.BASE = import.meta.env.VITE_API_URL
// Browser sends the HttpOnly access-token cookie automatically once
// `withCredentials` is on. The Authorization header is no longer needed
// for browser-driven calls.
OpenAPI.WITH_CREDENTIALS = true
OpenAPI.CREDENTIALS = "include"

// Ensure concurrent 401s from a burst of in-flight queries trigger only
// ONE refresh attempt — otherwise each query independently rotates the
// token and the later ones invalidate the earlier ones.
let refreshPromise: Promise<boolean> | null = null
function attemptRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = refreshTokens().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

async function handleApiError(error: Error) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      // Try to rotate the cookie pair before giving up.
      const refreshed = await attemptRefresh()
      if (refreshed) {
        // Reload so in-flight react-query state is rebuilt against the
        // new cookie. A scoped retry-original-request hook would avoid
        // the flash; out of scope for this change.
        window.location.reload()
        return
      }
      clearLocalSession()
      window.location.href = "/login"
      return
    }
    if (error.status === 403) {
      clearLocalSession()
      window.location.href = "/login"
      return
    }
  } else if (hasSessionMarker()) {
    // Network error (backend unreachable) while we think we're logged in.
    clearLocalSession()
    window.location.href = "/login"
  }
}
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: handleApiError,
  }),
  mutationCache: new MutationCache({
    onError: handleApiError,
  }),
})

const router = createRouter({ routeTree })
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <Toaster richColors closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
