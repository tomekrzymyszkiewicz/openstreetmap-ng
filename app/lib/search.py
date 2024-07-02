import logging
from collections.abc import Iterable, Sequence

import cython
import numpy as np
from shapely import MultiPolygon, Point, Polygon, STRtree

from app.lib.geo_utils import parse_bbox
from app.limits import SEARCH_LOCAL_AREA_LIMIT, SEARCH_LOCAL_MAX_ITERATIONS, SEARCH_LOCAL_RATIO
from app.models.db.element import Element
from app.models.db.element_member import ElementMember
from app.models.element_type import ElementType
from app.models.search_result import SearchResult

if cython.compiled:
    from cython.cimports.libc.math import ceil, log2
else:
    from math import ceil, log2


class Search:
    @staticmethod
    def get_search_bounds(bbox: str, local_only: bool) -> list[tuple[str, Polygon | MultiPolygon | None]]:
        """
        Get search bounds from a bbox string.

        Returns a list of (leaflet, shapely) bounds.
        """
        search_local_area_limit: cython.double = SEARCH_LOCAL_AREA_LIMIT
        search_local_max_iterations: cython.int = SEARCH_LOCAL_MAX_ITERATIONS

        parts = bbox.strip().split(',', maxsplit=3)
        minx: cython.double = float(parts[0])
        miny: cython.double = float(parts[1])
        maxx: cython.double = float(parts[2])
        maxy: cython.double = float(parts[3])
        bbox_center_x: cython.double = (minx + maxx) / 2
        bbox_center_y: cython.double = (miny + maxy) / 2
        bbox_width_2: cython.double = (maxx - minx) / 2
        bbox_height_2: cython.double = (maxy - miny) / 2
        bbox_area: cython.double = (maxx - minx) * (maxy - miny)

        local_iterations: cython.int = int(ceil(log2(search_local_area_limit / bbox_area)))
        if local_iterations > search_local_max_iterations:
            local_iterations = search_local_max_iterations
        if local_only:
            local_iterations = 1
        logging.debug('Searching area of %d with %d local iterations', bbox_area, local_iterations)

        result = []
        i: cython.int
        for i in range(local_iterations):
            bounds_width_2: cython.double = bbox_width_2 * (2**i)
            bounds_height_2: cython.double = bbox_height_2 * (2**i)
            bounds_minx = bbox_center_x - bounds_width_2
            bounds_miny = bbox_center_y - bounds_height_2
            bounds_maxx = bbox_center_x + bounds_width_2
            bounds_maxy = bbox_center_y + bounds_height_2

            leaflet_bounds = f'{bounds_minx:.7f},{bounds_miny:.7f},{bounds_maxx:.7f},{bounds_maxy:.7f}'
            shapely_bounds = parse_bbox(leaflet_bounds)
            result.append((leaflet_bounds, shapely_bounds))

        if not local_only:
            # append global search bounds
            result.append(('', None))
        return result

    @staticmethod
    def best_results_index(task_results: Sequence[Sequence[SearchResult]]) -> int:
        """
        Determine the best results index.
        """
        # local_only mode
        if len(task_results) == 1:
            return 0

        if _should_use_global_search(task_results):
            # global search
            logging.debug('Search performed using global mode')
            return -1

        logging.debug('Search performed using local mode')
        max_local_results = len(task_results[-2])
        threshold = max_local_results * SEARCH_LOCAL_RATIO

        # zoom out until there are enough local results
        for i, results in enumerate(task_results[:-2]):
            if len(results) >= threshold:
                return i
        return -2

    @staticmethod
    def improve_point_accuracy(
        results: Iterable[SearchResult],
        members_map: dict[tuple[ElementType, int], Element],
    ) -> None:
        """
        Improve accuracy of points by analyzing relations members.
        """
        for result in results:
            element = result.element
            if element.type != 'relation':
                continue

            members = element.members
            if members is None:
                raise ValueError('Element is missing members')

            label_node: ElementMember | None = None
            for member in members:
                if member.type != 'node':
                    continue
                if member.role == 'admin_centre':
                    label_node = member
                    break
                if label_node is None:
                    label_node = member

            if label_node is not None:
                node = members_map[('node', label_node.id)]
                result.point = node.point

    @staticmethod
    def remove_overlapping_points(results: Iterable[SearchResult]) -> None:
        """
        Remove overlapping points, preserving most important results.
        """
        relations = tuple(result for result in results if result.element.type == 'relation')
        if len(relations) <= 1:
            return

        geoms = tuple(result.point for result in relations)
        tree = STRtree(geoms)
        nearby_all: np.ndarray = tree.query(geoms, 'dwithin', 0.001).T
        nearby_all = np.unique(nearby_all, axis=0)
        nearby_all = nearby_all[nearby_all[:, 0] < nearby_all[:, 1]]
        nearby_all = np.sort(nearby_all, axis=1)
        for i1, i2 in nearby_all:
            if relations[i1].point is None:
                continue
            relations[i2].point = None

    @staticmethod
    def deduplicate_similar_results(results: Iterable[SearchResult]) -> tuple[SearchResult, ...]:
        """
        Deduplicate similar results.
        """
        # Deduplicate by type and id
        seen_type_id: set[tuple[ElementType, int]] = set()
        dedup1: list[SearchResult] = []
        geoms: list[Point] = []
        for result in results:
            element = result.element
            type_id = (element.type, element.id)
            if type_id in seen_type_id:
                continue
            seen_type_id.add(type_id)
            dedup1.append(result)
            geoms.append(result.point)

        if len(dedup1) <= 1:
            return tuple(dedup1)

        # Deduplicate by location and name
        tree = STRtree(geoms)
        nearby_all: np.ndarray = tree.query(geoms, 'dwithin', 0.001).T
        nearby_all = np.unique(nearby_all, axis=0)
        nearby_all = nearby_all[nearby_all[:, 0] < nearby_all[:, 1]]
        nearby_all = np.sort(nearby_all, axis=1)
        mask = np.ones(len(geoms), dtype=bool)
        for i1, i2 in nearby_all:
            if not mask[i1]:
                continue
            name1 = dedup1[i1].display_name
            name2 = dedup1[i2].display_name
            if name1 != name2:
                continue
            mask[i2] = False

        return tuple(dedup1[i] for i in np.nonzero(mask)[0])


@cython.cfunc
def _should_use_global_search(task_results: Sequence[Sequence[SearchResult]]) -> cython.char:
    """
    Determine whether to use global search or local search.

    Global search is used when there are no relevant local results.
    """
    local_results = task_results[:-1]
    global_results = task_results[-1]
    if not global_results or not any(local_results):
        return True

    # https://nominatim.org/release-docs/latest/customize/Ranking/
    return global_results[0].rank <= 16
