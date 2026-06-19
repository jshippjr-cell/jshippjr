"""Model Context Protocol servers for Chordential (Phase B).

These expose Chordential capabilities as MCP tools so an LLM agent (Claude
Desktop/Code, or a future Chordential copilot) can reason over them. The ``mcp``
SDK is an optional dependency, imported only when a server actually runs — the
core app never depends on it.
"""
