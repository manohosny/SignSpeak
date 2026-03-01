import { describe, expect, it } from "vitest"
import {
  emailSchema,
  passwordSchema,
  confirmPasswordSchema,
  fullNameSchema,
  signUpFormSchema,
  loginFormSchema,
  addUserFormSchema,
  editUserFormSchema,
  changePasswordFormSchema,
  resetPasswordFormSchema,
  userInfoFormSchema,
  recoverPasswordFormSchema,
} from "../schemas"

describe("Atomic schemas", () => {
  describe("emailSchema", () => {
    it("accepts valid email", () => {
      expect(emailSchema.safeParse("test@example.com").success).toBe(true)
    })
    it("rejects invalid email", () => {
      const result = emailSchema.safeParse("not-an-email")
      expect(result.success).toBe(false)
    })
  })

  describe("passwordSchema", () => {
    it("accepts valid password", () => {
      expect(passwordSchema.safeParse("password123").success).toBe(true)
    })
    it("accepts exactly 8 characters (boundary)", () => {
      expect(passwordSchema.safeParse("12345678").success).toBe(true)
    })
    it("rejects empty string", () => {
      const result = passwordSchema.safeParse("")
      expect(result.success).toBe(false)
    })
    it("rejects exactly 7 characters (boundary)", () => {
      const result = passwordSchema.safeParse("1234567")
      expect(result.success).toBe(false)
    })
  })

  describe("confirmPasswordSchema", () => {
    it("accepts non-empty string", () => {
      expect(confirmPasswordSchema.safeParse("anything").success).toBe(true)
    })
    it("rejects empty string", () => {
      const result = confirmPasswordSchema.safeParse("")
      expect(result.success).toBe(false)
    })
  })

  describe("fullNameSchema", () => {
    it("accepts non-empty name", () => {
      expect(fullNameSchema.safeParse("John Doe").success).toBe(true)
    })
    it("rejects empty string", () => {
      const result = fullNameSchema.safeParse("")
      expect(result.success).toBe(false)
    })
  })
})

describe("Composed schemas", () => {
  describe("signUpFormSchema", () => {
    const validData = {
      email: "test@example.com",
      full_name: "Test User",
      password: "password123",
      confirm_password: "password123",
    }

    it("accepts valid signup data", () => {
      expect(signUpFormSchema.safeParse(validData).success).toBe(true)
    })

    it("rejects mismatched passwords with correct error path", () => {
      const result = signUpFormSchema.safeParse({
        ...validData,
        confirm_password: "different",
      })
      expect(result.success).toBe(false)
      if (!result.success) {
        const paths = result.error.issues.map((i) => i.path.join("."))
        expect(paths).toContain("confirm_password")
      }
    })
  })

  describe("loginFormSchema", () => {
    it("accepts valid login data", () => {
      const result = loginFormSchema.safeParse({
        username: "test@example.com",
        password: "password123",
      })
      expect(result.success).toBe(true)
    })

    it("rejects invalid email as username", () => {
      const result = loginFormSchema.safeParse({
        username: "not-email",
        password: "password123",
      })
      expect(result.success).toBe(false)
    })
  })

  describe("addUserFormSchema", () => {
    const validData = {
      email: "admin@example.com",
      full_name: "Admin User",
      password: "password123",
      confirm_password: "password123",
      is_superuser: false,
      is_active: true,
    }

    it("accepts valid add user data", () => {
      expect(addUserFormSchema.safeParse(validData).success).toBe(true)
    })

    it("allows optional full_name", () => {
      const result = addUserFormSchema.safeParse({
        ...validData,
        full_name: undefined,
      })
      expect(result.success).toBe(true)
    })
  })

  describe("editUserFormSchema", () => {
    it("accepts valid edit data without password", () => {
      const result = editUserFormSchema.safeParse({
        email: "test@example.com",
        full_name: "Updated",
        password: "",
        is_superuser: true,
        is_active: true,
      })
      expect(result.success).toBe(true)
    })

    it("accepts valid edit data with password", () => {
      const result = editUserFormSchema.safeParse({
        email: "test@example.com",
        password: "newpassword123",
        confirm_password: "newpassword123",
      })
      expect(result.success).toBe(true)
    })

    it("rejects mismatched passwords when password is set", () => {
      const result = editUserFormSchema.safeParse({
        email: "test@example.com",
        password: "newpassword123",
        confirm_password: "different",
      })
      expect(result.success).toBe(false)
    })
  })

  describe("changePasswordFormSchema", () => {
    it("accepts valid change password data", () => {
      const result = changePasswordFormSchema.safeParse({
        current_password: "oldpass123",
        new_password: "newpass1234",
        confirm_password: "newpass1234",
      })
      expect(result.success).toBe(true)
    })

    it("rejects when new password does not match confirmation", () => {
      const result = changePasswordFormSchema.safeParse({
        current_password: "oldpass123",
        new_password: "newpass1234",
        confirm_password: "different",
      })
      expect(result.success).toBe(false)
    })
  })

  describe("resetPasswordFormSchema", () => {
    it("accepts valid reset password data", () => {
      const result = resetPasswordFormSchema.safeParse({
        new_password: "newpass1234",
        confirm_password: "newpass1234",
      })
      expect(result.success).toBe(true)
    })
  })

  describe("userInfoFormSchema", () => {
    it("accepts valid user info", () => {
      const result = userInfoFormSchema.safeParse({
        email: "test@example.com",
        full_name: "Test User",
      })
      expect(result.success).toBe(true)
    })

    it("accepts exactly 30 characters in full_name (boundary)", () => {
      const result = userInfoFormSchema.safeParse({
        email: "test@example.com",
        full_name: "A".repeat(30),
      })
      expect(result.success).toBe(true)
    })

    it("rejects full_name exceeding 30 characters", () => {
      const result = userInfoFormSchema.safeParse({
        email: "test@example.com",
        full_name: "A".repeat(31),
      })
      expect(result.success).toBe(false)
    })

    it("allows optional full_name", () => {
      const result = userInfoFormSchema.safeParse({
        email: "test@example.com",
      })
      expect(result.success).toBe(true)
    })
  })

  describe("recoverPasswordFormSchema", () => {
    it("accepts valid email", () => {
      const result = recoverPasswordFormSchema.safeParse({
        email: "test@example.com",
      })
      expect(result.success).toBe(true)
    })

    it("rejects invalid email", () => {
      const result = recoverPasswordFormSchema.safeParse({
        email: "invalid",
      })
      expect(result.success).toBe(false)
    })
  })
})
