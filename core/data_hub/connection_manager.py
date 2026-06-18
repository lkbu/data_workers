import os
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class ConnectionManager:
    """
    A Singleton manager for handling various database and API connections.
    Secrets are read directly from the environment to prevent leaking.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConnectionManager, cls).__new__(cls)
            cls._instance._pg_engine = None
            cls._instance._mssql_engine = None
            cls._instance._sharepoint_client = None
        return cls._instance

    @property
    def postgres_engine(self) -> Engine:
        if self._pg_engine is None:
            user = os.getenv("POSTGRES_USER")
            password = os.getenv("POSTGRES_PASSWORD")
            host = os.getenv("POSTGRES_HOST", "localhost")
            port = os.getenv("POSTGRES_PORT", "5432")
            db = os.getenv("POSTGRES_DB")
            
            if not all([user, password, db]):
                raise ValueError("PostgreSQL connection details are missing in environment variables.")

            # Wrap PostgreSQL using SQLAlchemy
            url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
            self._pg_engine = create_engine(url)
            
        return self._pg_engine

    @property
    def mssql_engine(self) -> Engine:
        if self._mssql_engine is None:
            user = os.getenv("MSSQL_USER")
            password = os.getenv("MSSQL_PASSWORD")
            server = os.getenv("MSSQL_SERVER", "localhost")
            port = os.getenv("MSSQL_PORT", "1433")
            db = os.getenv("MSSQL_DB")
            
            url = f"mssql+pyodbc://{user}:{password}@{server}:{port}/{db}?driver=ODBC+Driver+17+for+SQL+Server"
            self._mssql_engine = create_engine(url)
            
        return self._mssql_engine
        
    @property
    def sharepoint_client(self):
        if self._sharepoint_client is None:
            client_id = os.getenv("SHAREPOINT_CLIENT_ID")
            client_secret = os.getenv("SHAREPOINT_CLIENT_SECRET")
            
            # Placeholder for actual SharePoint client initialization
            self._sharepoint_client = "MockSharePointClient"
            
        return self._sharepoint_client

# Expose a singleton instance
connection_manager = ConnectionManager()
