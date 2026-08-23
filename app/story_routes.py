from typing import Any

from fastapi import APIRouter, Query, Request

from app.story_library import StoryLibrary

router = APIRouter(prefix="/api/v1/stories", tags=["story-library"])


def library_for(request: Request) -> StoryLibrary:
    return StoryLibrary(request.app.state.service)


@router.get(
    "",
    operation_id="listStories",
    summary="List saved master stories",
    include_in_schema=False,
)
def list_stories(request: Request) -> dict[str, Any]:
    return library_for(request).list_stories()


@router.put(
    "/{story_id}/draft",
    operation_id="writeStoryDraft",
    summary="Write or rewrite one story master draft",
    include_in_schema=False,
)
def write_story_draft(
    story_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    body = dict(payload)
    body["story_id"] = story_id
    return library_for(request).put_draft(body)


@router.get(
    "/{story_id}/readback",
    operation_id="getStoryReadbackChunk",
    summary="Read one exact chunk of a saved story draft",
    include_in_schema=False,
)
def get_story_readback_chunk(
    story_id: str,
    request: Request,
    chunk_index: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return library_for(request).readback(story_id, chunk_index)


@router.post(
    "/{story_id}/verify",
    operation_id="verifyStory",
    summary="Verify a story only after complete readback and zero discrepancies",
    include_in_schema=False,
)
def verify_story(
    story_id: str, payload: dict[str, Any], request: Request
) -> dict[str, Any]:
    return library_for(request).verify(story_id, payload)


@router.post(
    "/{story_id}/sessions",
    operation_id="createSessionFromStory",
    summary="Create a fresh session by copying a verified master story",
    include_in_schema=False,
)
def create_session_from_story(story_id: str, request: Request) -> dict[str, Any]:
    return library_for(request).create_session_from_story(story_id)
