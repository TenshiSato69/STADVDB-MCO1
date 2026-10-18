import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text

# --- Configuration & Connection ---
st.set_page_config(page_title="Optimized OLAP Data Warehouse Dashboard", layout="wide")

# Cache the connection so it doesn't reload on every UI interaction
@st.cache_resource
def init_connection():
    DB_URI = 'mysql+pymysql://<username>:<password>@localhost/faker'
    return create_engine(DB_URI)

engine = init_connection()

# --- Automatic Database Optimization (Secondary Indexes) ---
@st.cache_resource
def setup_indexes():
    with st.spinner("Initializing database and ensuring indexes exist..."):
        indexes_to_create = [
            "CREATE INDEX idx_order_date ON fact_order_items(order_date);",
            "CREATE INDEX idx_product_category ON dim_products(category);",
            "CREATE INDEX idx_user_location ON dim_users(country, city);"
        ]
        
        with engine.connect() as conn:
            for idx_query in indexes_to_create:
                try:
                    conn.execute(text(idx_query))
                    conn.commit()
                except Exception:
                    pass

setup_indexes()

# Helper function to fetch data safely using caching
@st.cache_data
def get_data(query, params=None):
    return pd.read_sql(query, engine, params=params)

# --- Sidebar: Slice & Dice Filters ---
st.sidebar.header("OLAP Filters (Slice & Dice)")

years_query = "SELECT DISTINCT YEAR(order_date) as year FROM fact_order_items ORDER BY year;"
years_df = get_data(years_query)
selected_year = st.sidebar.selectbox("Select Year (Slice):", [None] + years_df['year'].tolist())

categories_query = "SELECT DISTINCT category FROM dim_products;"
categories_df = get_data(categories_query)
selected_categories = st.sidebar.multiselect("Select Categories (Dice):", categories_df['category'].tolist())

# --- Main Dashboard ---
st.title("Enterprise Sales & Delivery OLAP Dashboard (Optimized)")

# --- Section 1: Roll-up & Drill-down ---
st.header("1. Geographic & Product Hierarchy (Roll-up)")
st.write("Use the toggle below to adjust the granularity of the report.")

granularity = st.radio("Select Granularity Level:", ["Country (Roll-up)", "City (Drill-down)", "Product Category (Drill-down)"])

# OPTIMIZED: Query Reformulation using STRAIGHT_JOIN to dictate execution order
rollup_query = """
    SELECT 
        COALESCE(u.country, 'All Countries') AS country,
        COALESCE(u.city, 'All Cities') AS city,
        COALESCE(p.category, 'All Categories') AS product_category,
        SUM(f.total_amount) AS total_revenue,
        SUM(f.quantity) AS total_items_sold
    FROM fact_order_items f
    STRAIGHT_JOIN dim_users u ON f.user_key = u.user_id
    STRAIGHT_JOIN dim_products p ON f.product_key = p.product_id
    GROUP BY u.country, u.city, p.category WITH ROLLUP;
"""
rollup_data = get_data(rollup_query)

if granularity == "Country (Roll-up)":
    filtered_rollup = rollup_data[(rollup_data['city'] == 'All Cities') & (rollup_data['country'] != 'All Countries')]
elif granularity == "City (Drill-down)":
    filtered_rollup = rollup_data[(rollup_data['product_category'] == 'All Categories') & (rollup_data['city'] != 'All Cities')]
else:
    filtered_rollup = rollup_data[(rollup_data['product_category'] != 'All Categories')]

st.dataframe(filtered_rollup, use_container_width=True)

# --- Section 2: Pivot Table ---
st.header("2. Revenue Pivot by User Gender")
st.write("Cross-tabulation comparing revenue by product category and gender.")

# OPTIMIZED: Query Reformulation using Common Table Expressions (CTEs)
pivot_query = """
    WITH FilteredFacts AS (
        SELECT product_key, user_key, total_amount
        FROM fact_order_items
        WHERE 1=1 {fact_filters}
    ),
    FilteredProducts AS (
        SELECT product_id, category
        FROM dim_products
        WHERE 1=1 {prod_filters}
    )
    SELECT 
        p.category AS product_category,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) IN ('male', 'm') THEN f.total_amount ELSE 0 END) AS revenue_male,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) IN ('female', 'f') THEN f.total_amount ELSE 0 END) AS revenue_female,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) NOT IN ('male', 'm', 'female', 'f') OR u.gender IS NULL THEN f.total_amount ELSE 0 END) AS revenue_unspecified,
        SUM(f.total_amount) AS total_revenue
    FROM FilteredFacts f
    JOIN dim_users u ON f.user_key = u.user_id
    JOIN FilteredProducts p ON f.product_key = p.product_id
    GROUP BY p.category 
    ORDER BY total_revenue DESC;
"""

fact_filters = ""
prod_filters = ""
params = []

if selected_year:
    fact_filters = " AND YEAR(order_date) = %s"
    params.append(selected_year)

if selected_categories:
    format_strings = ','.join(['%s'] * len(selected_categories))
    prod_filters = f" AND category IN ({format_strings})"
    params.extend(selected_categories)

final_pivot_query = pivot_query.format(fact_filters=fact_filters, prod_filters=prod_filters)

pivot_data = get_data(final_pivot_query, params=tuple(params) if params else None)
st.dataframe(pivot_data, use_container_width=True)

if not pivot_data.empty:
    chart_data = pivot_data.set_index("product_category")[["revenue_male", "revenue_female"]]
    st.bar_chart(chart_data)