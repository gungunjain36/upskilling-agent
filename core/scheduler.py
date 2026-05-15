"""APScheduler-based cron system for sending concepts and challenges."""

import asyncio
import logging
import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from config import settings
from core.memory import get_schedule_config, is_onboarded, get_user_profile
from core.tracker import log_session

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_send_callback = None  # injected by telegram bot


def set_send_callback(callback):
    """Register a coroutine function that sends a message to Telegram."""
    global _send_callback
    _send_callback = callback


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=settings.timezone)
    return _scheduler


def start_scheduler():
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        _schedule_jobs(scheduler)
        logger.info("Scheduler started")


def _schedule_jobs(scheduler: AsyncIOScheduler):
    scheduler.remove_all_jobs()

    config = get_schedule_config()
    interval_hours = config.get("interval_hours", 3)

    scheduler.add_job(
        _deliver_concept_job,
        trigger=IntervalTrigger(hours=interval_hours),
        id="concept_delivery",
        replace_existing=True,
    )

    # Daily progress nudge at configured time (default 9pm)
    scheduler.add_job(
        _daily_nudge_job,
        trigger="cron",
        hour=21,
        minute=0,
        id="daily_nudge",
        replace_existing=True,
    )

    logger.info(f"Scheduled concept delivery every {interval_hours}h")


def reschedule(interval_hours: int):
    """Reschedule jobs with a new interval."""
    scheduler = get_scheduler()
    scheduler.reschedule_job(
        "concept_delivery",
        trigger=IntervalTrigger(hours=interval_hours),
    )
    logger.info(f"Rescheduled concept delivery to every {interval_hours}h")


async def _deliver_concept_job():
    if not is_onboarded() or _send_callback is None:
        return

    try:
        from agents.orchestrator import cmd_concept
        profile = get_user_profile()
        domains = profile.get("domains", ["dsa"])
        domain = random.choice(domains)
        # save_state=False so cron delivery never overwrites the user's active challenge context
        message = await cmd_concept(f"/concept {domain}", save_state=False)
        await _send_callback(message)
        log_session(domain=domain, topic="scheduled", session_type="concept_delivery", summary="Scheduled concept sent")
    except Exception as e:
        logger.error(f"Concept delivery failed: {e}")


async def _daily_nudge_job():
    if not is_onboarded() or _send_callback is None:
        return

    try:
        from agents.orchestrator import cmd_progress
        progress = await cmd_progress("/progress")
        nudge = f"*Daily check-in*\n\n{progress}\n\nConsistency is what moves the needle. Keep going."
        await _send_callback(nudge)
    except Exception as e:
        logger.error(f"Daily nudge failed: {e}")
