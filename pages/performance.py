import importlib
import importlib.util
import pandas as pd
import streamlit as st
from benchmark import benchmark_query, capture_queries

# Apps that get compared
APP_MODULES = ["app_baseline", "app_optimized"]


def main():
    st.set_page_config(
        page_title="Query Performance",
        layout="wide",
    )

    st.title("Query Performance: Baseline vs. Optimized")
    st.write(
        "Runs every dashboard query of each app and measures it. "
        "**mysql_ms** is the execution time reported by MySQL (`EXPLAIN ANALYZE`), "
        "**wall_ms_median** includes total execution and connection round-trip latency."
    )

    runs = st.slider("Timed runs per query (median is reported):", 1, 5, 3)

    if not st.button("Run benchmark"):
        return

    rows = []
    plans = []
    for module_name in APP_MODULES:
        if importlib.util.find_spec(module_name) is None:
            st.info(f"Skipping {module_name}: file not found.")
            continue

        module = importlib.import_module(module_name)
        engine = module.init_connection()

        with st.spinner(f"Benchmarking {module_name}..."):
            for query_name, query, params in capture_queries(module, engine):
                result = benchmark_query(engine, query, params, runs)
                rows.append({
                    "app": module_name,
                    "query": query_name,
                    "mysql_ms": result["mysql_ms"],
                    "wall_ms_median": result["wall_ms_median"],
                    "estimated_cost": result["estimated_cost"],
                })
                plans.append((module_name, query_name, result["explain_analyze"]))

    results_df = pd.DataFrame(rows)

    # Raw metrics table
    st.subheader("Detailed Benchmark Metrics")
    st.dataframe(results_df, use_container_width=True)

    # Individual, unstacked bar chart per query
    st.subheader("Individual Query Performance (`mysql_ms`)")
    queries = results_df["query"].unique()
    cols = st.columns(2)

    for idx, q_name in enumerate(queries):
        with cols[idx % 2]:
            st.markdown(f"#### `{q_name}`")
            q_df = results_df[results_df["query"] == q_name]
            
            # Pivot app vs query execution time
            chart_data = q_df.pivot(index="app", columns="query", values="mysql_ms")
            
            # stack=False ensures side-by-side bars, not combined/stacked
            st.bar_chart(chart_data, stack=False)

    # EXPLAIN ANALYZE query plans
    st.subheader("Execution Plans")
    for module_name, query_name, plan in plans:
        with st.expander(f"EXPLAIN ANALYZE: {module_name} / {query_name}"):
            st.code(plan)


if __name__ == "__main__":
    main()