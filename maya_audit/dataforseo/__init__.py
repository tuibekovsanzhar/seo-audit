"""DataForSEO access for Maya Audit: credentials, one guarded client, a spend ledger and a cache.

Nothing here runs unless an audit is started with `--dataforseo` or the `dfs` command is used.
Every request goes through `DataForSEOClient.request`, which is where the price check, the
approval limit, the audit's own limit, the daily budget, the ledger and the cache live — there is no second way out.
"""

from .client import (ApprovalRequired, DataForSEOClient, DataForSEOError, EndpointNotAllowed, NoCredentials,
                     NoEstimator, PossiblyBilled)
from .credentials import Credentials, load_credentials
from .ledger import AuditCapReached, BudgetExceeded, Ledger, LedgerCorrupt

__all__ = ["ApprovalRequired", "AuditCapReached", "BudgetExceeded", "Credentials", "DataForSEOClient", "DataForSEOError",
           "EndpointNotAllowed", "Ledger", "LedgerCorrupt", "NoCredentials", "NoEstimator", "PossiblyBilled", "load_credentials"]
