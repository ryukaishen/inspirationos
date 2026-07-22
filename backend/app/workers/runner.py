"""RQ worker entrypoint: `python -m app.workers.runner`.

Consumes all three queues in dev; production can run one worker per queue.
"""

import logging

from redis import Redis
from rq import Queue, Worker

from app.config import get_config
from app.queues import ALL_QUEUES
from app.services.privacy.log_filter import install_redacting_filter


def main() -> None:
    logging.basicConfig(level=get_config().log_level)
    install_redacting_filter()
    connection = Redis.from_url(get_config().redis_url)
    queues = [Queue(name, connection=connection) for name in ALL_QUEUES]
    Worker(queues, connection=connection).work()


if __name__ == "__main__":
    main()
