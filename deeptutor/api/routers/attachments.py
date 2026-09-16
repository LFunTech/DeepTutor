"""HTTP endpoint for chat attachment downloads / previews.

The chat turn runtime persists every uploaded attachment to the
:class:`~deeptutor.services.storage.AttachmentStore` and records the public
URL on the message. The frontend preview drawer loads files via this
router, which only serves paths the store hands back — every component is
sanitised to defend against directory traversal.

URL shape::

    GET /files/attachments/{session_id}/{attachment_id}/{filename}

配置化 PG 分支以当前身份、对象代际和消息引用授权；session_id 不是 ACL。
对象操作状态/撤回与清理重试同样使用当前 owner 的 PG 权威账本。
"""

from __future__ import annotations

import logging
import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from deeptutor.api.utils.http_headers import content_disposition
from deeptutor.services.storage import (
    LocalDiskAttachmentStore,
    get_attachment_store,
)

logger = logging.getLogger(__name__)

router = APIRouter()


_content_disposition = content_disposition


def _operation_store():
    from deeptutor.persistence.postgres.session_resources import (
        PostgresAttachmentStore,
        PostgresObjectAttachmentStore,
    )

    store = get_attachment_store()
    if not isinstance(store, (PostgresAttachmentStore, PostgresObjectAttachmentStore)):
        raise HTTPException(status_code=501, detail="PostgreSQL resource provider required")
    return store


@router.get("/operations")
async def list_attachment_operations(after: str | None = None, limit: int = 100):
    try:
        return await _operation_store().list_operations(after=after, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Attachment access denied") from None


@router.get("/operations/{object_id}")
async def get_attachment_operation(object_id: str):
    try:
        row = await _operation_store().get_operation(object_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Attachment operation not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Attachment access denied") from None
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment operation not found")
    return row


@router.delete("/operations/{object_id}")
async def withdraw_attachment_operation(object_id: str):
    from fastapi.responses import JSONResponse

    try:
        report = await _operation_store().withdraw_operation(object_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Attachment operation not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Attachment access denied") from None
    return JSONResponse(status_code=202 if report["pending"] else 200, content=report)


@router.post("/cleanup")
async def retry_attachment_cleanup():
    from fastapi.responses import JSONResponse

    report = await _operation_store().cleanup_pending()
    return JSONResponse(status_code=202 if report["pending"] else 200, content=report)


@router.get("/{session_id}/{attachment_id}/{filename:path}")
async def get_attachment(
    session_id: str,
    attachment_id: str,
    filename: str,
):
    """Serve a previously uploaded chat attachment.

    Responds with ``Content-Disposition: inline`` so browsers preview PDFs
    and images directly in an ``<iframe>`` / ``<img>``. For unknown types
    the browser still falls back to download, which is fine for the
    drawer's "Download" button path.
    """
    store = get_attachment_store()
    from deeptutor.persistence.postgres.session_resources import (
        PostgresAttachmentStore,
        PostgresObjectAttachmentStore,
    )

    if isinstance(store, (PostgresAttachmentStore, PostgresObjectAttachmentStore)):
        try:
            data = await store.read_attachment(
                session_id=session_id, attachment_id=attachment_id, filename=filename
            )
        except (FileNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail="Attachment not found") from None
        except PermissionError:
            raise HTTPException(status_code=403, detail="Attachment access denied") from None
        return Response(
            content=data,
            media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
            headers={
                "Content-Disposition": _content_disposition(filename),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    if not isinstance(store, LocalDiskAttachmentStore):
        # Future remote backends should issue a redirect to the signed URL
        # here. Local-disk is the only backend today, so this branch just
        # guards against an unexpected configuration.
        raise HTTPException(status_code=501, detail="Attachment backend not servable")

    target = store.resolve_path(
        session_id=session_id,
        attachment_id=attachment_id,
        filename=filename,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    media_type, _ = mimetypes.guess_type(target.name)
    if not media_type:
        media_type = "application/octet-stream"

    # ``inline`` lets the browser preview the file when possible while still
    # honouring the suggested filename for the drawer's download action.
    headers = {
        "Content-Disposition": _content_disposition(target.name),
        # User-uploaded data; do not let intermediaries cache it.
        "Cache-Control": "private, max-age=0, must-revalidate",
    }
    return FileResponse(path=str(target), media_type=media_type, headers=headers)
