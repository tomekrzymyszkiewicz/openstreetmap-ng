from collections.abc import Sequence
from collections.abc import Set as AbstractSet

import anyio
from sqlalchemy import INTEGER, and_, cast, func, null, or_, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.orm import load_only

from db import DB
from limits import FIND_LIMIT
from models.db.element import Element
from models.element_type import ElementType
from models.typed_element_ref import TypedElementRef
from models.versioned_element_ref import VersionedElementRef
from utils import utcnow


class ElementRepository:
    @staticmethod
    async def get_last_typed_id_by_type(type: ElementType) -> int:
        """
        Find the last typed_id for the given type.

        Returns 0 if no elements exist for the given type.
        """

        async with DB() as session:
            stmt = (
                select(Element)
                .options(load_only(Element.typed_id, raiseload=True))
                .where(Element.type == type)
                .order_by(Element.typed_id.desc())
                .limit(1)
            )
            element = await session.scalar(stmt)
            return element.typed_id if element else 0

    @staticmethod
    async def find_one_by_versioned_ref(versioned_ref: VersionedElementRef) -> Element | None:
        """
        Find the element by the versioned ref.
        """

        async with DB() as session:
            stmt = select(Element).where(
                Element.type == versioned_ref.type,
                Element.typed_id == versioned_ref.typed_id,
                Element.version == versioned_ref.version,
            )
            return await session.scalar(stmt)

    @staticmethod
    async def get_many_by_versioned_refs(
        versioned_refs: AbstractSet[VersionedElementRef],
        *,
        limit: int | None = FIND_LIMIT,
    ) -> Sequence[Element]:
        """
        Get elements by the versioned refs.

        This method does not check for the existence of the given elements.
        """

        # small optimization
        if not versioned_refs:
            return ()

        async with DB() as session:
            stmt = select(Element).where(
                or_(
                    and_(
                        Element.type == versioned_ref.type,
                        Element.typed_id == versioned_ref.typed_id,
                        Element.version == versioned_ref.version,
                    )
                    for versioned_ref in versioned_refs
                )
            )

            if limit is not None:
                stmt = stmt.limit(limit)

            return (await session.scalars(stmt)).all()

    @staticmethod
    async def get_many_by_typed_ref(
        typed_ref: TypedElementRef,
        *,
        limit: int | None = FIND_LIMIT,
    ) -> Sequence[Element]:
        """
        Get elements by the typed ref.
        """

        async with DB() as session:
            stmt = (
                select(Element)
                .where(
                    Element.type == typed_ref.type,
                    Element.typed_id == typed_ref.typed_id,
                )
                .order_by(Element.version.desc())
            )

            if limit is not None:
                stmt = stmt.limit(limit)

            return (await session.scalars(stmt)).all()

    @staticmethod
    async def find_one_latest(typed_ref: TypedElementRef | None = None) -> Element | None:
        """
        Find the latest element (if any).

        Optionally by the given typed ref.
        """

        if typed_ref:
            elements = await ElementRepository.get_many_latest_by_typed_refs({typed_ref})
            return elements[0] if elements else None

        async with DB() as session:
            stmt = select(Element).order_by(Element.id.desc()).limit(1)
            return await session.scalar(stmt)

    @staticmethod
    async def get_many_latest_by_typed_refs(
        typed_refs: AbstractSet[TypedElementRef],
        *,
        recurse_ways: bool = False,
        limit: int | None = FIND_LIMIT,
    ) -> Sequence[Element]:
        """
        Get elements by the typed refs.

        Optionally recurse ways to get their nodes.

        This method does not check for the existence of the given elements.
        """

        # small optimization
        if not typed_refs:
            return ()

        # TODO: index
        # TODO: point in time
        point_in_time = utcnow()
        recurse_way_refs = tuple(ref for ref in typed_refs if ref.type == ElementType.way) if recurse_ways else ()

        async with DB() as session:
            stmt = select(Element).where(
                Element.created_at <= point_in_time,
                Element.superseded_at == null() | (Element.superseded_at > point_in_time),
                or_(
                    and_(
                        Element.type == typed_ref.type,
                        Element.typed_id == typed_ref.typed_id,
                    )
                    for typed_ref in typed_refs
                ),
            )

            if recurse_way_refs:
                stmt = stmt.union(
                    select(Element).where(
                        Element.created_at <= point_in_time,
                        Element.superseded_at == null() | (Element.superseded_at > point_in_time),
                        Element.type == ElementType.node,
                        Element.typed_id.in_(
                            select(
                                cast(
                                    func.jsonb_path_query(Element.members, '$[*].typed_id'),
                                    INTEGER,
                                )
                            )
                            .where(
                                Element.created_at <= point_in_time,
                                Element.superseded_at == null() | (Element.superseded_at > point_in_time),
                                Element.type == ElementType.way,
                                Element.typed_id.in_(ref.typed_id for ref in recurse_way_refs),
                            )
                            .subquery()
                        ),
                    )
                )

            if limit is not None:
                # proper limit on union requires subquery
                if recurse_way_refs:
                    stmt = select(Element).select_from(stmt.subquery()).limit(limit)
                else:
                    stmt = stmt.limit(limit)

            return (await session.scalars(stmt)).all()

    @staticmethod
    async def find_many_by_refs(
        refs: AbstractSet[VersionedElementRef | TypedElementRef],
        *,
        limit: int | None = FIND_LIMIT,
    ) -> Sequence[Element | None]:
        """
        Get elements by the ref strings.

        Results are ordered by the given type_strs and don't include duplicates.
        """

        # small optimization
        if not refs:
            return ()

        versioned_refs = []
        typed_refs = []

        for ref in refs:
            if isinstance(ref, VersionedElementRef):
                versioned_refs.append(ref)
            else:
                typed_refs.append(ref)

        ref_map: dict[VersionedElementRef | TypedElementRef, Element] = {}

        async def versioned_task() -> None:
            elements = await ElementRepository.get_many_by_versioned_refs(versioned_refs, limit=limit)
            ref_map.update({element.versioned_ref: element for element in elements})

        async def typed_task() -> None:
            elements = await ElementRepository.get_many_latest_by_typed_refs(typed_refs, limit=limit)
            ref_map.update({element.typed_ref: element for element in elements})

        async with anyio.create_task_group() as tg:
            if versioned_refs:
                tg.start_soon(versioned_task)
            if typed_refs:
                tg.start_soon(typed_task)

        result = []
        result_versioned_ref_set = set()

        for ref in refs:
            element = ref_map.get(ref)

            # deduplicate
            if element:
                versioned_ref = element.versioned_ref
                if versioned_ref in result_versioned_ref_set:
                    continue
                result_versioned_ref_set.add(versioned_ref)

            result.append(element)

        # apply limit
        if limit is not None:
            result = result[:limit]

        return result

    @staticmethod
    async def get_many_parents_by_typed_ref(
        member_ref: TypedElementRef,
        parent_type: ElementType | None = None,
        *,
        after: int | None = None,
        limit: int | None = FIND_LIMIT,
    ) -> Sequence[Element]:
        """
        Get elements that reference the given element.

        This method does not check for the existence of the given element.
        """

        # TODO: index
        # TODO: point in time
        point_in_time = utcnow()

        async with DB() as session:
            stmt = select(Element).where(
                Element.created_at <= point_in_time,
                Element.superseded_at == null() | (Element.superseded_at > point_in_time),
                func.jsonb_path_exists(
                    Element.members,
                    cast(
                        f'$[*] ? (@.type == "{member_ref.type.value}" && @.typed_id == {member_ref.typed_id})',
                        JSONPATH,
                    ),
                ),
            )

            if parent_type is not None:
                stmt = stmt.where(Element.type == parent_type)
            if after is not None:
                stmt = stmt.where(Element.id > after)
            if limit is not None:
                stmt = stmt.limit(limit)

            return (await session.scalars(stmt)).all()
