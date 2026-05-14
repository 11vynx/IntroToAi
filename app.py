import streamlit as st
import psycopg2
import pandas as pd
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("AIzaSyAAifks3wub5fRGY15K7M7t-6jmJ5c9pz8"))

SCHEMA_PROMPT = """
You are an expert SQL assistant for an Incident Command System.
Your task is to translate natural language questions into valid PostgreSQL queries.

Here is the schema for the database:
CREATE TABLE incidents (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255),
    type VARCHAR(100),
    severity VARCHAR(50),
    lgu VARCHAR(255),
    barangay VARCHAR(255),
    datetime TIMESTAMP,
    affected_population INTEGER,
    status VARCHAR(50) DEFAULT 'active'
);

Rules:
1. Return ONLY the raw SQL query.
2. Do not include markdown formatting (like ```sql).
3. Do not include any explanations.
4. Only query the columns that exist in the schema provided.
"""

def execute_sql(query):
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT")
        )
        cursor = conn.cursor()
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        colnames = [desc[0] for desc in cursor.description]
        df = pd.DataFrame(rows, columns=colnames)
        
        cursor.close()
        conn.close()
        return df, None
    except Exception as e:
        return None, str(e)

def get_count_for_lgu(lgu_value):
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT")
        )
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(id) FROM incidents WHERE lgu = %s", (lgu_value,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return (row[0] if row else 0), None
    except Exception as e:
        return None, str(e)

st.set_page_config(page_title="ICS Natural Language to SQL", layout="centered")

st.title("ICS Data Query Assistant")
st.markdown("Ask a question about the incident database in plain English.")

user_question = st.text_input("Example: 'Show me all High severity incidents in General Santos City'")

if st.button("Generate & Run Query"):
    if user_question:
        with st.spinner("Translating to SQL..."):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"{SCHEMA_PROMPT}\n\nUser Question: {user_question}"
                )
                
                generated_sql = response.text.replace('```sql', '').replace('```', '').strip()
                
                st.subheader("Generated SQL:")
                st.code(generated_sql, language="sql")
                
                with st.spinner("Executing query on PostgreSQL..."):
                    results_df, error = execute_sql(generated_sql)
                    
                    if error:
                        st.error(f"Database Error: {error}")
                    elif results_df.empty:
                        st.warning("Query executed successfully, but no records were found.")
                    else:
                        # Try to render a human-friendly sentence when possible
                        if 'lgu' in results_df.columns:
                            lgu = results_df.iloc[0].get('lgu')
                            count_value = None
                            # Look for a numeric/count column in the results
                            for col in results_df.columns:
                                if col == 'lgu':
                                    continue
                                try:
                                    if pd.api.types.is_integer_dtype(results_df[col].dtype) or pd.api.types.is_numeric_dtype(results_df[col].dtype) or 'count' in col.lower():
                                        count_value = int(results_df.iloc[0][col])
                                        break
                                except Exception:
                                    continue

                            if count_value is None:
                                # Fallback: run a safe parameterized count query for the returned lgu
                                cnt, cnt_err = get_count_for_lgu(lgu)
                                if cnt_err is None:
                                    st.success(f"The lgu with highest number of reported incidents is {lgu} with {cnt} reports.")
                                else:
                                    st.subheader("Results:")
                                    st.dataframe(results_df, use_container_width=True)
                                    st.info(f"Could not fetch count: {cnt_err}")
                            else:
                                st.success(f"The lgu with highest number of reported incidents is {lgu} with {count_value} reports.")
                        else:
                            st.subheader("Results:")
                            st.dataframe(results_df, use_container_width=True)
                        
            except Exception as e:
                st.error(f"AI Generation Error: {str(e)}")
    else:
        st.warning("Please enter a question first.")