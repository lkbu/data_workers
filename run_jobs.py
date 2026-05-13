from sqlalchemy import create_engine
from core.workers.fx_scraper import upload_fx_data

user = "pguser"
password = "Krakow11!"
host = "192.168.0.94"
port = "5432"
database = "homelab"

db_engine = create_engine(f"postgresql://{user}:{password}@{host}:{port}/{database}")

if __name__ == "__main__":
    upload_fx_data("ECB", db_engine)
    upload_fx_data("NBP", db_engine)
    print("ECB and NBP data uploaded successfully")
