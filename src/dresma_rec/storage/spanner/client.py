"""Cloud Spanner connection manager."""

from functools import lru_cache

from google.cloud import spanner
from google.cloud.spanner_v1.client import Client
from google.cloud.spanner_v1.database import Database
from google.cloud.spanner_v1.instance import Instance

from dresma_rec.config.settings import Settings, get_settings


class SpannerClient:
    """Manages Cloud Spanner client, instance, and database handles.

    The Spanner SDK pools sessions automatically when reads and writes are
    executed through the returned :class:`~google.cloud.spanner_v1.database.Database`.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize Spanner handles from application settings.

        Args:
            settings: GCP project, instance, and database configuration.
        """
        self._settings = settings
        self._client = spanner.Client(project=settings.project_id)
        self._instance = self._client.instance(settings.spanner_instance_id)
        self._database = self._instance.database(settings.spanner_database_id)

    @property
    def settings(self) -> Settings:
        """Settings used to configure this client."""
        return self._settings

    @property
    def client(self) -> Client:
        """Underlying Spanner client for the configured GCP project."""
        return self._client

    @property
    def instance(self) -> Instance:
        """Configured Spanner instance handle."""
        return self._instance

    @property
    def database(self) -> Database:
        """Configured Spanner database handle.

        Repository classes should use this object for snapshots, batches,
        and transactions; session pooling is handled by the SDK.
        """
        return self._database


@lru_cache
def get_spanner_client() -> SpannerClient:
    """Return a cached :class:`SpannerClient` built from application settings."""
    return SpannerClient(get_settings())


def get_spanner_database() -> Database:
    """Return the Spanner database handle for FastAPI dependency injection."""
    return get_spanner_client().database
