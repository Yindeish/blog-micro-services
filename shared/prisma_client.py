import logging
from typing import Optional
from prisma import Prisma

logger = logging.getLogger("prisma_client")

# Global Prisma ORM client instance
prisma = Prisma(auto_register=True)


async def get_prisma() -> Prisma:
    """Ensure Prisma client is connected and return it."""
    if not prisma.is_connected():
        try:
            await prisma.connect()
            logger.info("Connected to Supabase PostgreSQL via Prisma")
        except Exception as e:
            logger.warning("Prisma connection notice: %s", str(e))
    return prisma


async def disconnect_prisma():
    """Disconnect Prisma client on server shutdown."""
    if prisma.is_connected():
        await prisma.disconnect()
        logger.info("Disconnected from Prisma")
