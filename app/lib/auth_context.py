from collections.abc import Sequence
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import Security
from fastapi.security import SecurityScopes

from app.lib.exceptions_context import raise_for
from app.models.db.user import User
from app.models.scope import ExtendedScope, Scope

# TODO: ACL
# TODO: more 0.7 scopes


_context = ContextVar('Auth_context')


@contextmanager
def auth_context(user: User | None, scopes: Sequence[ExtendedScope]):
    """
    Context manager for authenticating the user.
    """

    token = _context.set((user, scopes))
    try:
        yield
    finally:
        _context.reset(token)


def auth_user_scopes() -> tuple[User | None, Sequence[ExtendedScope]]:
    """
    Get the authenticated user and scopes.
    """

    return _context.get()


def auth_user() -> User | None:
    """
    Get the authenticated user.
    """

    return _context.get()[0]


def auth_scopes() -> Sequence[ExtendedScope]:
    """
    Get the authenticated user's scopes.
    """

    return _context.get()[1]


def _get_user(require_scopes: SecurityScopes) -> User:
    """
    Get the authenticated user.

    Raises an exception if the user is not authenticated or does not have the required scopes.
    """

    user, user_scopes = auth_user_scopes()

    # user must be authenticated
    if user is None:
        raise_for().unauthorized(request_basic_auth=True)

    # and have the required scopes
    if missing_scopes := set(require_scopes.scopes).difference(s.value for s in user_scopes):
        raise_for().insufficient_scopes(missing_scopes)

    return user


def api_user(*require_scopes: Scope | ExtendedScope) -> User:
    """
    Dependency for authenticating the api user.
    """

    return Security(_get_user, scopes=tuple(s.value for s in require_scopes))


def web_user() -> User:
    """
    Dependency for authenticating the web user.
    """

    return Security(_get_user, scopes=(ExtendedScope.web_user,))
