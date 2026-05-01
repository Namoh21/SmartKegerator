from __future__ import annotations

import asyncio
import logging
import subprocess

from fastapi import APIRouter, Depends, Request

from web.api_auth import require_admin

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/system/restart", dependencies=[Depends(require_admin)])
async def restart_services(request: Request):
    """Restart both smartkegerator services.  Admin only."""
    admin = request.state.admin_username if hasattr(request.state, "admin_username") else "api"
    log.warning("Service restart requested via API by %s", admin)

    async def _delayed():
        await asyncio.sleep(1)
        subprocess.run(["systemctl", "--user", "restart", "smartkegerator"], check=False)
        subprocess.run(["systemctl", "--user", "restart", "smartkegerator-web"], check=False)

    asyncio.create_task(_delayed())
    return {"ok": True, "message": "Services restarting in 1 s"}


@router.post("/system/shutdown", dependencies=[Depends(require_admin)])
async def shutdown_services(request: Request):
    """Stop both services without restarting them.  Admin only."""
    admin = request.state.admin_username if hasattr(request.state, "admin_username") else "api"
    log.warning("Service shutdown requested via API by %s", admin)

    async def _delayed():
        await asyncio.sleep(1)
        subprocess.run(["systemctl", "--user", "stop", "smartkegerator-web"], check=False)
        subprocess.run(["systemctl", "--user", "stop", "smartkegerator"], check=False)

    asyncio.create_task(_delayed())
    return {"ok": True, "message": "Services stopping in 1 s"}


@router.post("/system/reboot", dependencies=[Depends(require_admin)])
async def reboot_system(request: Request):
    """Reboot the Raspberry Pi.  Admin only."""
    admin = request.state.admin_username if hasattr(request.state, "admin_username") else "api"
    log.warning("System reboot requested via API by %s", admin)

    async def _delayed():
        await asyncio.sleep(2)
        subprocess.run(["sudo", "reboot"], check=False)

    asyncio.create_task(_delayed())
    return {"ok": True, "message": "System rebooting in 2 s"}
