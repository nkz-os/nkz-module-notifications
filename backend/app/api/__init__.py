"""Notifications Backend - API Routes (agregación)."""
from fastapi import APIRouter

from app.api import channels, weekly

router = APIRouter(tags=["notifications"])
router.include_router(channels.router)
router.include_router(weekly.router)
