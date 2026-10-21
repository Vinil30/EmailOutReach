import os
import random

# Every automated send waits a random 1-3 minutes, so a run never looks like a fixed-interval blast.
SEND_GAP_MIN_SECONDS = float(os.environ.get("SEND_GAP_MIN_SECONDS", "60"))
SEND_GAP_MAX_SECONDS = float(os.environ.get("SEND_GAP_MAX_SECONDS", "180"))


def random_send_gap() -> float:
    low, high = sorted((SEND_GAP_MIN_SECONDS, SEND_GAP_MAX_SECONDS))
    return random.uniform(low, high)


def average_send_gap() -> float:
    return (SEND_GAP_MIN_SECONDS + SEND_GAP_MAX_SECONDS) / 2
