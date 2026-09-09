"""Agent documentation served from resources included in installed wheels."""

from importlib.resources import files

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["Documentation"])


class MarkdownResponse(PlainTextResponse):
    media_type = "text/markdown"


def _document(name: str) -> str:
    return files("sense_every_zone.api").joinpath("docs", name).read_text(encoding="utf-8")


@router.get("/agent-docs", response_class=MarkdownResponse)
async def agent_docs():
    """Agent integration guide; available without sensor configuration."""
    return _document("AGENT_GUIDE.md")


@router.get("/agent-docs/api-reference", response_class=MarkdownResponse)
async def api_reference():
    """Complete HTTP API reference in Markdown."""
    return _document("API_REFERENCE.md")


@router.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt(request: Request):
    """Discover agent documentation and the machine-readable OpenAPI schema."""
    # Relative URLs preserve any reverse-proxy root_path without trusting Host.
    root = request.scope.get("root_path", "").rstrip("/")
    return (
        "# Sense Every Zone\n\n"
        "> Read-only environmental monitoring API, STATUS_SPEC v1.2.\n\n"
        "## Documentation\n\n"
        f"- [Agent guide]({root}/agent-docs): discovery and polling workflow.\n"
        f"- [API reference]({root}/agent-docs/api-reference): routes and response semantics.\n"
        f"- [OpenAPI schema]({root}/openapi.json): machine-readable request and response schemas.\n"
    )
