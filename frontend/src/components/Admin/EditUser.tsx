import { zodResolver } from "@hookform/resolvers/zod"
import { Pencil } from "lucide-react"
import { useForm } from "react-hook-form"
import type { z } from "zod"

import { type UserPublic, UsersService } from "@/client"
import { UserFormFields } from "@/components/Admin/UserFormFields"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
import { Form } from "@/components/ui/form"
import { LoadingButton } from "@/components/ui/loading-button"
import { useApiMutation } from "@/hooks/useApiMutation"
import { useDialogForm } from "@/hooks/useDialogForm"
import { QUERY_KEYS } from "@/lib/constants"
import { editUserFormSchema } from "@/lib/schemas"

type FormData = z.infer<typeof editUserFormSchema>

interface EditUserProps {
  user: UserPublic
  onSuccess: () => void
}

const EditUser = ({ user, onSuccess }: EditUserProps) => {
  const form = useForm<FormData>({
    resolver: zodResolver(editUserFormSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      email: user.email,
      full_name: user.full_name ?? undefined,
      is_superuser: user.is_superuser,
      is_active: user.is_active,
    },
  })

  const dialog = useDialogForm({ form })

  const mutation = useApiMutation<unknown, FormData>({
    mutationFn: (data: FormData) =>
      UsersService.updateUser({ userId: user.id, requestBody: data }),
    successMessage: "User updated successfully",
    onSuccess: () => {
      dialog.close()
      onSuccess()
    },
    invalidateKeys: [[QUERY_KEYS.USERS]],
  })

  const onSubmit = (data: FormData) => {
    // exclude confirm_password from submission data and remove password if empty
    const { confirm_password: _, ...submitData } = data
    if (!submitData.password) {
      delete submitData.password
    }
    mutation.mutate(submitData)
  }

  return (
    <Dialog open={dialog.isOpen} onOpenChange={dialog.onOpenChange}>
      <DropdownMenuItem
        onSelect={(e) => e.preventDefault()}
        onClick={() => dialog.open()}
      >
        <Pencil />
        Edit User
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <DialogHeader>
              <DialogTitle>Edit User</DialogTitle>
              <DialogDescription>
                Update the user details below.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <UserFormFields form={form} passwordRequired={false} />
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" disabled={mutation.isPending}>
                  Cancel
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                Save
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default EditUser
