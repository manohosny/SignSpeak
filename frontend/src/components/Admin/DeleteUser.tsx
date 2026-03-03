import { Trash2 } from "lucide-react"
import { useState } from "react"

import { UsersService } from "@/client"
import { ConfirmDialog } from "@/components/Common/ConfirmDialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
import { useApiMutation } from "@/hooks/useApiMutation"
import { QUERY_KEYS } from "@/lib/constants"

interface DeleteUserProps {
  id: string
  onSuccess: () => void
}

const DeleteUser = ({ id, onSuccess }: DeleteUserProps) => {
  const [isOpen, setIsOpen] = useState(false)

  const mutation = useApiMutation<unknown, string>({
    mutationFn: (userId: string) => UsersService.deleteUser({ userId }),
    successMessage: "The user was deleted successfully",
    onSuccess: () => {
      setIsOpen(false)
      onSuccess()
    },
    invalidateKeys: [[QUERY_KEYS.USERS]],
  })

  return (
    <>
      <DropdownMenuItem
        variant="destructive"
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
      >
        <Trash2 />
        Delete User
      </DropdownMenuItem>
      <ConfirmDialog
        open={isOpen}
        onOpenChange={setIsOpen}
        title="Delete User"
        description={
          <>
            All items associated with this user will also be{" "}
            <strong>permanently deleted.</strong> Are you sure? You will not be
            able to undo this action.
          </>
        }
        onConfirm={() => mutation.mutate(id)}
        isPending={mutation.isPending}
      />
    </>
  )
}

export default DeleteUser
