import { zodResolver } from "@hookform/resolvers/zod"
import { Plus } from "lucide-react"
import { type FieldValues, type UseFormReturn, useForm } from "react-hook-form"
import type { z } from "zod"

import { type UserCreate, UsersService } from "@/client"
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
  DialogTrigger,
} from "@/components/ui/dialog"
import { Form } from "@/components/ui/form"
import { LoadingButton } from "@/components/ui/loading-button"
import { useApiMutation } from "@/hooks/useApiMutation"
import { useDialogForm } from "@/hooks/useDialogForm"
import { QUERY_KEYS } from "@/lib/constants"
import { addUserFormSchema } from "@/lib/schemas"

type FormData = z.infer<typeof addUserFormSchema>

const AddUser = () => {
  const form = useForm<FormData>({
    resolver: zodResolver(addUserFormSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      email: "",
      full_name: "",
      password: "",
      confirm_password: "",
      is_superuser: false,
      is_active: false,
    },
  })

  const dialog = useDialogForm({ form })

  const mutation = useApiMutation<unknown, UserCreate>({
    mutationFn: (data: UserCreate) =>
      UsersService.createUser({ requestBody: data }),
    successMessage: "User created successfully",
    onSuccess: () => dialog.close(),
    invalidateKeys: [[QUERY_KEYS.USERS]],
  })

  const onSubmit = (data: FormData) => {
    mutation.mutate(data)
  }

  return (
    <Dialog open={dialog.isOpen} onOpenChange={dialog.onOpenChange}>
      <DialogTrigger asChild>
        <Button className="my-4">
          <Plus className="mr-2" />
          Add User
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add User</DialogTitle>
          <DialogDescription>
            Fill in the form below to add a new user to the system.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <div className="grid gap-4 py-4">
              <UserFormFields
                form={form as unknown as UseFormReturn<FieldValues>}
              />
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

export default AddUser
