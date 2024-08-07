from typing import Annotated

from fastapi import APIRouter, Form, Query, Response
from pydantic import PositiveInt

from app.format import FormatLeaflet
from app.lib.auth_context import web_user
from app.lib.exceptions_context import raise_for
from app.lib.geo_utils import parse_bbox
from app.limits import (
    NOTE_QUERY_AREA_MAX_SIZE,
    NOTE_QUERY_DEFAULT_CLOSED,
    NOTE_QUERY_WEB_LIMIT,
)
from app.models.db.user import User
from app.models.geometry import Latitude, Longitude
from app.models.note_event import NoteEvent
from app.queries.note_comment_query import NoteCommentQuery
from app.queries.note_query import NoteQuery
from app.services.note_service import NoteService

router = APIRouter(prefix='/api/web/note')


# TODO: it is possible to use oauth to create user-authorized note
@router.post('/')
async def create_note(
    lon: Annotated[Longitude, Form()],
    lat: Annotated[Latitude, Form()],
    text: Annotated[str, Form(min_length=1)],
):
    note_id = await NoteService.create(lon, lat, text)
    return {'note_id': note_id}


@router.post('/{note_id:int}/comment')
async def create_note_comment(
    _: Annotated[User, web_user()],
    note_id: PositiveInt,
    event: Annotated[str, Form()],
    text: Annotated[str, Form(min_length=1)] = '',
):
    note_event: NoteEvent
    if event == 'closed':
        note_event = NoteEvent.closed
    elif event == 'reopened':
        note_event = NoteEvent.reopened
    elif event == 'commented':
        note_event = NoteEvent.commented
    else:
        raise NotImplementedError(f'Unsupported event {event!r}')
    await NoteService.comment(note_id, text, note_event)
    return Response()


@router.post('/{note_id:int}/subscribe')
async def subscribe(
    note_id: PositiveInt,
    _: Annotated[User, web_user()],
):
    await NoteService.subscribe(note_id)
    return Response()


@router.post('/{note_id:int}/unsubscribe')
async def unsubscribe(
    note_id: PositiveInt,
    _: Annotated[User, web_user()],
):
    await NoteService.unsubscribe(note_id)
    return Response()


@router.get('/map')
async def get_map(bbox: Annotated[str, Query()]):
    geometry = parse_bbox(bbox)
    if geometry.area > NOTE_QUERY_AREA_MAX_SIZE:
        raise_for().notes_query_area_too_big()
    notes = await NoteQuery.find_many_by_query(
        geometry=geometry,
        max_closed_days=NOTE_QUERY_DEFAULT_CLOSED,
        sort_by='updated_at',
        sort_dir='desc',
        limit=NOTE_QUERY_WEB_LIMIT,
    )
    await NoteCommentQuery.resolve_comments(notes, per_note_sort='asc', per_note_limit=1, resolve_rich_text=False)
    return FormatLeaflet.encode_notes(notes)
