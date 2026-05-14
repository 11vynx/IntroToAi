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

def generate_summary_message(results_df):
    """Generate a human-friendly summary message for any query result."""
    if len(results_df) == 0:
        return None
    
    num_rows = len(results_df)
    num_cols = len(results_df.columns)
    
    # Single row - create descriptive sentence
    if num_rows == 1:
        row = results_df.iloc[0]
        
        # If all columns are text, just list them
        if num_cols == 1:
            col_name = results_df.columns[0]
            value = row[col_name]
            return f"{col_name.capitalize()}: {value}"
        
        # Multiple columns - create a natural sentence
        else:
            parts = []
            for col_name in results_df.columns:
                value = row[col_name]
                # Format numeric values nicely
                if isinstance(value, (int, float)):
                    parts.append(f"{col_name.replace('_', ' ')}: {int(value) if isinstance(value, int) else value}")
                else:
                    parts.append(f"{col_name.replace('_', ' ')}: {value}")
            
            return "Summary: " + " | ".join(parts)
    
    # Multiple rows - create breakdown or list
    else:
        first_col = results_df.columns[0]
        
        # If there's a numeric column, show breakdown
        numeric_cols = results_df.select_dtypes(include=['number']).columns.tolist()
        if numeric_cols:
            second_col = numeric_cols[0]
            items = [f"{row[first_col]} ({int(row[second_col])})" for _, row in results_df.iterrows()]
            return f"{first_col.capitalize()} breakdown: " + ", ".join(items)
        else:
            # Just list the values
            values = results_df[first_col].tolist()
            return f"Found {num_rows} {first_col}: " + ", ".join(str(v) for v in values)

st.set_page_config(page_title="ICS Natural Language to SQL", layout="centered")

# Initialize session state
if "current_question" not in st.session_state:
    st.session_state.current_question = ""
if "generated_sql" not in st.session_state:
    st.session_state.generated_sql = None
if "results_df" not in st.session_state:
    st.session_state.results_df = None
if "results_error" not in st.session_state:
    st.session_state.results_error = None
if "success_message" not in st.session_state:
    st.session_state.success_message = None

st.title("ICS Data Query Assistant")
st.markdown("Ask a question about the incident database in plain English.")

user_question = st.text_input("Example: 'Show me all High severity incidents in General Santos City'")

# Clear results if question changed
if user_question != st.session_state.current_question:
    st.session_state.generated_sql = None
    st.session_state.results_df = None
    st.session_state.results_error = None
    st.session_state.success_message = None

if st.button("Generate & Run Query"):
    if user_question:
        # Update the current question
        st.session_state.current_question = user_question
        
        with st.spinner("Translating to SQL..."):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"{SCHEMA_PROMPT}\n\nUser Question: {user_question}"
                )
                
                generated_sql = response.text.replace('```sql', '').replace('```', '').strip()
                st.session_state.generated_sql = generated_sql
                
                st.subheader("Generated SQL:")
                st.code(generated_sql, language="sql")
                
                with st.spinner("Executing query on PostgreSQL..."):
                    results_df, error = execute_sql(generated_sql)
                    
                    if error:
                        st.session_state.results_error = error
                        st.error(f"Database Error: {error}")
                    elif results_df.empty:
                        st.session_state.results_error = "No results"
                        st.warning("Query executed successfully, but no records were found.")
                    else:
                        st.session_state.results_df = results_df
                        st.session_state.results_error = None
                        
                        st.subheader("Results:")
                        st.dataframe(results_df, use_container_width=True)
                        
                        # Generate and show summary for all results
                        summary = generate_summary_message(results_df)
                        if summary:
                            st.session_state.success_message = summary
                            st.info(summary)
                        
            except Exception as e:
                st.session_state.results_error = str(e)
                st.error(f"AI Generation Error: {str(e)}")
    else:
        st.warning("Please enter a question first.")