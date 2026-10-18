import pandas as pd
from sqlalchemy import create_engine, text

# 1. Database Connections
# Replace with your actual database credentials
DB_URI = 'mysql+pymysql://<username>:<password>@localhost/faker'
engine = create_engine(DB_URI)


# ==========================================
# Phase 1: EXTRACT
# ==========================================
print("Extracting data from source...")

users = pd.read_sql("SELECT * FROM users LIMIT 50000", engine)
products = pd.read_sql("SELECT * FROM products LIMIT 50000", engine)
riders = pd.read_sql("SELECT * FROM riders LIMIT 50000", engine)
couriers = pd.read_sql("SELECT * FROM couriers LIMIT 50000", engine)
orders = pd.read_sql("SELECT * FROM orders LIMIT 100000", engine)
orderitems = pd.read_sql("SELECT * FROM orderitems LIMIT 100000", engine)

# ==========================================
# Phase 2: TRANSFORM
# ==========================================
print("Transforming data...")
# --- Transform: User Dimension ---
# Select relevant columns, fix null values, and rename to match DW schema
dim_users = users[['id', 'username', 'firstName', 'lastName', 'city', 'country', 'gender']].copy()
dim_users.rename(columns={'id': 'user_id', 'firstName': 'first_name', 'lastName': 'last_name'}, inplace=True)
dim_users['city'] = dim_users['city'].fillna('Unknown City')
dim_users['country'] = dim_users['country'].fillna('Unknown Country')
dim_users['gender'] = dim_users['gender'].str.strip().str.title()
dim_users['gender'] = dim_users['gender'].fillna('Not Specified')
gender_mapping = {
    'M':'Male',
    'F':'Female'
}

# `Apply the mapping
dim_users['gender'] = dim_users['gender'].replace(gender_mapping)
print(dim_users['gender'].value_counts())
# --- Transform: Product Dimension ---
# Select relevant columns and handle missing descriptions
dim_products = products[['id', 'productCode', 'category', 'name', 'description']].copy()
dim_products.rename(columns={'id': 'product_id', 'productCode': 'product_code'}, inplace=True)
dim_products['description'] = dim_products['description'].fillna('No description available')
dim_products['category'] = dim_products['category'].str.strip().str.title()

# Map the remaining variations and sub-categories to master categories
category_mapping = {
    'Gadgets': 'Electronics',
    'Laptops': 'Electronics',
    'Toy': 'Toys',
    'Bag': 'Bags',
    'Make Up': 'Makeup',
    'Clothes': 'Apparel',
    "Men'S Apparel": 'Apparel' # .title() capitalizes the 's' after the apostrophe
}

# `Apply the mapping
dim_products['category'] = dim_products['category'].replace(category_mapping)
print(dim_products['category'].value_counts())

# --- Transform: Delivery Dimension (Merging Riders & Couriers) ---
# Merge riders and couriers to flatten the hierarchy into a single dimension
dim_delivery = pd.merge(
    riders, 
    couriers, 
    left_on='courierId', 
    right_on='id', 
    suffixes=('_rider', '_courier'),
    how='left'
)
dim_delivery = dim_delivery[['id_rider', 'firstName', 'lastName', 'vehicleType', 'courierId', 'name']].copy()
dim_delivery.rename(columns={
    'id_rider': 'rider_id',
    'firstName': 'rider_first_name',
    'lastName': 'rider_last_name',
    'vehicleType': 'vehicle_type',
    'courierId': 'courier_id',
    'name': 'courier_name'
}, inplace=True)
dim_delivery['courier_name'] = dim_delivery['courier_name'].fillna('Independent/Unknown')

dim_delivery['vehicle_type'] = dim_delivery['vehicle_type'].str.strip().str.title()

# 2. Map synonyms to standard vehicle types
vehicle_mapping = {
    'Motorbike': 'Motorcycle',
    'Bike': 'Bicycle',
    'Trike': 'Tricycle'
}

# 3. Apply the mapping
dim_delivery['vehicle_type'] = dim_delivery['vehicle_type'].replace(vehicle_mapping)

# Optional: Print to verify the cleanup
print(dim_delivery['vehicle_type'].value_counts())

print(orderitems.columns)
# --- Transform: Fact Order Items ---
# 1. Merge orderitems and orders to get order dates and user/rider IDs
fact_df = pd.merge(orderitems, orders, left_on='OrderId', right_on='id', how='inner')

# 2. Merge with products to retrieve the unit price for total_amount calculation
fact_df = pd.merge(fact_df, products[['id', 'price']], left_on='ProductId', right_on='id', how='inner')

# 3. Data Type Casting: Convert VARCHAR dates to actual datetime objects
fact_df['createdAt_x'] = pd.to_datetime(fact_df['createdAt_x'], errors='coerce') # orderitems createdAt
fact_df['deliveryDate'] = pd.to_datetime(fact_df['deliveryDate'], errors='coerce') 

# 4. Aggregations & Calculations: Calculate total_amount
fact_df['unit_price'] = fact_df['price'].astype(float)
fact_df['quantity'] = fact_df['quantity'].fillna(1).astype(int)
fact_df['total_amount'] = fact_df['quantity'] * fact_df['unit_price']

# 5. Select and rename final columns for the fact table
fact_order_items = fact_df[[
    'OrderId', 'orderNumber', 'userId', 'ProductId', 'deliveryRiderId', 
    'createdAt_x', 'deliveryDate', 'quantity', 'unit_price', 'total_amount'
]].copy()

fact_order_items.rename(columns={
    'OrderId': 'order_id',
    'orderNumber': 'order_number',
    'userId': 'user_key',            
    'ProductId': 'product_key',      
    'deliveryRiderId': 'delivery_key',  
    'createdAt_x': 'order_date',
    'deliveryDate': 'delivery_date'
}, inplace=True)

# Drop any rows where critical identifiers are missing
fact_order_items.dropna(subset=['order_id', 'product_key', 'user_key', 'delivery_key'], inplace=True)

# ADD THESE 3 LINES: Enforce referential integrity for the limited dataset
fact_order_items = fact_order_items[fact_order_items['user_key'].isin(dim_users['user_id'])]
fact_order_items = fact_order_items[fact_order_items['product_key'].isin(dim_products['product_id'])]
fact_order_items = fact_order_items[fact_order_items['delivery_key'].isin(dim_delivery['rider_id'])]

# ==========================================
# Phase 3: LOAD
# ==========================================
print("Clearing existing data from the Data Warehouse...")

# Use engine.begin() to automatically commit the transaction
with engine.begin() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
    conn.execute(text("TRUNCATE TABLE fact_order_items;"))
    conn.execute(text("TRUNCATE TABLE dim_delivery;"))
    conn.execute(text("TRUNCATE TABLE dim_products;"))
    conn.execute(text("TRUNCATE TABLE dim_users;"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

print("Database cleared. Loading new data...")

# Add chunksize to all dimension tables
dim_users.to_sql('dim_users', engine, if_exists='append', index=False, chunksize=20000)
print("Loaded dim_users.")

dim_products.to_sql('dim_products', engine, if_exists='append', index=False, chunksize=20000)
print("Loaded dim_products.")

dim_delivery.to_sql('dim_delivery', engine, if_exists='append', index=False, chunksize=20000)
print("Loaded dim_delivery.")

# Fact table with chunksize (and without method='multi')
fact_order_items.to_sql('fact_order_items', engine, if_exists='append', index=False, chunksize=20000)
print("Loaded fact_order_items.")

print("ETL Pipeline completed successfully.")