import streamlit as st
import pandas as pd
from sqlalchemy import create_engine

# --- Configuration & Connection ---
st.set_page_config(page_title="OLAP Data Warehouse Dashboard", layout="wide")

# No caching: Connection is re-initialized on every interaction
def init_connection():
    DB_URI = 'mysql+pymysql://avnadmin:AVNS_nYrrK36yeF2KYpse3G2@mysql-390fd756-virkato71-c11f.b.aivencloud.com:22255/faker'
    return create_engine(DB_URI)

engine = init_connection()


# gets data when executing SQL query and returns it as a pandas Dataframe
# I love pandas dataframe spamming all data, ang sarap DS
def get_data(engine, query, params=None):
    with engine.connect() as connection:
        return pd.read_sql_query(text(query), connection, params=params)



# ============ individual baseline queries ============ 
# gets the distinct order's months, in ascending months
def get_available_months(engine):
    months_query = """
    SELECT DISTINCT EXTRACT(MONTH FROM order_date) as month
    FROM fact_order_items 
    WHERE order_date IS NOT NULL
    ORDER BY month;
    """
    return get_data(engine, months_query)

# gets the unique product categories
def get_available_categories(engine):
    categories_query = """
    SELECT DISTINCT category 
    FROM dim_products 
    ORDER BY CATEGORY;
    """
    return get_data(engine, categories_query)

# roll-up query, return revenue and item totals by geographic and product hierarchy
# They see me rolling, they hating
def get_rollup_data(engine):
    rollup_query = """
    SELECT 
        COALESCE(u.country, 'All Countries') AS country,
        COALESCE(u.city, 'All Cities') AS city,
        COALESCE(p.category, 'All Categories') AS product_category,
        SUM(f.total_amount) AS total_revenue,
        SUM(f.quantity) AS total_items_sold
    FROM fact_order_items f
    JOIN dim_users u ON f.user_key = u.user_id
    JOIN dim_products p ON f.product_key = p.product_id
    GROUP BY u.country, u.city, p.category 
    WITH ROLLUP;
    """
    return get_data(engine, rollup_query)

# pivot query
# returns revenue by product category & normalized user's gender
# `selected_month` is optional. `selected_categories` may be an empty list.
# Filter values are passed as bound parameters, not concatenated into SQL.
def get_pivot_data(engine, selected_month=None, selected_categories=None):
    pivot_query = """
    SELECT 
        p.category AS product_category,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) 
            IN ('male', 'm') THEN f.total_amount ELSE 0 END) AS revenue_male,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) 
            IN ('female', 'f') THEN f.total_amount ELSE 0 END) AS revenue_female,
        SUM(CASE WHEN LOWER(TRIM(u.gender)) 
            NOT IN ('male', 'm', 'female', 'f') OR u.gender IS NULL THEN f.total_amount ELSE 0 END) AS revenue_unspecified,
        SUM(f.total_amount) AS total_revenue
    FROM fact_order_items f
    JOIN dim_users u ON f.user_key = u.user_id
    JOIN dim_products p ON f.product_key = p.product_id
    WHERE 1=1
    """

    params = {}

    # if there's a year, filter for only that year
    if selected_month is not None:
        pivot_query += " AND MONTH(f.order_date) = :selected_month"
        params["selected_month"] = selected_month
    # if selected_categories is present, 
    if selected_categories:
        placeholders = []

        for index, category in enumerate(selected_categories):
            parameter_name = f"category_{index}"
            placeholders.append(f":{parameter_name}")
            params[parameter_name] = category

        pivot_query += f" AND p.category IN ({', '.join(placeholders)})"

    pivot_query += " GROUP BY p.category ORDER BY total_revenue DESC;"
    return get_data(engine, pivot_query, params=params or None)

# ============== Streamlit UI ============== 

def main():
    st.set_page_config(
        page_title="OLAP Data Warehouse Dashboard",
        layout="wide",
    )

    engine = init_connection()

    # Sidebar: Slice & Dice Filters
    st.sidebar.header("OLAP Filters (Slice & Dice)")

    months_df = get_available_months(engine)
    available_months = [None] + months_df["month"].dropna().astype(int).tolist()

    selected_month = st.sidebar.selectbox(
        "Select Month (Slice):",
        available_months,
        format_func=lambda month: (
            "All Months"
            if month is None
            else calendar.month_name[int(month)]
        ),
    )

    categories_df = get_available_categories(engine)
    selected_categories = st.sidebar.multiselect(
        "Select Categories (Dice):",
        categories_df["category"].tolist(),
    )
    # Main dashboard
    st.title("Enterprise Sales & Order OLAP Dashboard (Unoptimized)")

    # Section 1: Roll-up & Drill-down
    st.header("1. Geographic & Product Hierarchy (Roll-up)")
    st.write("Use the toggle below to adjust the granularity of the report.")

    granularity = st.radio(
        "Select Granularity Level:",
        [
            "Country (Roll-up)",
            "City (Drill-down)",
            "Product Category (Drill-down)",
        ],
    )

    rollup_data = get_rollup_data(engine)

    if granularity == "Country (Roll-up)":
        filtered_rollup = rollup_data[
            (rollup_data["city"] == "All Cities")
            & (rollup_data["country"] != "All Countries")
        ]
    elif granularity == "City (Drill-down)":
        filtered_rollup = rollup_data[
            (rollup_data["product_category"] == "All Categories")
            & (rollup_data["city"] != "All Cities")
        ]
    else:
        filtered_rollup = rollup_data[
            rollup_data["product_category"] != "All Categories"
        ]

    st.dataframe(filtered_rollup, use_container_width=True)

    # Section 2: Pivot table
    st.header("2. Revenue Pivot by User Gender")
    st.write(
        "Cross-tabulation comparing revenue by product category and gender."
    )

    pivot_data = get_pivot_data(
        engine,
        selected_month=selected_month,
        selected_categories=selected_categories,
    )
    st.dataframe(pivot_data, use_container_width=True)

    if not pivot_data.empty:
        chart_data = pivot_data.set_index("product_category")[
            ["revenue_male", "revenue_female"]
        ]
        st.bar_chart(chart_data)


if __name__ == "__main__":
    main()
