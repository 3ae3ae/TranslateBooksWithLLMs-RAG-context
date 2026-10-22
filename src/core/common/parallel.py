import asyncio


async def iter_ordered_concurrent(items, workers, worker, should_interrupt=None):
    """Yield ``(item, result_or_exception)`` in input order while keeping up to
    ``workers`` ``worker(item)`` coroutines in flight at all times.

    With ``workers == 1`` the next item is only launched after the previous one
    has been yielded and processed, so a caller that mutates shared state between
    yields (e.g. previous-translation context) sees it reflected in the next
    call — byte-for-byte identical to a plain sequential loop.

    Args:
        items: ordered work items (e.g. chunk indices).
        workers: maximum number of concurrent ``worker`` coroutines (>= 1).
        worker: coroutine factory called once per item.
        should_interrupt: optional callable; when it returns True, no new work is
            launched (already in-flight items still complete and are yielded).
            The caller is responsible for detecting the interruption itself and
            persisting partial state once iteration ends.

    Breaking out of the ``async for`` (e.g. on a rate-limit result) cancels any
    still-running tasks via the generator's ``finally`` block. Because results
    are yielded in order, every item before the one that triggered the break has
    already been yielded (and committed by the caller).
    """
    limit = max(1, int(workers))
    n = len(items)
    pending_tasks = {}      # asyncio.Task -> position
    results = {}            # position -> result or Exception
    next_launch = 0
    next_yield = 0

    try:
        while next_yield < n:
            # Fill the pool, unless interruption was requested.
            while (next_launch < n
                   and len(pending_tasks) < limit
                   and not (should_interrupt and should_interrupt())):
                pos = next_launch
                task = asyncio.ensure_future(worker(items[pos]))
                pending_tasks[task] = pos
                next_launch += 1

            if not pending_tasks:
                # Nothing in flight and nothing new to launch (interrupted or
                # done): surface whatever contiguous results remain, then stop.
                break

            done, _ = await asyncio.wait(
                list(pending_tasks.keys()), return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                pos = pending_tasks.pop(task)
                try:
                    results[pos] = task.result()
                except Exception as exc:  # noqa: BLE001 - surfaced to caller in order
                    results[pos] = exc

            while next_yield in results:
                yield items[next_yield], results.pop(next_yield)
                next_yield += 1
    finally:
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks.keys(), return_exceptions=True)
