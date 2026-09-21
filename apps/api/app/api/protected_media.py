"""Do not serve protected Agent diagnostic files through the media mount."""

from pathlib import PurePosixPath

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class ProtectedMediaFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        if "model-calls" in PurePosixPath(path).parts:
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)
