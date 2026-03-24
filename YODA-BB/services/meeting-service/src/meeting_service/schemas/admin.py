"""Pydantic schemas for Admin API (user management)."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class CreateUserRequest(BaseModel):
    user_id: str = Field(..., description="Azure AD object ID")
    display_name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    summary_delivery: str = Field("chat", pattern="^(chat|email|both)$")
    nudge_enabled: bool = True


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = None
    opted_in: bool | None = None
    summary_delivery: str | None = Field(None, pattern="^(chat|email|both)$")
    nudge_enabled: bool | None = None


class UserResponse(BaseModel):
    id: str
    user_id: str
    display_name: str
    email: str
    opted_in: bool
    summary_delivery: str
    nudge_enabled: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
