from __future__ import annotations
from typing import Any

def identity_boundary_inventory() -> list[dict[str,Any]]:
    return [
      {'boundary':'REQUEST_TRUSTED_IDENTITY','same_identity':'ALLOW','body_conflict':'DENY','thread_conflict':'DENY','credential_validation':'UPSTREAM_OUT_OF_SCOPE'},
      {'boundary':'LONG_TERM_MEMORY','same_tenant_same_user':'ALLOW','same_owner_new_session':'ALLOW','same_tenant_other_user':'DENY','cross_tenant':'DENY','anonymous':'DENY'},
      {'boundary':'ARTIFACT','exact_identity':'ALLOW','same_user_new_session':'DENY','same_user_new_conversation':'DENY','cross_user':'DENY','cross_tenant':'DENY'},
      {'boundary':'STRUCTURED_SELF_READ','same_owner_with_permission':'ALLOW','same_owner_missing_permission':'DENY','same_tenant_other_user':'DENY','cross_tenant':'DENY','identity_missing':'DENY'},
      {'boundary':'RETRIEVAL','anonymous_public_global':'ALLOW','anonymous_nonpublic':'DENY','same_tenant':'ALLOW','cross_tenant_without_permission':'DENY','cross_tenant_with_tenant_cross_read':'ALLOW'},
    ]
