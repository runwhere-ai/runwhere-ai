"""HTTP routes: /login (GET, POST), /logout (POST).

Delegates the actual logic to the configured AuthProvider.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.console.auth import AuthProvider
from src.webui.deps import get_auth_provider


router = APIRouter(tags=["auth"])


@router.get("/login")
async def login_get(request: Request, auth: AuthProvider = Depends(get_auth_provider)):
    return await auth.begin_login(request)


@router.post("/login")
async def login_post(request: Request, auth: AuthProvider = Depends(get_auth_provider)):
    return await auth.complete_login(request)


@router.post("/logout")
async def logout(request: Request, auth: AuthProvider = Depends(get_auth_provider)):
    return await auth.logout(request)
