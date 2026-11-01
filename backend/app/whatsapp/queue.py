"""The job queue for inbound WhatsApp messages (arq on Redis, ADR 0027).

The webhook stores a message, enqueues its id and answers at once; the worker's
`whatsapp_inbound` job processes it. One job per message id (arq's job id), and when Redis cannot
be reached the message stays pending: the worker's sweep processes it a minute later.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from arq import create_pool
from arq.connections import RedisSettings

from app.observability import get_logger

JOB = "whatsapp_inbound"


class InboundQueue(Protocol):
    async def enqueue(self, message_id: str) -> None: ...


@dataclass
class ArqQueue:
    redis_url: str
    pool: Any = field(default=None, repr=False)  # an ArqRedis, created on first use

    async def enqueue(self, message_id: str) -> None:
        try:
            if self.pool is None:
                self.pool = await create_pool(RedisSettings.from_dsn(self.redis_url), retry=0)
            await self.pool.enqueue_job(JOB, message_id, _job_id=f"{JOB}:{message_id}")
        except Exception as exc:  # the sweep processes it: the webhook must still answer
            get_logger(__name__).warning("whatsapp.enqueue_failed", error=type(exc).__name__)
            self.pool = None
