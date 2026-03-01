import type { Control, FieldPath, FieldValues } from "react-hook-form"

import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

interface EditableFieldProps<T extends FieldValues> {
  control: Control<T>
  name: FieldPath<T>
  label: string
  editMode: boolean
  type?: string
  placeholder?: string
  emptyText?: string
}

export function EditableField<T extends FieldValues>({
  control,
  name,
  label,
  editMode,
  type = "text",
  placeholder,
  emptyText = "N/A",
}: EditableFieldProps<T>) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) =>
        editMode ? (
          <FormItem>
            <FormLabel>{label}</FormLabel>
            <FormControl>
              <Input type={type} placeholder={placeholder} {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        ) : (
          <FormItem>
            <FormLabel>{label}</FormLabel>
            <p
              className={cn(
                "py-2 truncate max-w-sm",
                !field.value && "text-muted-foreground",
              )}
            >
              {field.value || emptyText}
            </p>
          </FormItem>
        )
      }
    />
  )
}
