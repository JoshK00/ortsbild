import logging
import time
from collections.abc import Callable
from typing import TypeVar

import botocore.exceptions
import httpx
import psycopg

logger = logging.getLogger("ortsbild.privacy")

T = TypeVar("T")


def is_transient_error(error: Exception) -> bool:
    """True for errors that may go away on their own: network, timeout, server trouble.

    A broken image or a bug in a detector is not transient, trying again fails the same way.
    """
    if isinstance(
        error,
        (
            httpx.TransportError,
            ConnectionError,
            TimeoutError,
            psycopg.OperationalError,  # database not reachable (also a wrong password, retrying is harmless)
            botocore.exceptions.ConnectionError,
            botocore.exceptions.HTTPClientError,
        ),
    ):
        return True
    status = getattr(error, "status", None)  # e.g. the storage API error
    response = getattr(error, "response", None)  # boto3 ClientError
    if status is None and isinstance(response, dict):
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if isinstance(status, str) and status.isdigit():
        status = int(status)
    return isinstance(status, int) and (status >= 500 or status == 429)


def retry(
    call: Callable[[], T],
    what: str,
    attempts: int = 3,
    delay: float = 0.5,
    sleep: Callable[[float], None] | None = None,
) -> T:
    """Run `call`, and repeat it after a transient error (waiting 0.5 s, 1 s, ... between tries).

    Only the error type is logged, never its message, it could contain raw data.
    """
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as error:
            if attempt == attempts or not is_transient_error(error):
                raise
            logger.warning(
                "%s failed (%s), retry %d of %d", what, type(error).__name__, attempt, attempts - 1
            )
            (sleep or time.sleep)(delay * 2 ** (attempt - 1))
    raise AssertionError("unreachable")  # the loop always returns or raises
