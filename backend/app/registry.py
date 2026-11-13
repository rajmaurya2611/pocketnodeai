import asyncio
from dataclasses import dataclass, field
from typing import Any
from fastapi import WebSocket

class WorkerOffline(Exception): pass
class WorkerBusy(Exception): pass
class WorkerTimeout(Exception): pass

@dataclass
class WorkerSession:
    socket: WebSocket
    device_id: str
    model_id: str
    context_window: int
    max_output_tokens: int
    ready: bool = False
    active: bool = False
    pending: dict[str, asyncio.Future] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, obj: dict[str, Any]):
        async with self.send_lock:
            await self.socket.send_json(obj)

class WorkerRegistry:
    def __init__(self):
        self.sessions: dict[str, WorkerSession] = {}

    async def attach(self, session: WorkerSession):
        old = self.sessions.get(session.device_id)
        if old is not None:
            await self.detach(old)
            try: await old.socket.close(code=4001, reason='Replaced by new connection')
            except Exception: pass
        self.sessions[session.device_id] = session

    async def detach(self, session: WorkerSession):
        if self.sessions.get(session.device_id) is session:
            self.sessions.pop(session.device_id, None)
        for future in session.pending.values():
            if not future.done(): future.set_exception(WorkerOffline())
        session.pending.clear()
        session.active = False

    def get(self, device_id: str) -> WorkerSession | None:
        return self.sessions.get(device_id)

    async def infer(self, device_id: str, message: dict, timeout: int):
        session = self.get(device_id)
        if not session or not session.ready: raise WorkerOffline()
        if session.active: raise WorkerBusy()
        session.active = True
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request_id = message['request_id']
        session.pending[request_id] = future
        try:
            await session.send(message)
            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError as e:
                try: await session.send({'type':'cancel_request','request_id':request_id})
                except Exception: pass
                raise WorkerTimeout() from e
        except (ConnectionError, RuntimeError) as e:
            raise WorkerOffline() from e
        finally:
            session.pending.pop(request_id, None)
            session.active = False

    def resolve(self, session: WorkerSession, message: dict):
        request_id = message.get('request_id')
        if not isinstance(request_id, str): return
        future = session.pending.get(request_id)
        if future is not None and not future.done():
            future.set_result(message)
