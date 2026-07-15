"""Base settings for Firnline services.

Precedence (highest → lowest):

    1. init kwargs
    2. process environment variables
    3. ``.env`` files
    4. **TOML config file** (one table per service, keyed by ``env_prefix``
       lower-cased without trailing underscore, e.g. ``INGESTD_`` → ``[ingestd]``)
    5. secrets directory
    6. hard-coded field defaults

The TOML file path is ``os.environ.get("FIRNLINE_CONFIG_FILE",
"/etc/firnline/config.toml")``, resolved at instantiation time so tests can
monkeypatch the env var.

Subclasses should set their own ``env_prefix`` via
``model_config = SettingsConfigDict(env_prefix="...")``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings
from pydantic_settings.sources import InitSettingsSource, TomlConfigSettingsSource

if TYPE_CHECKING:
    from pydantic_settings.sources import PydanticBaseSettingsSource


class FirnlineTomlConfigSettingsSource(TomlConfigSettingsSource):
    """Reads a service-specific TOML table from the Firnline config file.

    The file path is resolved from the ``FIRNLINE_CONFIG_FILE`` env var
    (default ``/etc/firnline/config.toml``) at instantiation time, not
    at import time.

    The source reads the top-level table whose name matches the service's
    ``env_prefix`` lower-cased and with trailing underscore removed
    (e.g. ``INGESTD_`` → ``ingestd``).  If the prefix is empty, the file
    does not exist, or the table is missing, the source returns ``{}``.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:  # noqa: D107
        self.toml_file_path = os.environ.get("FIRNLINE_CONFIG_FILE", "/etc/firnline/config.toml")
        self.toml_data = self._read_files(self.toml_file_path, deep_merge=False)

        env_prefix: str = settings_cls.model_config.get("env_prefix", "")
        if env_prefix:
            table = env_prefix.lower().rstrip("_")
            filtered = self.toml_data.get(table, {})
        else:
            filtered = {}

        # Re-initialise InitSettingsSource directly with the filtered dict
        # so field-alias normalization happens only on the relevant table.
        InitSettingsSource.__init__(self, settings_cls, filtered)


class FirnlineBaseSettings(BaseSettings):
    """Base class for all Firnline service settings.

    Injects a TOML config-file layer between ``.env`` files and secrets.
    See the module docstring for the full precedence table and naming
    convention.
    """

    @classmethod
    def settings_customise_sources(  # noqa: D102
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            FirnlineTomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


class TdbSettings(FirnlineBaseSettings):
    """TerminusDB connection settings – meant to be subclassed."""

    # Intentionally no env_prefix here; subclasses set their own.
    tdb_url: str = "http://localhost:6363"
    tdb_org: str = "admin"
    tdb_db: str
    tdb_branch: str = "main"
    tdb_user: str = "admin"
    tdb_password: str
