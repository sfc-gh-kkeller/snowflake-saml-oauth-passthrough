import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.auth import get_current_user
from ..core.config import settings
from ..models.user import User
from ..models.session import UserFile
from ..services.file_extractor import FileExtractor

router = APIRouter(prefix="/api/files", tags=["files"])
logger = logging.getLogger(__name__)

MAX_SIZE = settings.max_file_size_mb * 1024 * 1024


@router.get("/quota")
async def get_quota(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await db.scalar(
        select(func.count()).select_from(UserFile).where(UserFile.user_id == user.id)
    )
    total_size = await db.scalar(
        select(func.coalesce(func.sum(UserFile.file_size), 0)).where(UserFile.user_id == user.id)
    )
    return {
        "used": count or 0,
        "limit": settings.max_user_files,
        "total_size_bytes": total_size or 0,
        "max_file_size_mb": settings.max_file_size_mb,
        "max_files_per_message": settings.max_files_per_message,
    }


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if len(files) > settings.max_files_per_message:
        raise HTTPException(400, f"Max {settings.max_files_per_message} files per upload")

    current_count = await db.scalar(
        select(func.count()).select_from(UserFile).where(UserFile.user_id == user.id)
    )
    if (current_count or 0) + len(files) > settings.max_user_files:
        raise HTTPException(400, f"File limit reached ({settings.max_user_files}). Delete some files first.")

    results = []
    for upload in files:
        if not FileExtractor.is_allowed(upload.content_type):
            raise HTTPException(400, f"File type not allowed: {upload.content_type}")

        content = await upload.read()
        if len(content) > MAX_SIZE:
            raise HTTPException(400, f"File too large: {upload.filename} ({len(content)} bytes, max {MAX_SIZE})")

        file_id = str(uuid.uuid4())
        file_type = FileExtractor.classify_file(upload.content_type)
        upload_dir = FileExtractor.get_upload_dir(user.id, file_id)

        ext = os.path.splitext(upload.filename)[1] or ""
        stored_name = f"original{ext}"
        file_path = os.path.join(upload_dir, stored_name)

        with open(file_path, "wb") as f:
            f.write(content)

        extracted_pages = None
        if file_type == "pdf":
            extracted_pages = await FileExtractor.extract_pdf_pages(file_path, upload_dir)

        user_file = UserFile(
            id=file_id,
            user_id=user.id,
            original_filename=upload.filename,
            stored_filename=stored_name,
            content_type=upload.content_type,
            file_size=len(content),
            file_type=file_type,
            extracted_pages=extracted_pages,
        )
        db.add(user_file)
        results.append({
            "id": file_id,
            "filename": upload.filename,
            "content_type": upload.content_type,
            "file_size": len(content),
            "file_type": file_type,
            "pages": len(extracted_pages) if extracted_pages else None,
        })

    await db.commit()
    return results


@router.get("")
async def list_files(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserFile)
        .where(UserFile.user_id == user.id)
        .order_by(UserFile.created_at.desc())
    )
    files = result.scalars().all()
    return [
        {
            "id": f.id,
            "filename": f.original_filename,
            "content_type": f.content_type,
            "file_size": f.file_size,
            "file_type": f.file_type,
            "pages": len(f.extracted_pages) if f.extracted_pages else None,
            "created_at": f.created_at.isoformat(),
        }
        for f in files
    ]


@router.get("/{file_id}")
async def get_file_info(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserFile).where(UserFile.id == file_id, UserFile.user_id == user.id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "File not found")
    return {
        "id": f.id,
        "filename": f.original_filename,
        "content_type": f.content_type,
        "file_size": f.file_size,
        "file_type": f.file_type,
        "pages": len(f.extracted_pages) if f.extracted_pages else None,
        "extracted_pages": f.extracted_pages,
        "created_at": f.created_at.isoformat(),
    }


@router.get("/{file_id}/content")
async def get_file_content(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserFile).where(UserFile.id == file_id, UserFile.user_id == user.id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "File not found")
    upload_dir = FileExtractor.get_upload_dir(user.id, file_id)
    file_path = os.path.join(upload_dir, f.stored_filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, "File data missing")
    return FileResponse(file_path, media_type=f.content_type, filename=f.original_filename)


@router.get("/{file_id}/thumbnail")
async def get_file_thumbnail(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserFile).where(UserFile.id == file_id, UserFile.user_id == user.id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "File not found")

    upload_dir = FileExtractor.get_upload_dir(user.id, file_id)

    if f.file_type == "image":
        file_path = os.path.join(upload_dir, f.stored_filename)
        return FileResponse(file_path, media_type=f.content_type)
    elif f.file_type == "pdf" and f.extracted_pages:
        page_path = os.path.join(upload_dir, f.extracted_pages[0])
        return FileResponse(page_path, media_type="image/png")
    raise HTTPException(404, "No thumbnail available")


@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserFile).where(UserFile.id == file_id, UserFile.user_id == user.id)
    )
    f = result.scalar_one_or_none()
    if not f:
        raise HTTPException(404, "File not found")

    upload_dir = FileExtractor.get_upload_dir(user.id, file_id)
    import shutil
    if os.path.exists(upload_dir):
        shutil.rmtree(upload_dir, ignore_errors=True)

    await db.execute(delete(UserFile).where(UserFile.id == file_id))
    await db.commit()
    return {"ok": True}
