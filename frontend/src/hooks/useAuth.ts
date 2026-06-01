import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"

import {
  type Body_login_login_access_token as AccessToken,
  LoginService,
  type UserPublic,
  type UserRegister,
  UsersService,
} from "@/client"
import { clearLocalSession, hasSessionMarker } from "@/lib/auth-tokens"
import { QUERY_KEYS } from "@/lib/constants"
import { handleError } from "@/utils"
import useCustomToast from "./useCustomToast"

/**
 * Synchronous "is the user logged in?" check used by route guards.
 *
 * Reads the non-HttpOnly `ss_session` marker cookie set by the backend.
 * The marker contains no payload — it just signals the FE that an
 * HttpOnly access-token cookie should be sitting alongside it.
 */
const isLoggedIn = () => hasSessionMarker()

const useAuth = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const { data: user } = useQuery<UserPublic | null, Error>({
    queryKey: [QUERY_KEYS.CURRENT_USER],
    queryFn: UsersService.readUserMe,
    enabled: isLoggedIn(),
    retry: false,
  })

  const signUpMutation = useMutation({
    mutationFn: (data: UserRegister) =>
      UsersService.registerUser({ requestBody: data }),
    onSuccess: () => {
      navigate({ to: "/login" })
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.USERS] })
    },
  })

  // Cookies are set by the backend as part of the response — we only
  // need to await the call. The JSON body still comes back too, for
  // backwards compat with non-browser API clients, but we ignore it.
  const login = (data: AccessToken) =>
    LoginService.loginAccessToken({ formData: data })

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: () => {
      navigate({ to: "/" })
    },
    onError: handleError.bind(showErrorToast),
  })

  const logout = async () => {
    // Server-side: revoke the refresh token and clear the auth cookies.
    // The browser sends the HttpOnly refresh cookie automatically; we
    // swallow failures so local cleanup runs even when offline.
    try {
      await LoginService.logout()
    } catch {
      // ignored — local cleanup runs regardless
    }
    clearLocalSession()
    queryClient.clear()
    navigate({ to: "/login" })
  }

  return {
    signUpMutation,
    loginMutation,
    logout,
    user,
  }
}

export { isLoggedIn }
export default useAuth
