from anyio import Path

from app.config import FILE_DATA_DIR
from app.lib.storage.base import StorageBase


class LocalStorage(StorageBase):
    """
    Local file storage.
    """

    def __init__(self, context: str):
        super().__init__(context)

    async def _get_path(self, key: str) -> Path:
        """
        Get the path to a file by key string.

        >>> await LocalStorage('context')._get_path('file_key.png')
        Path('.../context/file_key.png')
        """

        dir_path = FILE_DATA_DIR / self._context
        await dir_path.mkdir(parents=True, exist_ok=True)

        full_path = dir_path / key
        return full_path

    async def load(self, key: str) -> bytes:
        path = await self._get_path(key)
        return await path.read_bytes()

    async def save(self, data: bytes, suffix: str, *, random: bool = True) -> str:
        key = self._make_key(data, suffix, random)
        path = await self._get_path(key)

        async with await path.open('xb') as f:
            await f.write(data)

        return key

    async def delete(self, key: str) -> None:
        path = await self._get_path(key)
        await path.unlink(missing_ok=True)