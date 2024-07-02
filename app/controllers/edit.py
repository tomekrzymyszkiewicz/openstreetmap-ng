from typing import Annotated

from fastapi import APIRouter

from app.config import ID_URL, RAPID_URL
from app.lib.auth_context import auth_user, web_user
from app.lib.render_response import render_response
from app.lib.yarn_lock import ID_VERSION, RAPID_VERSION
from app.models.db.user import User
from app.models.editor import DEFAULT_EDITOR, Editor

router = APIRouter()


@router.get('/edit')
async def edit(
    _: Annotated[User, web_user()],
    editor: Editor | None = None,
):
    if editor is None:
        current_user = auth_user()
        if current_user is not None:
            editor = current_user.editor
        if editor is None:
            editor = DEFAULT_EDITOR

    if editor == Editor.id:
        return render_response('edit/id.jinja2', {'ID_URL': ID_URL})
    elif editor == Editor.rapid:
        return render_response('edit/rapid.jinja2', {'RAPID_URL': RAPID_URL})
    elif editor == Editor.remote:
        return render_response('index.jinja2')
    else:
        raise NotImplementedError(f'Unsupported editor {editor!r}')


@router.get('/id')
async def id(_: Annotated[User, web_user()]):
    return render_response('edit/id_iframe.jinja2', {'ID_VERSION': ID_VERSION})


@router.get('/rapid')
async def rapid(_: Annotated[User, web_user()]):
    return render_response('edit/rapid_iframe.jinja2', {'RAPID_VERSION': RAPID_VERSION})
