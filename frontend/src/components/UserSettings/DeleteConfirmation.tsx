import { useState } from "react"

import { UsersService } from "@/client"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import { Button } from "@/components/ui/button"
import { useApiMutation } from "@/hooks/useApiMutation"
import useAuth from "@/hooks/useAuth"
import { QUERY_KEYS } from "@/lib/constants"

const DeleteConfirmation = () => {
  const [isOpen, setIsOpen] = useState(false)
  const { logout } = useAuth()

  const mutation = useApiMutation<unknown, void>({
    mutationFn: () => UsersService.deleteUserMe(),
    successMessage: "Your account has been successfully deleted",
    onSuccess: () => logout(),
    invalidateKeys: [[QUERY_KEYS.CURRENT_USER]],
  })

  return (
    <>
      <Button
        variant="destructive"
        className="mt-3"
        onClick={() => setIsOpen(true)}
      >
        Delete Account
      </Button>
      <ConfirmDialog
        open={isOpen}
        onOpenChange={setIsOpen}
        title="Confirmation Required"
        description={
          <>
            All your account data will be <strong>permanently deleted.</strong>{" "}
            If you are sure, please click <strong>"Confirm"</strong> to proceed.
            This action cannot be undone.
          </>
        }
        onConfirm={() => mutation.mutate()}
        isPending={mutation.isPending}
      />
    </>
  )
}

export default DeleteConfirmation
