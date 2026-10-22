"""One request budget per translation or refinement, including validation retries."""

from contextvars import ContextVar
from functools import wraps
from inspect import signature

from src import config
from .exceptions import RateLimitError


_current_budget = ContextVar('llm_request_budget', default=None)


class RequestBudget:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0
        self.permanent_failure = False

    @property
    def available(self):
        return not self.permanent_failure and self.used < self.limit


def take_request_attempt():
    budget = _current_budget.get()
    if budget is None:
        return True
    if not budget.available:
        return False
    budget.used += 1
    return True


def stop_request_retries():
    budget = _current_budget.get()
    if budget is not None:
        budget.permanent_failure = True


def check_rate_limit_budget(error):
    budget = _current_budget.get()
    if budget is not None and not budget.available:
        raise error


async def retry_operation(llm_client, operation, *, succeeded=bool, log_callback=None,
                          check_interruption_callback=None):
    """Retry a validated result in place without multiplying provider retries."""
    budget = _current_budget.get()
    nested = budget is not None
    if not nested:
        limit = getattr(llm_client, 'max_attempts', config.MAX_TRANSLATION_ATTEMPTS)
        if not isinstance(limit, int):
            limit = config.MAX_TRANSLATION_ATTEMPTS
        budget = RequestBudget(max(1, limit))
    token = _current_budget.set(budget)
    result = None
    try:
        while budget.available:
            if check_interruption_callback and check_interruption_callback():
                break
            before = budget.used
            if before and log_callback:
                log_callback('llm_retry', f'Retrying this passage ({before + 1}/{budget.limit})')
            try:
                result = await operation()
            except RateLimitError:
                raise
            except Exception:
                if nested or not budget.available or before + 1 >= budget.limit:
                    raise
            finally:
                # Test doubles and failures before HTTP still consume one attempt.
                if budget.used == before:
                    budget.used += 1
            if nested or succeeded(result):
                return result
        return result
    finally:
        _current_budget.reset(token)


def retry_llm_operation(succeeded=bool):
    """Apply the shared budget to request functions with an llm_client argument."""
    def decorate(operation):
        parameters = signature(operation)

        @wraps(operation)
        async def wrapped(*args, **kwargs):
            arguments = parameters.bind(*args, **kwargs).arguments
            client = arguments.get('llm_client')
            if client is None:
                from src.core.llm_client import default_client
                client = default_client
            return await retry_operation(
                client, lambda: operation(*args, **kwargs), succeeded=succeeded,
                log_callback=arguments.get('log_callback'),
            )

        return wrapped
    return decorate
