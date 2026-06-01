import type { FieldValues, UseFormReturn } from "react-hook-form"

import { Checkbox } from "@/components/ui/checkbox"
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"

// Accept any react-hook-form return shape — every user-form schema in
// this codebase has the same field names (`email`, `password`, …) and
// the FormField path-strings are validated at runtime by zod, so giving
// up the compile-time path narrowing is a fair trade for letting Add /
// Edit reuse the same fields component without three duplicate copies.
interface UserFormFieldsProps {
  form: UseFormReturn<FieldValues>
  passwordRequired?: boolean
}

export function UserFormFields({
  form,
  passwordRequired = true,
}: UserFormFieldsProps) {
  const { control } = form
  return (
    <>
      <FormField
        control={control}
        name="email"
        render={({ field }) => (
          <FormItem>
            <FormLabel>
              Email <span className="text-destructive">*</span>
            </FormLabel>
            <FormControl>
              <Input
                placeholder="Email"
                type="email"
                autoComplete="email"
                {...field}
                required
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="full_name"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Full Name</FormLabel>
            <FormControl>
              <Input
                placeholder="Full name"
                type="text"
                autoComplete="name"
                {...field}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="password"
        render={({ field }) => (
          <FormItem>
            <FormLabel>
              Set Password{" "}
              {passwordRequired && <span className="text-destructive">*</span>}
            </FormLabel>
            <FormControl>
              <Input
                placeholder="Password"
                type="password"
                autoComplete="new-password"
                {...field}
                required={passwordRequired}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="confirm_password"
        render={({ field }) => (
          <FormItem>
            <FormLabel>
              Confirm Password{" "}
              {passwordRequired && <span className="text-destructive">*</span>}
            </FormLabel>
            <FormControl>
              <Input
                placeholder="Password"
                type="password"
                autoComplete="new-password"
                {...field}
                required={passwordRequired}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="is_superuser"
        render={({ field }) => (
          <FormItem className="flex items-center gap-3 space-y-0">
            <FormControl>
              <Checkbox
                checked={field.value}
                onCheckedChange={field.onChange}
              />
            </FormControl>
            <FormLabel className="font-normal">Is superuser?</FormLabel>
          </FormItem>
        )}
      />

      <FormField
        control={control}
        name="is_active"
        render={({ field }) => (
          <FormItem className="flex items-center gap-3 space-y-0">
            <FormControl>
              <Checkbox
                checked={field.value}
                onCheckedChange={field.onChange}
              />
            </FormControl>
            <FormLabel className="font-normal">Is active?</FormLabel>
          </FormItem>
        )}
      />
    </>
  )
}
