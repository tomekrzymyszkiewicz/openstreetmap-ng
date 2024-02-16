from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import PositiveInt

from app.format06 import Format06
from app.lib.auth_context import api_user
from app.lib.exceptions_context import raise_for
from app.lib.xmltodict import XMLToDict
from app.models.db.user import User
from app.models.element_ref import ElementRef
from app.models.element_type import ElementType
from app.models.scope import Scope
from app.models.versioned_element_ref import VersionedElementRef
from app.repositories.element_repository import ElementRepository
from app.services.optimistic_diff import OptimisticDiff

# TODO: rate limit
# TODO: dependency for xml parsing?
router = APIRouter()

# read property once for performance
_type_node = ElementType.node
_type_way = ElementType.way
_type_relation = ElementType.relation

# TODO: redaction (403 forbidden), https://wiki.openstreetmap.org/wiki/API_v0.6#Redaction:_POST_/api/0.6/[node|way|relation]/#id/#version/redact?redaction=#redaction_id
# TODO: HttpUrl, ConstrainedUrl


@router.put('/{type}/create', response_class=PlainTextResponse)
async def element_create(
    request: Request,
    type: ElementType,
    _: Annotated[User, api_user(Scope.write_api)],
) -> int:
    xml = (await request.body()).decode()
    data: dict = XMLToDict.parse(xml).get('osm', {}).get(type.value, {})

    if not data:
        raise_for().bad_xml(type.value, xml, f"XML doesn't contain an osm/{type.value} element.")

    # force dynamic id allocation
    data['@id'] = -1

    try:
        element = Format06.decode_element(data, changeset_id=None)
    except Exception as e:
        raise_for().bad_xml(type.value, xml, str(e))

    assigned_ref_map = await OptimisticDiff((element,)).run()
    return assigned_ref_map[element.element_ref][0].id


@router.get('/{type}/{id}')
@router.get('/{type}/{id}.xml')
@router.get('/{type}/{id}.json')
async def element_read_latest(
    type: ElementType,
    id: PositiveInt,
) -> dict:
    ref = ElementRef(type=type, id=id)
    elements = await ElementRepository.get_many_latest_by_element_refs((ref,), limit=1)
    element = elements[0] if elements else None

    if element is None:
        raise_for().element_not_found(ref)
    if not element.visible:
        raise HTTPException(status.HTTP_410_GONE)

    return Format06.encode_element(element)


@router.get('/{type}/{id}/{version}')
@router.get('/{type}/{id}/{version}.xml')
@router.get('/{type}/{id}/{version}.json')
async def element_read_version(
    type: ElementType,
    id: PositiveInt,
    version: PositiveInt,
) -> dict:
    versioned_ref = VersionedElementRef(type=type, id=id, version=version)
    elements = await ElementRepository.get_many_by_versioned_refs((versioned_ref,), limit=1)

    if not elements:
        raise_for().element_not_found(versioned_ref)

    return Format06.encode_element(elements[0])


@router.put('/{type}/{id}', response_class=PlainTextResponse)
async def element_update(
    request: Request,
    type: ElementType,
    id: PositiveInt,
    _: Annotated[User, api_user(Scope.write_api)],
) -> int:
    xml = (await request.body()).decode()
    data: dict = XMLToDict.parse(xml).get('osm', {}).get(type.value, {})

    if not data:
        raise_for().bad_xml(type.value, xml, f"XML doesn't contain an osm/{type.value} element.")

    data['@id'] = id

    try:
        element = Format06.decode_element(data, changeset_id=None)
    except Exception as e:
        raise_for().bad_xml(type.value, xml, str(e))

    await OptimisticDiff((element,)).run()
    return element.version


