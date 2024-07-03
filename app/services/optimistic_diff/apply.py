import logging
from asyncio import TaskGroup
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime

from sqlalchemy import and_, null, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db import db_commit
from app.exceptions.optimistic_diff_error import OptimisticDiffError
from app.lib.date_utils import utcnow
from app.models.db.changeset import Changeset
from app.models.db.element import Element
from app.models.db.element_member import ElementMember
from app.models.element_ref import ElementRef, VersionedElementRef
from app.models.element_type import ElementType
from app.queries.changeset_query import ChangesetQuery
from app.queries.element_query import ElementQuery
from app.services.optimistic_diff.prepare import ElementStateEntry, OptimisticDiffPrepare

# allow reads but prevent writes
_lock_table_sql = text(
    f'LOCK TABLE "{Changeset.__tablename__}","{Element.__tablename__}","{ElementMember.__tablename__}" IN EXCLUSIVE MODE'
)


class OptimisticDiffApply:
    async def apply(self, prepare: OptimisticDiffPrepare) -> dict[ElementRef, list[Element]]:
        """
        Apply the optimistic diff update.

        Returns a dict, mapping original element refs to the new elements.
        """
        assigned_ref_map: dict[ElementRef, list[Element]] = defaultdict(list)
        for element, element_ref in prepare.apply_elements:
            assigned_ref_map[element_ref].append(element)
        if not assigned_ref_map:
            return {}

        changeset = prepare.changeset
        if changeset is None:
            raise AssertionError('Changeset must be set')

        async with db_commit() as session, TaskGroup() as tg:
            # obtain exclusive lock on the tables
            await session.execute(_lock_table_sql)

            # check if the element_state is valid
            tg.create_task(_check_elements_latest(prepare.element_state))

            # check if the elements have no new references
            if prepare.reference_check_element_refs:
                tg.create_task(
                    _check_elements_unreferenced(
                        prepare.reference_check_element_refs,
                        prepare.at_sequence_id,
                    )
                )

            now = utcnow()
            tg.create_task(_update_changeset(changeset, now, session))
            tg.create_task(_update_elements(prepare.apply_elements, now, session))

        return assigned_ref_map


async def _check_elements_latest(element_state: dict[ElementRef, ElementStateEntry]) -> None:
    """
    Check if the elements are the current version.

    Raises OptimisticDiffError if they are not.
    """
    versioned_refs = tuple(
        VersionedElementRef(ref.type, ref.id, entry.remote.version)
        for ref, entry in element_state.items()
        if entry.remote is not None
    )
    if not await ElementQuery.check_is_latest(versioned_refs):
        raise OptimisticDiffError('Element is outdated')


async def _check_elements_unreferenced(element_refs: Collection[ElementRef], after_sequence_id: int) -> None:
    """
    Check if the elements are currently unreferenced.

    Raises OptimisticDiffError if they are.
    """
    if not await ElementQuery.check_is_unreferenced(element_refs, after_sequence_id):
        raise OptimisticDiffError(f'Element is referenced after {after_sequence_id}')


async def _update_changeset(changeset: Changeset, now: datetime, session: AsyncSession) -> None:
    """
    Update the changeset table.

    Raises OptimisticDiffError if the changeset was modified in the meantime.
    """
    changeset_id = changeset.id
    changeset_id_updated_map = await ChangesetQuery.get_updated_at_by_ids((changeset_id,))
    updated_at = changeset_id_updated_map[changeset_id]
    if changeset.updated_at != updated_at:
        raise OptimisticDiffError(f'Changeset {changeset_id} is outdated ({changeset.updated_at} != {updated_at})')

    changeset.updated_at = now
    changeset.auto_close_on_size(now)
    session.add(changeset)


async def _update_elements(
    elements: Collection[tuple[Element, ElementRef]],
    now: datetime,
    session: AsyncSession,
) -> None:
    """
    Update the element table by creating new revisions.
    """
    async with TaskGroup() as tg:
        current_sequence_task = tg.create_task(ElementQuery.get_current_sequence_id())
        current_id_task = tg.create_task(ElementQuery.get_current_ids())

    current_sequence_id = current_sequence_task.result()
    current_id_map = current_id_task.result()
    update_type_ids: dict[ElementType, list[int]] = defaultdict(list)
    insert_elements: list[Element] = []
    insert_members: list[ElementMember] = []
    prev_map: dict[ElementRef, Element] = {}
    assigned_id_map: dict[ElementRef, int] = {}

    # process elements
    for sequence_id, (element, element_ref) in enumerate(elements, current_sequence_id + 1):
        # assign sequence_id
        element.sequence_id = sequence_id
        element.created_at = now

        # assign next_sequence_id
        prev = prev_map.get(element_ref)
        if prev is not None:
            prev.next_sequence_id = sequence_id  # update locally
        elif element.version > 1:
            update_type_ids[element.type].append(element.id)  # update remotely
        prev_map[element_ref] = element

        # assign id
        if element.id < 0:
            assigned_id = assigned_id_map.get(element_ref)
            if assigned_id is None:
                assigned_id = current_id_map[element.type] + 1
                assigned_id_map[element_ref] = current_id_map[element.type] = assigned_id
            element.id = assigned_id

    # process members
    for element_t in elements:
        element = element_t[0]
        insert_elements.append(element)
        element_members = element.members
        if not element_members:
            continue

        insert_members.extend(element_members)
        sequence_id = element.sequence_id

        for member in element_members:
            # assign sequence_id
            member.sequence_id = sequence_id

            # assign id
            if member.id < 0:
                member_ref = ElementRef(member.type, member.id)
                member.id = assigned_id_map[member_ref]

    await _update_elements_db(current_sequence_id, update_type_ids, insert_elements, insert_members, session)


async def _update_elements_db(
    current_sequence_id: int,
    update_type_ids: Mapping[ElementType, Iterable[int]],
    insert_elements: Collection[Element],
    insert_members: Collection[ElementMember],
    session: AsyncSession,
) -> None:
    """
    Update the element table by creating new revisions - push prepared data to the database.
    """
    logging.info('Inserting %d elements and %d members', len(insert_elements), len(insert_members))
    session.add_all(insert_elements)
    session.add_all(insert_members)
    await session.flush()

    if update_type_ids:
        E = aliased(Element)  # noqa: N806
        stmt = (
            update(Element)
            .where(
                Element.sequence_id <= current_sequence_id,
                Element.next_sequence_id == null(),
                or_(
                    *(
                        and_(
                            Element.type == type,
                            Element.id.in_(text(','.join(map(str, ids)))),
                        )
                        for type, ids in update_type_ids.items()
                    ),
                ),
            )
            .values(
                {
                    Element.next_sequence_id: select(E.sequence_id)
                    .where(
                        E.type == Element.type,
                        E.id == Element.id,
                        E.version > Element.version,
                    )
                    .order_by(E.version.asc())
                    .limit(1)
                    .scalar_subquery()
                }
            )
            .inline()
        )
        await session.execute(stmt)
