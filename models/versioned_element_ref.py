from typing import Self

from cachetools import cached

from models.element_type import ElementType
from models.typed_element_ref import TypedElementRef


# TODO: expiring cache, never forever on instance
class VersionedElementRef(TypedElementRef):
    version: int

    @property
    def typed_ref(self) -> TypedElementRef:
        return TypedElementRef(
            type=self.type,
            typed_id=self.typed_id,
        )

    def __hash__(self) -> int:
        return hash((super().__hash__(), self.version))

    def __str__(self) -> str:
        """
        Produce a string representation of the versioned element reference.

        >>> VersionedElementRef(ElementType.node, 123, 1)
        'n123v1'
        """

        return f'{self.type.value[0]}{self.typed_id}v{self.version}'

    @classmethod
    def from_str(cls, s: str) -> Self:
        """
        Parse a versioned element reference from a string representation.

        >>> VersionedElementRef.from_str('n123v1')
        VersionedElementRef(type=<ElementType.node: 'node'>, id=123, version=1)
        """

        i = s.rindex('v')
        type, typed_id, version = s[0], int(s[1:i]), int(s[i + 1 :])
        type = ElementType.from_str(type)

        if typed_id == 0:
            raise ValueError('Element id cannot be 0')
        if version <= 0:
            raise ValueError('Element version must be positive')

        return cls(type, typed_id, version)

    @classmethod
    def from_typed_str(cls, type: ElementType, s: str) -> Self:
        """
        Parse a versioned element reference from a string.

        >>> VersionedElementRef.from_typed_str(ElementType.node, '123v1')
        VersionedElementRef(type=<ElementType.node: 'node'>, id=123, version=1)
        """

        i = s.rindex('v')
        typed_id, version = int(s[:i]), int(s[i + 1 :])

        if typed_id == 0:
            raise ValueError('Element id cannot be 0')
        if version <= 0:
            raise ValueError('Element version must be positive')

        return cls(type, typed_id, version)
