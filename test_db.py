from sqlalchemy import create_engine
import pandas as pd

print("Connecting to database...")
# Using the credentials from your etl_pipeline.py file
engine = create_engine('mysql+pymysql://<username>:<password>@localhost/faker')

print("Executing simple query...")
df1 = pd.read_sql("SELECT COUNT(*) FROM dim_users", engine)
df2 = pd.read_sql("SELECT COUNT(*) FROM dim_products", engine)
df3 = pd.read_sql("SELECT COUNT(*) FROM dim_delivery", engine)
df4 = pd.read_sql("SELECT COUNT(*) FROM fact_order_items", engine)

print("Result:")
print(df1)
print(df2)
print(df3)
print(df4)