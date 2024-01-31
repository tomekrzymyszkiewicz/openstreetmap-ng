from collections.abc import Mapping, Sequence
from typing import Any

import orjson
from fastapi import Response

from app.config import ATTRIBUTION_URL, COPYRIGHT, GENERATOR, LICENSE_URL
from app.lib.format_style_context import format_style
from app.lib.xmltodict import XMLToDict
from app.models.format_style import FormatStyle

# TODO: 0.7 json/xml version
_json_attributes = {
    'version': '0.6',
    'generator': GENERATOR,
    'copyright': COPYRIGHT,
    'attribution': ATTRIBUTION_URL,
    'license': LICENSE_URL,
}

_xml_attributes = {
    '@version': '0.6',
    '@generator': GENERATOR,
    '@copyright': COPYRIGHT,
    '@attribution': ATTRIBUTION_URL,
    '@license': LICENSE_URL,
}

_gpx_attributes = {
    '@version': '1.1',
    '@creator': GENERATOR,
    '@copyright': COPYRIGHT,
    '@attribution': ATTRIBUTION_URL,
    '@license': LICENSE_URL,
    '@xmlns': 'http://www.topografix.com/GPX/1/1',
    '@xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
    '@xsi:schemaLocation': 'http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd',
}

# read property once for performance
_style_json = FormatStyle.json
_style_xml = FormatStyle.xml
_style_rss = FormatStyle.rss
_style_gpx = FormatStyle.gpx


class OSMResponse(Response):
    xml_root = 'osm'

    def render(self, content: Any) -> bytes:
        style = format_style()

        # set content type
        self.media_type = FormatStyle.media_type(style)

        if style == _style_json:
            if isinstance(content, Mapping):
                content |= _json_attributes
            else:
                raise ValueError(f'Invalid json content type {type(content)}')

            return orjson.dumps(content, option=orjson.OPT_NAIVE_UTC | orjson.OPT_UTC_Z)

        elif style == _style_xml:
            if isinstance(content, Mapping):
                content = {self.xml_root: _xml_attributes | content}
            elif isinstance(content, Sequence) and not isinstance(content, str):
                content = {self.xml_root: (*_xml_attributes.items(), *content)}
            else:
                raise ValueError(f'Invalid xml content type {type(content)}')

            return XMLToDict.unparse(content, raw=True)

        elif style == _style_rss:
            if not isinstance(content, str):
                raise ValueError(f'Invalid rss content type {type(content)}')

            return content.encode()

        elif style == _style_gpx:
            if isinstance(content, Mapping):
                content = {self.xml_root: _gpx_attributes | content}
            elif isinstance(content, Sequence) and not isinstance(content, str):
                content = {self.xml_root: (*_gpx_attributes.items(), *content)}
            else:
                raise ValueError(f'Invalid xml content type {type(content)}')

            return XMLToDict.unparse(content, raw=True)

        else:
            raise NotImplementedError(f'Unsupported osm format style {style!r}')


class OSMChangeResponse(OSMResponse):
    xml_root = 'osmChange'


class DiffResultResponse(OSMResponse):
    xml_root = 'diffResult'


class GPXResponse(OSMResponse):
    xml_root = 'gpx'
