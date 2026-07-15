"""RQ worker entrypoint: `python -m app.workers.runner`.

Consumes all three queues in dev; production can run one worker per queue.
"""

from redis import Redis
from rq import Queue, Worker

from app.config import get_config
from app.queues import ALL_QUEUES


def main() -> None:
    connection = Redis.from_url(get_config().redis_url)
    queues = [Queue(name, connection=connection) for name in ALL_QUEUES]
    Worker(queues, connection=connection).work()


if __name__ == "__main__":
    main()
