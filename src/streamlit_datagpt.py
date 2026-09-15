""" Streamlit interface asking questions about orders table"""

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
import os
import pandas as pd

from mydb import *
from sendreport import send_email_report

load_dotenv()
my_key=os.getenv('OPEN_API_KEY')
print(my_key)

client =OpenAI(api_key=my_key)

st.set_page_config(page_title="DataGPT", page_icon="📊", layout="wide")
# Domain and table selection (select schema/domain and then table)
st.sidebar.header("Select domain")
domain = st.sidebar.selectbox("Which domain to analyze?", ("public", "company"), index=0)
@st.cache_data(show_spinner=False)
def fetch_schema(table_name:str,domain:str):
    schema=get_schema(table_name,domain)
    return schema


def get_tables_in_domain(domain: str):
    """Return a list of table names for the given schema/domain."""
    q = f"""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = '{domain}'
      AND table_type = 'BASE TABLE'
    ORDER BY table_name;
    """
    try:
        df = execute_query(q)
        return df['table_name'].tolist() if not df.empty else []
    except Exception:
        return []

# Get tables for selected domain
tables = get_tables_in_domain(domain)
print(tables)

# Default table used by the query generator is the first table in the domain
table_name = tables[0]

# Sidebar Data Explorer: show schema for every table in the domain
st.sidebar.header("Data Explorer")
for t in tables:
    with st.sidebar.expander(f"{t}"):
        try:
            sch = fetch_schema(t, domain)
            st.dataframe(sch, use_container_width=True, hide_index=True)
        except Exception as e:
            st.sidebar.write(f"Could not load schema for {t}: {e}")
@st.cache_data(show_spinner=False)

def fetch_schema(table_name:str,domain:str):
    schema=get_schema(table_name,domain)
    return schema

def generate_sql(question: str, domain: str, domain_tables: list):
    """Build a prompt containing the full schema for the selected domain (all tables),
    ask the LLM to produce a single read-only PostgreSQL SELECT query that answers
    the user's natural-language `question`.

    The LLM must only return SQL (no explanation, no markdown fences). The SQL must
    be read-only (SELECT only)."""
    # Build combined schema text for the domain
    schema_parts = []
    for t in domain_tables:
        try:
            sch = fetch_schema(t, domain)
            # convert schema dataframe to simple table description
            sch_text = sch.to_string(index=False)
        except Exception:
            sch_text = "(could not load schema)"
        schema_parts.append(f"Table: {t}\n{sch_text}")
    combined_schema = "\n\n".join(schema_parts)

    prompt = f"""You are an expert SQL generator. Use the schema below to write one PostgreSQL SELECT query that answers the user's question.

Rules:
- Use only the tables and columns provided in the schema below.
- Produce a single read-only PostgreSQL `SELECT` statement (no INSERT/UPDATE/DELETE/DDL).
- Do not include any explanation, commentary, or Markdown fences — return SQL only.
- If the question requires columns or tables not present, return a commented SQL line starting with /* MISSING: ... */ explaining what is missing.

Domain: {domain}

Schema:
{combined_schema}

Question: {question}
"""

    client = OpenAI(api_key=my_key)
    response = client.responses.create(model="gpt-5.6-sol", input=prompt)
    sql = response.output_text.strip()
    # strip common code fences if present
    sql = sql.removeprefix("```sql").removeprefix("```").removesuffix("```").strip()
    return sql




st.title("DataGPT")
st.caption(f"Ask questions about the `{table_name}` table in plain English.")


try:
    schema = fetch_schema(table_name,domain)
    print(schema)
except Exception as error:
    st.error("Could not connect to PostgreSQL. Check that the database is running and configured.")
    st.exception(error)
    st.stop()

with st.form("question_form"):
    question = st.text_input(
        "What would you like to know about the data?",
        placeholder="For example: Give me the top 5 states by sales",
    )
    submitted = st.form_submit_button("Run query", type="primary")

if submitted:
    if not question.strip():
        st.warning("Enter a question before running a query.")
        st.stop()

    try:
        with st.spinner("Generating SQL and querying the database..."):
            sql_query = generate_sql(question, domain, tables)
            # Execute the query with the search_path set to the selected domain
            results = execute_query(sql_query, search_path=domain)

        st.subheader("Generated SQL")
        st.code(sql_query, language="sql")
        st.subheader("Results")
        st.dataframe(results, use_container_width=True, hide_index=True)
        st.caption(f"{len(results):,} row(s) returned")
        # Email report UI
        recipient = st.text_input("Send report to (email)", value=os.getenv('REPORT_TO', ''))
        if st.button("Email report"):
            if not recipient:
                st.warning("Enter recipient email before sending the report.")
            else:
                try:
                    send_email_report(recipient, f"DataGPT report for {table_name}", schema, sql_query, results)
                    st.success("Report emailed successfully")
                except Exception as e:
                    st.error(f"Failed to send email: {e}")
    except Exception as error:
        st.error("The query could not be completed.")
        st.exception(error)    