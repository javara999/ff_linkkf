import time
import logging
from functools import wraps

logger = logging.getLogger("linkkf")

def linkkf_async_timeit(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        try:
            return await func(*args, **kwargs)
        finally:
            total_time = time.perf_counter() - start_time
            logger.debug("%s%r %r took %.4fs", func.__name__, args, kwargs, total_time)

    return wrapper
