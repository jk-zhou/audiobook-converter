import asyncio
import json

from sse_starlette.sse import EventSourceResponse


def sse_endpoint(job_manager):
    async def event_stream():
        q = job_manager.subscribe()
        initial = json.dumps(
            [j.model_dump(mode="json") for j in job_manager.jobs.values()], default=str)
        yield {"event": "job.list", "data": initial}
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield event
                except asyncio.TimeoutError:
                    yield {"event": "keepalive", "data": ""}
        finally:
            job_manager.unsubscribe(q)

    return EventSourceResponse(event_stream())
