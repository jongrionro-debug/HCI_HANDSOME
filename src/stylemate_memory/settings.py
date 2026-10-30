"""Explicit local runtime configuration; credentials are read only on opt-in."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Mapping

from .errors import StyleMateError


@dataclass(frozen=True)
class ConsumerSettings:
    db: Path
    catalog_db: Path
    image_root: Path | None = None
    user_id: str = "local-tester"
    provider: str = "fake"
    model: str = "gpt-6-luna"
    port: int = 8766

    @classmethod
    def from_options(cls, options: Any, settings: Mapping[str, str] | None = None) -> ConsumerSettings:
        values = settings if settings is not None else os.environ
        def pick(name: str, env: str, default: Any = None) -> Any:
            value = getattr(options, name, None)
            return value if value is not None else values.get(env, default)
        db, catalog = pick("db", "STYLEMATE_DB"), pick("catalog_db", "STYLEMATE_CATALOG_DB")
        if not db or not catalog:
            raise StyleMateError("invalid_input", "--db/STYLEMATE_DB와 --catalog-db/STYLEMATE_CATALOG_DB가 필요합니다.")
        image = pick("image_root", "STYLEMATE_IMAGE_ROOT")
        provider = pick("provider", "STYLEMATE_PROVIDER", "fake")
        if provider not in ("fake", "openai"):
            raise StyleMateError("invalid_input", "provider는 fake 또는 openai로 지정해 주세요.")
        try:
            port = int(pick("port", "STYLEMATE_PORT", 8766))
            db_path, catalog_path = Path(db).expanduser().resolve(), Path(catalog).expanduser().resolve()
            image_path = Path(image).expanduser().resolve() if image else None
        except (ValueError, TypeError, OSError, RuntimeError):
            raise StyleMateError("invalid_input", "로컬 경로와 포트를 확인해 주세요.") from None
        if not 0 <= port <= 65535 or db_path == catalog_path:
            raise StyleMateError("invalid_input", "서로 다른 DB 경로와 유효한 포트가 필요합니다.")
        # Runtime data is external. In an installed wheel there is no checkout;
        # in a source checkout reject paths through symlinks into the repository.
        checkout = Path(__file__).resolve().parents[2]
        if (checkout / "pyproject.toml").is_file():
            if any(path is not None and path.is_relative_to(checkout) for path in (db_path, catalog_path, image_path)):
                raise StyleMateError("invalid_input", "실행 DB와 이미지 root는 저장소 밖에 두어 주세요.")
        return cls(db_path, catalog_path, image_path, pick("user", "STYLEMATE_USER_ID", "local-tester"),
                   provider, pick("model", "STYLEMATE_OPENAI_MODEL", "gpt-6-luna"), port)

    def gateway(self, *, settings: Mapping[str, str] | None = None, transport: Any = None) -> Any:
        from .llm import create_model_gateway
        if self.provider == "fake":
            return create_model_gateway("fake")
        values = settings if settings is not None else os.environ
        return create_model_gateway("openai", model=self.model, api_key=values.get("OPENAI_API_KEY", ""), transport=transport)

    def open_service(self, *, gateway: Any = None) -> Any:
        from .app import ConsumerService
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.catalog_db.parent.mkdir(parents=True, exist_ok=True)
        return ConsumerService(self.db, self.catalog_db, gateway if gateway is not None else self.gateway(),
                               user_id=self.user_id, image_root=self.image_root)
