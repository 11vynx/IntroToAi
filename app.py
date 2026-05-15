import streamlit as st
import psycopg2
import pandas as pd
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GENAI_API_KEY"))

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
5. For text comparisons (especially lgu and barangay), ALWAYS use ILIKE instead of = to handle case variations.
6. When users mention location names (lgu, barangay), normalize them to Proper Case format (e.g., "general santos city" → "General Santos City").
7. Handle all user input variations: lowercase, UPPERCASE, mixed case, extra spaces - convert them to the proper format.
8. Example: If user asks "everything in GENERAL SANTOS CITY", convert to: WHERE lgu ILIKE 'General Santos City'
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

def generate_natural_language_answer(user_question, results_df):
    """Use AI to convert query results into a natural English answer."""
    try:
        # Convert dataframe to a readable string format for the AI
        results_text = results_df.to_string()
        
        prompt = f"""You are an assistant for an Incident Command System database.
        
The user asked: "{user_question}"

Here are the query results:
{results_text}

Please provide a clear, concise, natural English answer to the user's question based on these results.
- Be conversational and easy to understand
- Summarize key findings
- If there are multiple records, highlight important patterns or totals
- Do not include technical SQL or database terminology
- Keep the answer to 2-3 sentences maximum"""

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        return response.text.strip()
    except Exception as e:
        return f"Could not generate answer: {str(e)}"

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
if "natural_answer" not in st.session_state:
    st.session_state.natural_answer = None

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
                        
                        # Generate natural language answer
                        with st.spinner("Generating answer..."):
                            natural_answer = generate_natural_language_answer(user_question, results_df)
                            st.session_state.success_message = natural_answer
                        
                        # Display the answer prominently
                        st.subheader("Answer:")
                        st.success(natural_answer)
                        
                        # Show raw results for transparency
                        st.subheader("Query Results:")
                        st.dataframe(results_df, use_container_width=True)
                        
            except Exception as e:
                st.session_state.results_error = str(e)
                st.error(f"AI Generation Error: {str(e)}")
    else:
        st.warning("Please enter a question first.")