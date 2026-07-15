"""RQ queue names. Three queues so slow AI work never blocks an import.

One worker consumes all three in dev; production can scale per-queue.
"""

QUEUE_IMPORTS = "imports"
QUEUE_ENRICHMENT = "enrichment"
QUEUE_AI = "ai"

ALL_QUEUES = (QUEUE_IMPORTS, QUEUE_ENRICHMENT, QUEUE_AI)
