"""Do not serve protected Agent diagnostic files through the media mount."""

from pathlib import PurePosixPath
from os import stat_result

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class ProtectedMediaFiles(StaticFiles):
    def lookup_path(self, path: str) -> tuple[str, stat_result | None]:
        full_path, stat = super().lookup_path(path)
        if "model-calls" in PurePosixPath(full_path).parts:
            return "", None
        return full_path, stat

    async def get_response(self, path: str, scope: Scope) -> Response:
        if "model-calls" in PurePosixPath(path).parts:
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)
