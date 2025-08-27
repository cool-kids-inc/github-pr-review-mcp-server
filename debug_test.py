#!/usr/bin/env python3

import asyncio
from unittest.mock import patch

import httpx

from mcp_server import fetch_pr_comments


async def test_debug():
    # Simulate infinite next pages with 2 comments per page;
    # expect stop at MAX_PAGES (50)
    class DummyResp:
        def __init__(self, status_code=200):
            self.status_code = status_code
            self.headers = {"Link": '<https://next>; rel="next"'}

        def json(self):
            return [{"id": 1}, {"id": 2}]

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("error", request=None, response=None)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            self.calls += 1
            print(f"DEBUG: Call #{self.calls}", flush=True)
            if self.calls > 60:  # Safety stop
                print("DEBUG: Emergency stop to prevent infinite loop", flush=True)
                resp = DummyResp(200)
                resp.headers = {}  # No next link
                return resp
            return DummyResp(200)

    fake = FakeClient()
    
    with patch("mcp_server.httpx.AsyncClient", lambda *a, **k: fake):
        comments = await fetch_pr_comments("o", "r", 1)
    
    print(f"Comments: {len(comments) if comments else 'None'}")
    print(f"Calls made: {fake.calls}")

if __name__ == "__main__":
    asyncio.run(test_debug())