"""ORM model registry — import all models so SQLAlchemy mapper is aware of them."""

from ghg_tool.infrastructure.db.models.audit_log import AuditLog
from ghg_tool.infrastructure.db.models.dlq import Dlq
from ghg_tool.infrastructure.db.models.dq_finding import DqFinding
from ghg_tool.infrastructure.db.models.emission import Emission
from ghg_tool.infrastructure.db.models.factor import FactorCatalog
from ghg_tool.infrastructure.db.models.go_certificate import GoCertificate
from ghg_tool.infrastructure.db.models.gwp_set import GwpSet
from ghg_tool.infrastructure.db.models.ingestion_batch import IngestionBatch
from ghg_tool.infrastructure.db.models.raw_scope1 import RawScope1Ingestion
from ghg_tool.infrastructure.db.models.raw_scope2 import RawScope2Ingestion
from ghg_tool.infrastructure.db.models.raw_scope3 import RawScope3Ingestion
from ghg_tool.infrastructure.db.models.role import Role
from ghg_tool.infrastructure.db.models.site import Site
from ghg_tool.infrastructure.db.models.tenant import Tenant
from ghg_tool.infrastructure.db.models.user import User

__all__ = [
    "AuditLog",
    "Dlq",
    "DqFinding",
    "Emission",
    "FactorCatalog",
    "GoCertificate",
    "GwpSet",
    "IngestionBatch",
    "RawScope1Ingestion",
    "RawScope2Ingestion",
    "RawScope3Ingestion",
    "Role",
    "Site",
    "Tenant",
    "User",
]
