from datetime import timedelta

import pytest

from app.config import DEFAULT_LANGUAGE
from app.lib.date_utils import utcnow
from app.lib.translation import (
    primary_translation_language,
    render,
    t,
    timeago,
    translation_context,
    translation_languages,
)


def test_translation_context():
    with translation_context(['pl']):
        translation_languages()
    with pytest.raises(LookupError):
        translation_languages()


def test_translation_languages():
    with translation_context(['pl']):
        assert translation_languages() == ('pl', DEFAULT_LANGUAGE)


def test_primary_translation_language():
    with translation_context(['pl']):
        assert primary_translation_language() == 'pl'


def test_translate_local_chapter():
    with translation_context(['pl']):
        assert t('osm_community_index.communities.OSM-PL-chapter.name') == 'OpenStreetMap Polska'


def test_render():
    with translation_context(['en']):
        assert render('test.jinja2').strip() == 'half a minute ago'
    with translation_context(['pl']):
        assert render('test.jinja2').strip() != 'half a minute ago'


@pytest.mark.parametrize(
    ('delta', 'output'),
    [
        (timedelta(seconds=-5), 'less than 1 second ago'),
        (timedelta(seconds=35), 'half a minute ago'),
        (timedelta(days=370), '1 year ago'),
    ],
)
def test_timeago(delta, output):
    with translation_context(['en']):
        now = utcnow() - delta
        assert timeago(now) == output
