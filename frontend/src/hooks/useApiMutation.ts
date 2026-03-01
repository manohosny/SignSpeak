import { useMutation, useQueryClient } from "@tanstack/react-query"
import type { InvalidateQueryFilters } from "@tanstack/react-query"
import useCustomToast from "./useCustomToast"
import { handleError } from "@/utils"

interface UseApiMutationOptions<TData, TVariables> {
  mutationFn: (variables: TVariables) => Promise<TData>
  successMessage: string
  onSuccess?: () => void
  invalidateKeys?: string[][]
}

export function useApiMutation<TData, TVariables>({
  mutationFn,
  successMessage,
  onSuccess,
  invalidateKeys,
}: UseApiMutationOptions<TData, TVariables>) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  return useMutation({
    mutationFn,
    onSuccess: () => {
      showSuccessToast(successMessage)
      onSuccess?.()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      if (invalidateKeys) {
        for (const queryKey of invalidateKeys) {
          queryClient.invalidateQueries({ queryKey } as InvalidateQueryFilters)
        }
      }
    },
  })
}
