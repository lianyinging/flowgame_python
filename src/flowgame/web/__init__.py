"""Web search / URL fetch helpers for workflow nodes."""

from src.flowgame.web.fetch import fetch_url_document, fetch_url_documents
from src.flowgame.web.search import search_web

__all__ = ["fetch_url_document", "fetch_url_documents", "search_web"]
