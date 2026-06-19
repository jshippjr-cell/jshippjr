"""Gmail MCP server (Phase B1) — exposes the inbox as MCP tools.

A thin wrapper over ``web.gmail_client`` so an MCP-capable agent (Claude
Desktop/Code, or Chordential's own agent) can read and triage the alert inbox
interactively: list the unread alert queue, read a message, search, and mark a
message processed. The in-app autonomous triage (``web/triage.py``) shares the
same ``gmail_client`` core, so both doors see identical behavior.

Run it (after ``pip install '.[gmail,mcp]'`` and setting the CHORDENTIAL_GMAIL_*
env vars):

    python -m chordential_oia.mcp.gmail_server      # or: chordential-gmail-mcp

The ``mcp`` SDK is imported lazily in ``main()`` so importing this module never
hard-depends on it.
"""
from __future__ import annotations

from typing import List

from ..web import gmail_client


def _build_server():
    """Construct the FastMCP server. ``mcp`` is imported here so the package
    only needs it at run time, not import time."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("chordential-gmail")

    @server.tool()
    def list_unread(limit: int = 25) -> List[dict]:
        """List unread messages in the Chordential alerts label — the triage
        queue. Returns a list of {id, thread_id}."""
        return gmail_client.list_candidates(limit=limit)

    @server.tool()
    def get_message(message_id: str) -> dict:
        """Read one message as {id, sender, subject, date, body}."""
        return gmail_client.get_message(message_id)

    @server.tool()
    def mark_processed(message_id: str) -> dict:
        """Remove UNREAD from a message so it leaves the triage queue."""
        return {"ok": gmail_client.mark_processed(message_id)}

    @server.tool()
    def status() -> dict:
        """Whether Gmail is configured, the label being watched, and the last
        error (if any)."""
        return {
            "configured": gmail_client.is_configured(),
            "label": gmail_client.label(),
            "last_error": gmail_client.last_error(),
        }

    return server


def main() -> None:
    _build_server().run()


if __name__ == "__main__":
    main()
