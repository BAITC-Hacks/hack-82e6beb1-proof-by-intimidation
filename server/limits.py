"""Bounded, process-local protection against repeated paid analysis requests."""

from collections import OrderedDict, deque
from contextlib import contextmanager
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import HTTPException


class AnalysisLimits:
    def __init__(self, per_minute: int = 6, capacity: int = 1024):
        self.per_minute = max(1, min(30, per_minute))
        self.capacity = capacity
        self.sessions = OrderedDict()
        self.lock = Lock()

    @contextmanager
    def slot(self, actor: str):
        timestamp = monotonic()
        with self.lock:
            if actor not in self.sessions:
                if len(self.sessions) >= self.capacity:
                    removable = next((key for key, item in self.sessions.items() if not item["active"]), None)
                    if removable is None:
                        raise HTTPException(429, "All analysis slots are busy. Please try again shortly.", headers={"Retry-After": "5"})
                    del self.sessions[removable]
                self.sessions[actor] = {"active": False, "starts": deque()}
            session = self.sessions[actor]
            self.sessions.move_to_end(actor)
            while session["starts"] and timestamp - session["starts"][0] >= 60:
                session["starts"].popleft()
            if session["active"]:
                raise HTTPException(429, "Analysis is already running in this browser. Wait for it to finish.", headers={"Retry-After": "5"})
            if len(session["starts"]) >= self.per_minute:
                retry = max(1, ceil(60 - (timestamp - session["starts"][0])))
                raise HTTPException(429, "Too many analysis requests. Wait a minute before trying again.", headers={"Retry-After": str(retry)})
            session["active"] = True
            session["starts"].append(timestamp)
        try:
            yield
        finally:
            with self.lock:
                session["active"] = False
