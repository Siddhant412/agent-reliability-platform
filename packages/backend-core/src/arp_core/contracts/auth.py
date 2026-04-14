from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from arp_core.contracts.tenant import MembershipRead


class AuthSessionRead(BaseModel):
    user_id: UUID
    memberships: list[MembershipRead]
