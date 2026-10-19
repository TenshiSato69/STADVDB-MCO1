import calendar
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

# --- Page Config (Must be the FIRST Streamlit command) ---
st.set_page_config(page_title="OLAP Data Warehouse Dashboard", layout="wide")


# --- Configuration & Connection ---
def init_connection():
    # 1. Read from Streamlit Secrets if deployed on Streamlit Cloud
    if "connections" in st.secrets and "mysql" in st.secrets["connections"]:
        conn = st.secrets["connections"]["mysql"]
        host = conn["host"]
        port = conn.get("port", 4000)
        user = conn["username"]
        password = conn["password"]
        database = conn.get("database", "faker")
    else:
        # 2. Hardcoded fallback for TiDB Cloud
        host = "gateway01.ap-northeast-1.prod.aws.tidbcloud.com"
        port = 4000
        user = "4D7HRxU1YMyqocC.root"
        password = "V8vprts060560f46"
        database = "faker"

    db_uri = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"

    # Required TLS/SSL configuration for TiDB Serverless
    return create_engine(
        db_uri,
        connect_args={"ssl": {"ssl_mode": "PREFERRED"}},
        pool_pre_ping=True
    )


engine = init_connection()


def get_data(query, params=None):
    # Wrap string in text() for SQLAlchemy 2.0 query execution
    return pd.read_sql(text(query), engine, params=params)