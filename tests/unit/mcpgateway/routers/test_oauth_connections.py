# -*- coding: utf-8 -*-
"""Tests for the caller's own per-user OAuth connections (GET/DELETE /oauth/connections).

Kairos carried patch 4.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.routers import oauth_router as router_module
from mcpgateway.routers.oauth_router import _is_per_user_oauth, list_my_oauth_connections, oauth_router, revoke_my_oauth_connection

USER = {"email": "ana@example.com", "is_admin": False}


def _gateway(gid, grant_type="authorization_code", auth_type="oauth"):
    return SimpleNamespace(id=gid, name=f"gw-{gid}", description=f"desc {gid}", auth_type=auth_type, oauth_config={"grant_type": grant_type, "client_secret": "never-returned"})


def _db_listing(gateways):
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = gateways
    return db


def _db_single(gateway):
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = gateway
    return db


def test_routes_registered():
    routes = {(m, r.path) for r in oauth_router.routes for m in getattr(r, "methods", set())}
    assert ("GET", "/oauth/connections") in routes
    assert ("DELETE", "/oauth/connections/{gateway_id}") in routes


@pytest.mark.parametrize(
    "auth_type,config,expected",
    [
        ("oauth", {"grant_type": "authorization_code"}, True),
        ("oauth", {"grant_type": "client_credentials"}, False),
        ("oauth", None, False),
        ("bearer", {"grant_type": "authorization_code"}, False),
    ],
)
def test_is_per_user_oauth(auth_type, config, expected):
    assert _is_per_user_oauth(SimpleNamespace(auth_type=auth_type, oauth_config=config)) is expected


@pytest.mark.asyncio
async def test_list_only_accessible_per_user_gateways_without_token_values():
    connected, disconnected, shared, forbidden = _gateway("g1"), _gateway("g2"), _gateway("g3", grant_type="client_credentials"), _gateway("g4")
    db = _db_listing([connected, disconnected, shared, forbidden])

    async def enforce(gateway_id, *_args, **_kwargs):
        if gateway_id == "g4":
            raise HTTPException(status_code=403, detail="nope")

    storage = MagicMock()
    storage.get_token_info = AsyncMock(
        side_effect=lambda gid, email: {"status": "active", "scopes": ["Files.Read"], "expires_at": "2026-10-03T00:00:00", "updated_at": "x", "access_token": "secret"} if gid == "g1" else None
    )

    with patch.object(router_module, "_enforce_gateway_access", AsyncMock(side_effect=enforce)), patch.object(router_module, "TokenStorageService", return_value=storage):
        result = await list_my_oauth_connections(request=MagicMock(), current_user=USER, db=db)

    conns = {c["gateway_id"]: c for c in result["connections"]}
    assert set(conns) == {"g1", "g2"}
    assert conns["g1"]["connected"] is True and conns["g1"]["token_status"] == "active" and conns["g1"]["scopes"] == ["Files.Read"]
    assert conns["g2"]["connected"] is False and conns["g2"]["token_status"] is None
    assert "secret" not in repr(result) and "never-returned" not in repr(result)
    storage.get_token_info.assert_any_await("g1", "ana@example.com")


@pytest.mark.asyncio
async def test_revoke_deletes_only_the_callers_token():
    storage = MagicMock()
    storage.revoke_user_tokens = AsyncMock(return_value=True)
    enforce = AsyncMock()
    with patch.object(router_module, "_enforce_gateway_access", enforce), patch.object(router_module, "TokenStorageService", return_value=storage):
        result = await revoke_my_oauth_connection("g1", request=MagicMock(), current_user=USER, db=_db_single(_gateway("g1")))
    assert result == {"gateway_id": "g1", "revoked": True}
    storage.revoke_user_tokens.assert_awaited_once_with("g1", "ana@example.com")
    enforce.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("gateway", [None, _gateway("g1", grant_type="client_credentials")])
async def test_revoke_unknown_or_shared_gateway_is_404(gateway):
    with pytest.raises(HTTPException) as exc:
        await revoke_my_oauth_connection("g1", request=MagicMock(), current_user=USER, db=_db_single(gateway))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_revoke_enforces_gateway_access():
    storage = MagicMock()
    storage.revoke_user_tokens = AsyncMock()
    with (
        patch.object(router_module, "_enforce_gateway_access", AsyncMock(side_effect=HTTPException(status_code=403, detail="nope"))),
        patch.object(router_module, "TokenStorageService", return_value=storage),
    ):
        with pytest.raises(HTTPException) as exc:
            await revoke_my_oauth_connection("g1", request=MagicMock(), current_user=USER, db=_db_single(_gateway("g1")))
    assert exc.value.status_code == 403
    storage.revoke_user_tokens.assert_not_awaited()
