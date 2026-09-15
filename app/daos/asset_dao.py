"""媒体素材表数据访问对象。"""

from app.daos.db import DB
from app.models import AuthStatus, Clarity, MediaAsset, MediaType, SourceType


def _to_row(asset: MediaAsset) -> tuple:
    return (
        asset.id,
        asset.event_id,
        asset.type.value,
        asset.source_url,
        asset.source_type.value,
        asset.auth_status.value,
        asset.auth_evidence,
        int(asset.license_business),
        asset.attribution,
        asset.clarity.value if asset.clarity is not None else None,
        asset.info_density,
        asset.duration_s,
        asset.fingerprint,
        asset.ingested_at,
    )


def _from_row(row) -> MediaAsset:
    return MediaAsset(
        id=row["id"],
        event_id=row["event_id"],
        type=MediaType(row["type"]),
        source_url=row["source_url"],
        source_type=SourceType(row["source_type"]),
        auth_status=AuthStatus(row["auth_status"]),
        auth_evidence=row["auth_evidence"],
        license_business=bool(row["license_business"]),
        attribution=row["attribution"],
        clarity=Clarity(row["clarity"]) if row["clarity"] is not None else None,
        info_density=row["info_density"],
        duration_s=row["duration_s"],
        fingerprint=row["fingerprint"],
        ingested_at=row["ingested_at"],
    )


class MediaAssetDao:
    """media_assets 表的存取。"""

    def __init__(self, db: DB) -> None:
        self._db = db

    def insert(self, asset: MediaAsset) -> None:
        self._db.connect().execute(
            "INSERT OR REPLACE INTO media_assets"
            " (id, event_id, type, source_url, source_type, auth_status, auth_evidence,"
            "  license_business, attribution, clarity, info_density, duration_s,"
            "  fingerprint, ingested_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _to_row(asset),
        )
        self._db.connect().commit()

    def get(self, asset_id: str) -> MediaAsset | None:
        row = self._db.connect().execute(
            "SELECT * FROM media_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        return _from_row(row) if row else None

    def list_by_event(self, event_id: str) -> list[MediaAsset]:
        rows = self._db.connect().execute(
            "SELECT * FROM media_assets WHERE event_id = ? ORDER BY ingested_at", (event_id,)
        ).fetchall()
        return [_from_row(r) for r in rows]
