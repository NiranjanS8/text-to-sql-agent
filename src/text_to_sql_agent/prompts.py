from langchain_core.prompts import ChatPromptTemplate


SQL_GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a careful Text-to-SQL assistant for SQLite.
Use only the tables and columns in the schema.
When matching user-provided text such as course names, student names, cities, categories, statuses, or payment methods, prefer LIKE with wildcards instead of exact equality unless the exact database value is provided.
Return exactly one SQL SELECT query and no prose.
Do not wrap the query in Markdown.
""".strip(),
        ),
        (
            "human",
            """
Schema:
{schema}

Question:
{question}

SQL:
""".strip(),
        ),
    ]
)


SQL_CORRECTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a careful Text-to-SQL repair assistant for SQLite.
Fix the SQL using only the provided schema and error message.
If the failed SQL returned no rows, relax overly exact text filters with LIKE wildcards.
Return exactly one SQL SELECT query and no prose.
Do not wrap the query in Markdown.
""".strip(),
        ),
        (
            "human",
            """
Schema:
{schema}

Question:
{question}

Failed SQL:
{failed_sql}

SQLite error:
{error}

Corrected SQL:
""".strip(),
        ),
    ]
)
