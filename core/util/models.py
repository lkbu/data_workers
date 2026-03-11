from pydantic import BaseModel
from typing import Optional

class ConnectionParams(BaseModel):
    """
    Represents connection parameters for data sources.
    """
    mssql: Optional[dict[str, dict[str, str]]] = None
    postgresql: Optional[dict[str, dict[str, str]]] = None

