from asyncio import TaskGroup

from fastapi import APIRouter
from pydantic import PositiveInt
from sqlalchemy.orm import joinedload

from app.format.element_list import FormatElementList
from app.lib.auth_context import auth_user
from app.lib.options_context import options_context
from app.lib.render_response import render_response
from app.lib.tags_format import tags_format
from app.lib.translation import t
from app.models.db.changeset import Changeset
from app.models.db.changeset_comment import ChangesetComment
from app.models.db.user import User
from app.models.tags_format import TagFormat
from app.queries.changeset_comment_query import ChangesetCommentQuery
from app.queries.changeset_query import ChangesetQuery
from app.queries.element_query import ElementQuery
from app.utils import json_encodes

router = APIRouter(prefix='/api/partial/changeset')


@router.get('/{id:int}')
async def get_changeset(id: PositiveInt):
    with options_context(
        joinedload(Changeset.user).load_only(
            User.id,
            User.display_name,
            User.avatar_type,
            User.avatar_id,
        )
    ):
        changeset = await ChangesetQuery.find_by_id(id)

    if changeset is None:
        return render_response(
            'partial/not_found.jinja2',
            {'type': 'changeset', 'id': id},
        )

    prev_changeset_id: int | None = None
    next_changeset_id: int | None = None

    async def elements_task():
        elements_ = await ElementQuery.get_by_changeset(id, sort_by='id')
        return await FormatElementList.changeset_elements(elements_)

    async def comments_task():
        with options_context(joinedload(ChangesetComment.user)):
            await ChangesetCommentQuery.resolve_comments((changeset,), limit_per_changeset=None, resolve_rich_text=True)

    async def adjacent_ids_task():
        nonlocal prev_changeset_id, next_changeset_id
        changeset_user_id = changeset.user_id
        if changeset_user_id is None:
            return
        t = await ChangesetQuery.get_user_adjacent_ids(id, user_id=changeset_user_id)
        prev_changeset_id, next_changeset_id = t

    async with TaskGroup() as tg:
        elements_t = tg.create_task(elements_task())
        tg.create_task(comments_task())
        tg.create_task(adjacent_ids_task())
        is_subscribed_task = (
            tg.create_task(ChangesetCommentQuery.is_subscribed(id))
            if auth_user() is not None  #
            else None
        )

    elements = elements_t.result()
    is_subscribed = is_subscribed_task.result() if (is_subscribed_task is not None) else False

    tags = tags_format(changeset.tags)
    comment_tag = tags.pop('comment', None)
    if comment_tag is None:
        comment_tag = TagFormat('comment', t('browse.no_comment'))

    return render_response(
        'partial/changeset.jinja2',
        {
            'changeset': changeset,
            'prev_changeset_id': prev_changeset_id,
            'next_changeset_id': next_changeset_id,
            'is_subscribed': is_subscribed,
            'tags': tags.values(),
            'comment_tag': comment_tag,
            'params': json_encodes(
                {
                    'id': id,
                    'bounds': tuple(cb.bounds.bounds for cb in changeset.bounds),
                    'elements': elements,
                }
            ),
        },
    )
