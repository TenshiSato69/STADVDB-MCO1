import calendar
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

# --- Page Config (Must be the FIRST Streamlit command) ---
st.set_page_config(page_title="OLAP Data Warehouse Dashboard", layout="wide")


# --- Configuration & Connection ---
@st.cache_resource
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
        # 2. TiDB Cloud fallback
        host = "gateway01.ap-northeast-1.prod.aws.tidbcloud.com"
        port = 4000
        user = "4D7HRxU1YMyqocC.root"
        password = "1GqVW010xoLcUp0T"
        database = "faker"

    db_uri = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    
    # Required TLS/SSL parameters for TiDB Serverless
    return create_engine(
        db_uri,
        connect_args={"ssl": {"ssl_mode": "PREFERRED"}},
        pool_pre_ping=True
    )


def get_data(engine, query, params=None):
    with engine.connect() as connection:
        return pd.read_sql_query(text(query), connection, params=params)


# ============ Individual Baseline Queries ============


def get_available_months(engine):
    months_query = """
    SELECT DISTINCT EXTRACT(MONTH FROM order_date) as month
    FROM fact_order_items 
    WHERE order_date IS NOT NULL
    ORDER BY month;
    """
    return get_data(engine, months_query)


def get_available_categories(engine):
    categories_query = """
    SELECT DISTINCT category 
    FROM dim_products 
    ORDER BY category;
    """
    return get_data(engine, categories_query)


def get_available_countries(engine):
    countries_query = """
    SELECT DISTINCT country 
    FROM dim_users 
    WHERE country IS NOT NULL AND country != 'Unknown Country'
    ORDER BY country;
    """
    return get_data(engine, countries_query)


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


def get_drilldown_data(engine, selected_country=None, selected_city=None):
    # Baseline query without CTE pre-filtering
    query = """
    SELECT 
        u.country,
        u.city,
        p.category AS product_category,
        SUM(f.total_amount) AS total_revenue,
        SUM(f.quantity) AS total_items_sold
    FROM fact_order_items f
    JOIN dim_users u ON f.user_key = u.user_id
    JOIN dim_products p ON f.product_key = p.product_id
    WHERE 1=1
    """
    params = {}
    if selected_country:
        query += " AND u.country = :selected_country"
        params["selected_country"] = selected_country
    if selected_city:
        query += " AND u.city = :selected_city"
        params["selected_city"] = selected_city

    query += " GROUP BY u.country, u.city, p.category ORDER BY u.country, u.city, total_revenue DESC;"
    return get_data(engine, query, params=params or None)


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

    if selected_month is not None:
        pivot_query += " AND MONTH(f.order_date) = :selected_month"
        params["selected_month"] = selected_month

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
    engine = init_connection()

    # Sidebar: Slice & Dice Filters
    st.sidebar.header("OLAP Filters (Slice & Dice)")

    months_df = get_available_months(engine)
    available_months = [None] + months_df["month"].dropna().astype(int).tolist()

    selected_month = st.sidebar.selectbox(
        "Select Month (Slice):",
        available_months,
        format_func=lambda month: (
            "All Months" if month is None else calendar.month_name[int(month)]
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
    st.header("1. Geographic & Product Hierarchy (Roll-up & Drill-down)")
    st.write("Navigate global sales summaries or perform targeted country drill-downs.")

    op_mode = st.radio(
        "Select Analytical View:",
        ["Full Roll-up Summary", "Geographic Drill-down"],
    )

    if op_mode == "Full Roll-up Summary":
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
            x_col = "country"
        elif granularity == "City (Drill-down)":
            filtered_rollup = rollup_data[
                (rollup_data["product_category"] == "All Categories")
                & (rollup_data["city"] != "All Cities")
            ]
            x_col = "city"
        else:
            filtered_rollup = rollup_data[
                rollup_data["product_category"] != "All Categories"
            ]
            x_col = "product_category"

        st.dataframe(filtered_rollup, use_container_width=True)

        if not filtered_rollup.empty and x_col in filtered_rollup.columns:
            chart_df = (
                filtered_rollup[[x_col, "total_revenue"]]
                .dropna()
                .groupby(x_col)["total_revenue"]
                .sum()
            )
            st.subheader(f"Total Revenue Breakdown by {granularity.split(' ')[0]}")
            st.bar_chart(chart_df)

    else:
        # Dynamic country selection from dim_users
        countries_df = get_available_countries(engine)
        available_countries = countries_df["country"].tolist()

        if available_countries:
            selected_country = st.selectbox(
                "Select Country to Drill-Down:",
                available_countries,
            )

            drilldown_data = get_drilldown_data(
                engine, selected_country=selected_country
            )
            st.dataframe(drilldown_data, use_container_width=True)

            if not drilldown_data.empty:
                chart_df = (
                    drilldown_data.groupby("city")["total_revenue"]
                    .sum()
                    .reset_index()
                    .set_index("city")
                )
                st.subheader(f"City Revenue Share in {selected_country}")
                st.bar_chart(chart_df)
        else:
            st.warning("No user location data available for drill-down.")

    # Section 2: Pivot table
    st.header("2. Revenue Pivot by User Gender")
    st.write(
        "Cross-tabulation comparing revenue across product categories and user demographics."
    )

    pivot_data = get_pivot_data(
        engine,
        selected_month=selected_month,
        selected_categories=selected_categories,
    )
    st.dataframe(pivot_data, use_container_width=True)

    if not pivot_data.empty:
        chart_data = pivot_data.set_index("product_category")[
            ["revenue_male", "revenue_female", "revenue_unspecified"]
        ]
        chart_data.columns = ["Male", "Female", "Unspecified / Other"]

        st.subheader("Gender Revenue Share per Category")
        st.bar_chart(chart_data, stack=True)


if __name__ == "__main__":
    main()