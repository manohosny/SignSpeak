import { z } from "zod"
import type { Body_login_login_access_token as AccessToken } from "@/client"

// Atomic schemas
export const emailSchema = z.email({ message: "Invalid email address" })

export const passwordSchema = z
  .string()
  .min(1, { message: "Password is required" })
  .min(8, { message: "Password must be at least 8 characters" })

export const confirmPasswordSchema = z
  .string()
  .min(1, { message: "Password confirmation is required" })

export const fullNameSchema = z
  .string()
  .min(1, { message: "Full Name is required" })

// Helper for password confirmation refinement
export function withPasswordConfirmation<
  T extends z.ZodType<Record<string, unknown>>,
>(schema: T, passwordField = "password", confirmField = "confirm_password") {
  return schema.refine((data) => data[passwordField] === data[confirmField], {
    message: "The passwords don't match",
    path: [confirmField],
  })
}

// Composed schemas
export const signUpFormSchema = withPasswordConfirmation(
  z.object({
    email: z.email(),
    full_name: fullNameSchema,
    password: passwordSchema,
    confirm_password: confirmPasswordSchema,
  }),
)

export const loginFormSchema = z.object({
  username: z.email(),
  password: passwordSchema,
}) satisfies z.ZodType<AccessToken>

export const addUserFormSchema = withPasswordConfirmation(
  z.object({
    email: emailSchema,
    full_name: z.string().optional(),
    password: passwordSchema,
    confirm_password: z
      .string()
      .min(1, { message: "Please confirm your password" }),
    is_superuser: z.boolean(),
    is_active: z.boolean(),
  }),
)

export const editUserFormSchema = z
  .object({
    email: emailSchema,
    full_name: z.string().optional(),
    password: z
      .string()
      .min(8, { message: "Password must be at least 8 characters" })
      .optional()
      .or(z.literal("")),
    confirm_password: z.string().optional(),
    is_superuser: z.boolean().optional(),
    is_active: z.boolean().optional(),
  })
  .refine((data) => !data.password || data.password === data.confirm_password, {
    message: "The passwords don't match",
    path: ["confirm_password"],
  })

export const changePasswordFormSchema = withPasswordConfirmation(
  z.object({
    current_password: passwordSchema,
    new_password: passwordSchema,
    confirm_password: confirmPasswordSchema,
  }),
  "new_password",
)

export const resetPasswordFormSchema = withPasswordConfirmation(
  z.object({
    new_password: passwordSchema,
    confirm_password: confirmPasswordSchema,
  }),
  "new_password",
)

export const userInfoFormSchema = z.object({
  full_name: z.string().max(30).optional(),
  email: emailSchema,
})

export const recoverPasswordFormSchema = z.object({
  email: z.email(),
})
