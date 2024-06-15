from typing import Annotated

import cython
from anyio import create_task_group
from fastapi import APIRouter, Path, Query
from sqlalchemy.orm import joinedload
from starlette import status
from starlette.responses import RedirectResponse

from app.lib.auth_context import auth_user, web_user
from app.lib.options_context import options_context
from app.lib.render_response import render_response
from app.limits import DISPLAY_NAME_MAX_LENGTH, TRACE_TAG_MAX_LENGTH
from app.models.db.trace_ import Trace
from app.models.db.user import User
from app.queries.trace_point_query import TracePointQuery
from app.queries.trace_query import TraceQuery
from app.queries.user_query import UserQuery
from app.utils import JSON_ENCODE

router = APIRouter()


@cython.cfunc
async def _get_traces_data(
    *,
    user: User | None,
    tag: str | None,
    after: int | None,
    before: int | None,
) -> dict:
    user_id = user.id if (user is not None) else None

    with options_context(joinedload(Trace.user)):
        traces = await TraceQuery.find_many_recent(
            user_id=user_id,
            tag=tag,
            after=after,
            before=before,
            limit=30,
        )

    new_after: int | None = None
    new_before: int | None = None

    async def resolve_task():
        await TracePointQuery.resolve_image_coords(traces, limit_per_trace=100, resolution=100)

    async def new_after_task():
        nonlocal new_after
        after = traces[0].id
        after_traces = await TraceQuery.find_many_recent(
            user_id=user_id,
            tag=tag,
            after=after,
            limit=1,
        )
        if after_traces:
            new_after = after

    async def new_before_task():
        nonlocal new_before
        before = traces[-1].id
        before_traces = await TraceQuery.find_many_recent(
            user_id=user_id,
            tag=tag,
            before=before,
            limit=1,
        )
        if before_traces:
            new_before = before

    if traces:
        async with create_task_group() as tg:
            tg.start_soon(resolve_task)
            tg.start_soon(new_after_task)
            tg.start_soon(new_before_task)

    base_url = f'/user/{user.display_name}/traces' if (user is not None) else '/traces'
    base_url_notag = base_url
    if tag is not None:
        base_url += f'/tag/{tag}'

    image_coords = JSON_ENCODE(tuple(trace.image_coords for trace in traces)).decode()

    active_tab = 0
    if user is not None:
        user_ = auth_user()
        if (user_ is not None) and user.id == user_.id:
            active_tab = 1
        else:
            active_tab = 2  # TODO: implement

    return {
        'profile': user,
        'active_tab': active_tab,
        'base_url': base_url,
        'base_url_notag': base_url_notag,
        'tag': tag,
        'new_after': new_after,
        'new_before': new_before,
        'traces': traces,
        'image_coords': image_coords,
    }


@router.get('/traces')
async def index(
    after: Annotated[int | None, Query(gt=0)] = None,
    before: Annotated[int | None, Query(gt=0)] = None,
):
    data = await _get_traces_data(user=None, tag=None, after=after, before=before)
    return render_response('traces/index.jinja2', data)


@router.get('/traces/tag/{tag:str}')
async def tagged(
    tag: Annotated[str, Path(min_length=1, max_length=TRACE_TAG_MAX_LENGTH)],
    after: Annotated[int | None, Query(gt=0)] = None,
    before: Annotated[int | None, Query(gt=0)] = None,
):
    data = await _get_traces_data(user=None, tag=tag, after=after, before=before)
    return render_response('traces/index.jinja2', data)


@router.get('/user/{display_name:str}/traces')
async def personal(
    display_name: Annotated[str, Path(min_length=1, max_length=DISPLAY_NAME_MAX_LENGTH)],
    after: Annotated[int | None, Query(gt=0)] = None,
    before: Annotated[int | None, Query(gt=0)] = None,
):
    user = await UserQuery.find_one_by_display_name(display_name)
    data = await _get_traces_data(user=user, tag=None, after=after, before=before)
    return render_response('traces/index.jinja2', data)


@router.get('/user/{display_name:str}/traces/tag/{tag:str}')
async def personal_tagged(
    display_name: Annotated[str, Path(min_length=1, max_length=DISPLAY_NAME_MAX_LENGTH)],
    tag: Annotated[str, Path(min_length=1, max_length=TRACE_TAG_MAX_LENGTH)],
    after: Annotated[int | None, Query(gt=0)] = None,
    before: Annotated[int | None, Query(gt=0)] = None,
):
    user = await UserQuery.find_one_by_display_name(display_name)
    data = await _get_traces_data(user=user, tag=tag, after=after, before=before)
    return render_response('traces/index.jinja2', data)


@router.get('/traces/mine')
async def legacy_mine(
    user: Annotated[User, web_user()],
):
    return RedirectResponse(f'/user/{user.display_name}/traces', status.HTTP_301_MOVED_PERMANENTLY)


@router.get('/traces/mine/tag/{tag:str}')
async def legacy_mine_tagged(
    user: Annotated[User, web_user()],
    tag: Annotated[str, Path(min_length=1, max_length=TRACE_TAG_MAX_LENGTH)],
):
    return RedirectResponse(f'/user/{user.display_name}/traces/tag/{tag}', status.HTTP_301_MOVED_PERMANENTLY)


@router.get('/traces/new')
async def legacy_new():
    return RedirectResponse('/trace/upload', status.HTTP_301_MOVED_PERMANENTLY)
