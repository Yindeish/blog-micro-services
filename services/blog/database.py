"""Prisma ORM database interface for Blog Service."""

from shared.prisma_client import disconnect_prisma, get_prisma, prisma


async def init_db():
    """Initialize Prisma connection to Supabase."""
    await get_prisma()


async def close_db():
    """Disconnect Prisma on service shutdown."""
    await disconnect_prisma()