@router.delete('/{type}/{id}', response_class=PlainTextResponse)
async def element_delete(
    request: Request,
    type: ElementType,
    id: PositiveInt,
    _: Annotated[User, api_user(Scope.write_api)],
) -> int:
    xml = (await request.body()).decode()
    data: dict = XMLToDict.parse(xml).get('osm', {}).get(type.value, {})

    if not data:
        raise_for().bad_xml(type.value, xml, f"XML doesn't contain an osm/{type.value} element.")

    data['@id'] = id
    data['@visible'] = False

    try:
        element = Format06.decode_element(data, changeset_id=None)
    except Exception as e:
        raise_for().bad_xml(type.value, xml, str(e))

    await OptimisticDiff((element,)).run()
    return element.version


@router.get('/{type}/{id}/history')
@router.get('/{type}/{id}/history.xml')
@router.get('/{type}/{id}/history.json')
async def element_history(
    type: ElementType,
    id: PositiveInt,
) -> Sequence[dict]:
    element_ref = ElementRef(type=type, id=id)
    elements = await ElementRepository.get_many_by_element_ref(element_ref, limit=None)

    if not elements:
        raise_for().element_not_found(element_ref)

    return Format06.encode_elements(elements)


@router.get('/{type}s')
@router.get('/{type}s.xml')
@router.get('/{type}s.json')
async def elements_read_many(
    type: ElementType,
    nodes: Annotated[str | None, Query(None)],
    ways: Annotated[str | None, Query(None)],
    relations: Annotated[str | None, Query(None)],
) -> Sequence[dict]:
    if type == _type_node:
        query = nodes
    elif type == _type_way:
        query = ways
    elif type == _type_relation:
        query = relations
    else:
        raise NotImplementedError(f'Unsupported element type {type!r}')

    if not query:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f'The parameter {type.value}s is required, and must be of the form '
            f'{type.value}s=ID[vVER][,ID[vVER][,ID[vVER]...]].',
        )

    try:
        query = (q.strip() for q in query.split(','))
        query = (q for q in query if q)
        query = {
            VersionedElementRef.from_type_str(type, q)
            if 'v' in q  #
            else ElementRef(type=type, id=int(q))
            for q in query
        }
    except ValueError as e:
        # parsing error => element not found
        raise HTTPException(status.HTTP_404_NOT_FOUND) from e

    elements = await ElementRepository.find_many_by_refs(query, limit=None)

    for element in elements:
        if element is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)

    return Format06.encode_elements(elements)


@router.get('/{type}/{id}/relations')
@router.get('/{type}/{id}/relations.xml')
@router.get('/{type}/{id}/relations.json')
async def element_parent_relations(
    type: ElementType,
    id: PositiveInt,
) -> Sequence[dict]:
    element_ref = ElementRef(type=type, id=id)
    elements = await ElementRepository.get_many_parents_by_element_refs(
        (element_ref,),
        parent_type=_type_relation,
        limit=None,
    )
    return Format06.encode_elements(elements)


@router.get('/node/{id}/ways')
@router.get('/node/{id}/ways.xml')
@router.get('/node/{id}/ways.json')
async def element_parent_ways(
    id: PositiveInt,
) -> Sequence[dict]:
    element_ref = ElementRef(type=_type_node, id=id)
    elements = await ElementRepository.get_many_parents_by_element_refs(
        (element_ref,),
        parent_type=_type_way,
        limit=None,
    )
    return Format06.encode_elements(elements)


@router.get('/{type}/{id}/full')
@router.get('/{type}/{id}/full.xml')
@router.get('/{type}/{id}/full.json')
async def element_full(
    type: ElementType.way | ElementType.relation,
    id: PositiveInt,
) -> Sequence[dict]:
    element_ref = ElementRef(type=type, id=id)
    elements = await ElementRepository.get_many_latest_by_element_refs((element_ref,), limit=1)

    if not elements:
        raise_for().element_not_found(element_ref)

    element = elements[0]

    if not element.visible:
        raise HTTPException(status.HTTP_410_GONE)

    members_element_refs = tuple(member.element_ref for member in element.members)
    members_elements = await ElementRepository.get_many_latest_by_element_refs(
        members_element_refs,
        recurse_ways=True,
        limit=None,
    )

    return Format06.encode_elements(members_elements)