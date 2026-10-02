"""Notifications Backend - API Routes (agregación)."""
from fastapi import APIRouter

from app.api import channels

router = APIRouter(tags=["notifications"])
router.include_router(channels.router)
