"""Платформенные geo-операции (скоуп по region_id, без JWT tenant)."""
from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.enums import PlatformAuditAction, RegionStatus
from app.geo_catalog import catalog_by_id, catalog_city_summary
from app.models import (
    District,
    DistrictCreate,
    DistrictPatch,
    GeoConfig,
    GeoConfigPatch,
    GeoImportRequest,
    GeoImportResponse,
    GeoImportCounts,
    Microdistrict,
    MicrodistrictCreate,
    MicrodistrictPatch,
    Street,
    StreetCreate,
    StreetPatch,
)
from app.platform_models import GeoCatalogCityDetail, GeoCatalogCitySummary, GeoProvisionConfig
from db import models as m
from db.codes import uuid_for_code
from db import mappers

if TYPE_CHECKING:
    from db.platform_repository import PlatformStore


class PlatformGeoMixin:
    """Миксин для PlatformStore — CRUD географии и каталог РК."""

    _session: "PlatformStore._session"  # type: ignore[name-defined]

    def _region_row(self, region_id: str) -> m.Region | None:
        return self._session.get(m.Region, region_id)

    def find_region(self, region_id: str):
        from app.platform_models import Region

        row = self._region_row(region_id)
        return self._region(row) if row else None

    def get_region_status(self, region_id: str) -> RegionStatus | None:
        row = self._region_row(region_id)
        return RegionStatus(row.status.value) if row else None

    def _geo_config_dto(self, row: m.Region) -> GeoConfig:
        return GeoConfig(
            hasDistricts=row.has_districts,
            hasMicrodistricts=row.has_microdistricts,
            hasStreets=row.has_streets,
            addressSchema=row.address_schema or "microdistrict,street,house",
            cityType=row.city_type,
            oblast=row.oblast,
            centerLat=row.center_lat,
            centerLng=row.center_lng,
            mapZoom=row.map_zoom,
        )

    def _apply_geo_config(self, row: m.Region, cfg: GeoProvisionConfig | GeoConfigPatch) -> None:
        data = cfg.model_dump(exclude_unset=True)
        mapping = {
            "hasDistricts": "has_districts",
            "hasMicrodistricts": "has_microdistricts",
            "hasStreets": "has_streets",
            "addressSchema": "address_schema",
            "cityType": "city_type",
            "oblast": "oblast",
            "centerLat": "center_lat",
            "centerLng": "center_lng",
            "mapZoom": "map_zoom",
        }
        for key, attr in mapping.items():
            if key in data:
                setattr(row, attr, data[key])

    def _geo_is_complete(self, row: m.Region) -> bool:
        rid = row.id
        if row.has_districts:
            n = self._session.scalar(
                select(func.count()).select_from(m.District).where(m.District.region_id == rid)
            )
            if not n:
                return False
        if row.has_microdistricts:
            n = self._session.scalar(
                select(func.count()).select_from(m.Microdistrict).where(m.Microdistrict.region_id == rid)
            )
            if not n:
                return False
        if row.has_streets:
            n = self._session.scalar(
                select(func.count()).select_from(m.Street).where(m.Street.region_id == rid)
            )
            if not n:
                return False
        return True

    def activate_region(self, region_id: str, *, actor: str):
        from app.platform_models import Region

        row = self._region_row(region_id)
        if row is None:
            raise LookupError("region_not_found")
        if RegionStatus(row.status.value) != RegionStatus.provisioning:
            raise ValueError("not_provisioning")
        if not self._geo_is_complete(row):
            raise ValueError("geo_incomplete")
        from db.enums import RegionStatus as DbRegionStatus

        row.status = DbRegionStatus.active
        self._write_audit(
            region_id=region_id,
            actor=actor,
            action=PlatformAuditAction.region_activated,
            detail="provisioning→active",
        )
        self._session.flush()
        return self._region(row)

    def _next_geo_code(self, region_id: str, prefix: str) -> str:
        if prefix == "d":
            n = self._session.scalar(
                select(func.count()).select_from(m.District).where(m.District.region_id == region_id)
            )
        elif prefix == "m":
            n = self._session.scalar(
                select(func.count()).select_from(m.Microdistrict).where(m.Microdistrict.region_id == region_id)
            )
        else:
            n = self._session.scalar(
                select(func.count()).select_from(m.Street).where(m.Street.region_id == region_id)
            )
        return f"{region_id}-{prefix}{int(n or 0) + 1}"

    def _duplicate_name(self, model, region_id: str, name: str, exclude_id=None) -> None:
        q = select(model).where(
            model.region_id == region_id,
            func.lower(model.name) == name.strip().lower(),
        )
        if exclude_id is not None:
            q = q.where(model.id != exclude_id)
        if self._session.scalar(q):
            raise HTTPException(
                409,
                detail={"message": "Запись с таким названием уже существует", "code": "duplicate_name"},
            )

    def list_region_districts(self, region_id: str) -> list[District]:
        if self._region_row(region_id) is None:
            raise LookupError("region_not_found")
        rows = self._session.scalars(
            select(m.District).where(m.District.region_id == region_id).order_by(m.District.name)
        ).all()
        return [mappers.district(r) for r in rows]

    def create_region_district(self, region_id: str, body: DistrictCreate) -> District:
        if self._region_row(region_id) is None:
            raise LookupError("region_not_found")
        self._duplicate_name(m.District, region_id, body.name)
        code = self._next_geo_code(region_id, "d")
        row = m.District(id=code, region_id=region_id, name=body.name.strip())
        self._session.add(row)
        self._session.flush()
        return mappers.district(row)

    def update_region_district(self, region_id: str, did: str, body: DistrictPatch) -> District:
        row = self._session.get(m.District, did)
        if row is None or row.region_id != region_id:
            raise LookupError("not_found")
        if body.name:
            self._duplicate_name(m.District, region_id, body.name, exclude_id=did)
            row.name = body.name.strip()
        self._session.flush()
        return mappers.district(row)

    def delete_region_district(self, region_id: str, did: str) -> None:
        row = self._session.get(m.District, did)
        if row is None or row.region_id != region_id:
            raise LookupError("not_found")
        md = self._session.scalar(
            select(func.count()).select_from(m.Microdistrict).where(m.Microdistrict.district_id == did)
        )
        st = self._session.scalar(
            select(func.count()).select_from(m.Street).where(m.Street.district_id == did)
        )
        obj = self._session.scalar(
            select(func.count()).select_from(m.CityObject).where(m.CityObject.district_id == did)
        )
        if md or st or obj:
            raise ValueError("in_use")
        self._session.delete(row)
        self._session.flush()

    def list_region_microdistricts(self, region_id: str) -> list[Microdistrict]:
        if self._region_row(region_id) is None:
            raise LookupError("region_not_found")
        rows = self._session.scalars(
            select(m.Microdistrict).where(m.Microdistrict.region_id == region_id).order_by(m.Microdistrict.name)
        ).all()
        return [mappers.microdistrict(r) for r in rows]

    def create_region_microdistrict(self, region_id: str, body: MicrodistrictCreate) -> Microdistrict:
        if self._region_row(region_id) is None:
            raise LookupError("region_not_found")
        self._duplicate_name(m.Microdistrict, region_id, body.name)
        code = self._next_geo_code(region_id, "m")
        row = m.Microdistrict(
            id=code,
            region_id=region_id,
            district_id=body.districtId,
            name=body.name.strip(),
        )
        self._session.add(row)
        self._session.flush()
        return mappers.microdistrict(row)

    def update_region_microdistrict(
        self, region_id: str, mid: str, body: MicrodistrictPatch
    ) -> Microdistrict:
        row = self._session.get(m.Microdistrict, mid)
        if row is None or row.region_id != region_id:
            raise LookupError("not_found")
        if body.name is not None:
            self._duplicate_name(m.Microdistrict, region_id, body.name, exclude_id=mid)
            row.name = body.name.strip()
        if "districtId" in body.model_fields_set:
            row.district_id = body.districtId
        self._session.flush()
        return mappers.microdistrict(row)

    def delete_region_microdistrict(self, region_id: str, mid: str) -> None:
        row = self._session.get(m.Microdistrict, mid)
        if row is None or row.region_id != region_id:
            raise LookupError("not_found")
        st = self._session.scalar(
            select(func.count()).select_from(m.Street).where(m.Street.microdistrict_id == mid)
        )
        obj = self._session.scalar(
            select(func.count()).select_from(m.CityObject).where(m.CityObject.microdistrict_id == mid)
        )
        if st or obj:
            raise ValueError("in_use")
        self._session.delete(row)
        self._session.flush()

    def list_region_streets(self, region_id: str) -> list[Street]:
        if self._region_row(region_id) is None:
            raise LookupError("region_not_found")
        rows = self._session.scalars(
            select(m.Street).where(m.Street.region_id == region_id).order_by(m.Street.name)
        ).all()
        return [mappers.street(r) for r in rows]

    def create_region_street(self, region_id: str, body: StreetCreate) -> Street:
        if self._region_row(region_id) is None:
            raise LookupError("region_not_found")
        code = self._next_geo_code(region_id, "st")
        row = m.Street(
            id=uuid_for_code(code),
            code=code,
            region_id=region_id,
            name=body.name.strip(),
            district_id=body.districtId,
            microdistrict_id=body.microdistrictId,
        )
        self._session.add(row)
        self._session.flush()
        return mappers.street(row)

    def update_region_street(self, region_id: str, sid: str, body: StreetPatch) -> Street:
        uid = uuid_for_code(sid) if not sid.startswith(region_id) else None
        row = None
        if uid:
            row = self._session.get(m.Street, uid)
        if row is None:
            row = self._session.scalar(select(m.Street).where(m.Street.code == sid))
        if row is None or row.region_id != region_id:
            raise LookupError("not_found")
        data = body.model_dump(exclude_unset=True)
        if "name" in data and data["name"] is not None:
            row.name = data["name"].strip()
        if "districtId" in data:
            row.district_id = data["districtId"]
        if "microdistrictId" in data:
            row.microdistrict_id = data["microdistrictId"]
        self._session.flush()
        return mappers.street(row)

    def delete_region_street(self, region_id: str, sid: str) -> None:
        uid = uuid_for_code(sid)
        row = self._session.get(m.Street, uid)
        if row is None:
            row = self._session.scalar(select(m.Street).where(m.Street.code == sid))
        if row is None or row.region_id != region_id:
            raise LookupError("not_found")
        obj = self._session.scalar(
            select(func.count()).select_from(m.CityObject).where(m.CityObject.street_id == row.id)
        )
        if obj:
            raise ValueError("in_use")
        self._session.delete(row)
        self._session.flush()

    def get_region_geo_config(self, region_id: str) -> GeoConfig:
        row = self._region_row(region_id)
        if row is None:
            raise LookupError("region_not_found")
        return self._geo_config_dto(row)

    def patch_region_geo_config(self, region_id: str, body: GeoConfigPatch) -> GeoConfig:
        row = self._region_row(region_id)
        if row is None:
            raise LookupError("region_not_found")
        self._apply_geo_config(row, body)
        self._session.flush()
        return self._geo_config_dto(row)

    def _seed_geo_from_catalog_data(self, region_id: str, city: dict) -> None:
        cfg = city.get("config") or {}
        row = self._region_row(region_id)
        if row is None:
            return
        self._apply_geo_config(row, GeoProvisionConfig(**cfg))
        if city.get("oblast"):
            row.oblast = city["oblast"]
        district_id_by_name: dict[str, str] = {}
        md_id_by_name: dict[str, str] = {}
        for d in city.get("districts") or []:
            dname = d["name"]
            did = self._next_geo_code(region_id, "d")
            self._session.add(m.District(id=did, region_id=region_id, name=dname))
            self._session.flush()
            district_id_by_name[dname.lower()] = did
            for md_name in d.get("microdistricts") or []:
                mid = self._next_geo_code(region_id, "m")
                self._session.add(
                    m.Microdistrict(id=mid, region_id=region_id, district_id=did, name=md_name)
                )
                self._session.flush()
                md_id_by_name[md_name.lower()] = mid
            for st_name in d.get("streets") or []:
                code = self._next_geo_code(region_id, "st")
                self._session.add(
                    m.Street(
                        id=uuid_for_code(code),
                        code=code,
                        region_id=region_id,
                        name=st_name,
                        district_id=did,
                    )
                )
                self._session.flush()

    def seed_geo_from_catalog(self, region_id: str, catalog_id: str) -> None:
        row = self._session.scalar(select(m.GeoCatalogCity).where(m.GeoCatalogCity.id == catalog_id))
        if row is not None:
            city = dict(row.payload)
            city.setdefault("id", row.id)
            city.setdefault("name", row.name)
            city.setdefault("oblast", row.oblast)
        else:
            city = catalog_by_id(catalog_id)
        if city is None:
            raise LookupError("catalog_not_found")
        self._seed_geo_from_catalog_data(region_id, city)

    def clear_region_geo(self, region_id: str) -> None:
        """Стереть всю гео региона — для replace-импорта (streets→mkr→districts)."""
        if self._region_row(region_id) is None:
            raise LookupError("region_not_found")
        self._session.execute(delete(m.Street).where(m.Street.region_id == region_id))
        self._session.execute(delete(m.Microdistrict).where(m.Microdistrict.region_id == region_id))
        self._session.execute(delete(m.District).where(m.District.region_id == region_id))
        self._session.flush()

    def import_region_geo(
        self, region_id: str, body: GeoImportRequest, mode: str = "append"
    ) -> GeoImportResponse:
        if self._region_row(region_id) is None:
            raise LookupError("region_not_found")
        if mode == "replace":
            self.clear_region_geo(region_id)
        added = GeoImportCounts()
        skipped = 0
        district_by_name = {d.name.lower(): d.id for d in self.list_region_districts(region_id)}
        md_by_name = {d.name.lower(): d.id for d in self.list_region_microdistricts(region_id)}

        for item in body.districts:
            key = item.name.strip().lower()
            if key in district_by_name:
                skipped += 1
                continue
            d = self.create_region_district(region_id, DistrictCreate(name=item.name.strip()))
            district_by_name[key] = d.id
            added.districts += 1

        for item in body.microdistricts:
            key = item.name.strip().lower()
            if key in md_by_name:
                skipped += 1
                continue
            did = item.districtId
            if not did and item.districtName:
                did = district_by_name.get(item.districtName.strip().lower())
            md = self.create_region_microdistrict(
                region_id,
                MicrodistrictCreate(name=item.name.strip(), districtId=did),
            )
            md_by_name[key] = md.id
            added.microdistricts += 1

        existing_streets = {s.name.lower() for s in self.list_region_streets(region_id)}
        for item in body.streets:
            key = item.name.strip().lower()
            if key in existing_streets:
                skipped += 1
                continue
            did = item.districtId or (
                district_by_name.get(item.districtName.strip().lower()) if item.districtName else None
            )
            mid = item.microdistrictId or (
                md_by_name.get(item.microdistrictName.strip().lower()) if item.microdistrictName else None
            )
            self.create_region_street(
                region_id,
                StreetCreate(name=item.name.strip(), districtId=did, microdistrictId=mid),
            )
            existing_streets.add(key)
            added.streets += 1

        return GeoImportResponse(added=added, skipped=skipped)

    def list_geo_catalog_cities(self) -> list[GeoCatalogCitySummary]:
        rows = self._session.scalars(select(m.GeoCatalogCity).order_by(m.GeoCatalogCity.name)).all()
        if rows:
            out = []
            for r in rows:
                city = dict(r.payload)
                city["id"] = r.id
                city["name"] = r.name
                city["oblast"] = r.oblast
                out.append(GeoCatalogCitySummary(**catalog_city_summary(city)))
            return out
        from app.geo_catalog import GEO_CATALOG_CITIES

        return [GeoCatalogCitySummary(**catalog_city_summary(c)) for c in GEO_CATALOG_CITIES]

    def get_geo_catalog_city(self, city_id: str) -> GeoCatalogCityDetail:
        row = self._session.get(m.GeoCatalogCity, city_id)
        if row is None:
            city = catalog_by_id(city_id)
            if city is None:
                raise LookupError("catalog_not_found")
        else:
            city = dict(row.payload)
            city["id"] = row.id
            city["name"] = row.name
            city["oblast"] = row.oblast

        cfg = city.get("config") or {}
        districts: list[District] = []
        microdistricts: list[Microdistrict] = []
        streets: list[Street] = []
        for i, d in enumerate(city.get("districts") or [], start=1):
            did = f"preview-d{i}"
            districts.append(District(id=did, name=d["name"]))
            for j, md_name in enumerate(d.get("microdistricts") or [], start=1):
                microdistricts.append(
                    Microdistrict(id=f"preview-m{i}-{j}", districtId=did, name=md_name)
                )
            for j, st_name in enumerate(d.get("streets") or [], start=1):
                streets.append(Street(id=f"preview-st{i}-{j}", name=st_name, districtId=did))

        return GeoCatalogCityDetail(
            id=city["id"],
            name=city["name"],
            oblast=city.get("oblast"),
            config=GeoConfig(
                hasDistricts=cfg.get("hasDistricts", True),
                hasMicrodistricts=cfg.get("hasMicrodistricts", True),
                hasStreets=cfg.get("hasStreets", True),
                addressSchema=cfg.get("addressSchema", "microdistrict,street,house"),
                cityType=cfg.get("cityType"),
                oblast=city.get("oblast"),
                centerLat=cfg.get("centerLat"),
                centerLng=cfg.get("centerLng"),
                mapZoom=cfg.get("mapZoom"),
            ),
            districts=districts,
            microdistricts=microdistricts,
            streets=streets,
        )
