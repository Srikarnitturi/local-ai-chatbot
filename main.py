"""Version 2: Ollama chatbot with MySQL-backed conversation history."""
from __future__ import annotations
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

import httpx
import pymysql
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pymysql.cursors import DictCursor

import json
import math



BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.1')
EMBEDDING_MODEL = os.getenv(
    'EMBEDDING_MODEL', 'nomic-embed-text'
)

SYSTEM_PROMPT = 'You are a helpful technical support assistant. Give clear and accurate answers. If uncertain, say so.'


def get_db_connection():
    """Use environment variables; do not commit real passwords."""
    return pymysql.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', '3306')),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'ai_chatbot'),
        cursorclass=DictCursor,
        charset='utf8mb4',
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
        autocommit=False,
    )


def store_chat(session_id: str, question: str, answer: str) -> None:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO chat_history (session_id, question, answer) VALUES (%s, %s, %s)',
                (session_id, question, answer),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def read_history(session_id: str):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT id, question, answer, created_at FROM chat_history '
                'WHERE session_id = %s ORDER BY id ASC LIMIT 100',
                (session_id,),
            )
            return cursor.fetchall()
    finally:
        connection.close()

def get_previous_messages(session_id, limit=10):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT question, answer
                FROM (
                    SELECT id, question, answer
                    FROM chat_history
                    WHERE session_id = %s
                    ORDER BY id DESC
                    LIMIT %s
                ) AS recent
                ORDER BY id ASC
            """, (str(session_id), limit))

            return cursor.fetchall()
    finally:
        connection.close()


def cosine_similarity(vector_a, vector_b):
    if len(vector_a) != len(vector_b):
        return 0.0

    dot_product = sum(
        a * b for a, b in zip(vector_a, vector_b)
    )

    magnitude_a = math.sqrt(
        sum(a * a for a in vector_a)
    )
    magnitude_b = math.sqrt(
        sum(b * b for b in vector_b)
    )

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


async def search_knowledge(
    question: str,
    limit: int = 3,
    min_similarity: float = 0.55
):
    # Step 1: Generate embedding for the question
    response = await app.state.http_client.post(
        f'{OLLAMA_URL}/api/embed',
        json={
            'model': EMBEDDING_MODEL,
            'input': question
        }
    )
    response.raise_for_status()

    embeddings = response.json().get('embeddings')

    if not embeddings or not embeddings[0]:
        raise ValueError('Ollama returned no embedding')

    question_vector = embeddings[0]

    # Step 2: Load knowledge from MySQL
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, title, content, embedding
                FROM knowledge_base
                WHERE embedding IS NOT NULL
            """)
            records = cursor.fetchall()
    finally:
        connection.close()

    # Step 3: Compare embeddings
    results = []

    for record in records:
        stored_vector = record['embedding']

        if isinstance(stored_vector, str):
            stored_vector = json.loads(stored_vector)

        if not isinstance(stored_vector, list):
            continue

        if len(question_vector) != len(stored_vector):
            continue

        similarity = cosine_similarity(
            question_vector,
            stored_vector
        )

        if similarity >= min_similarity:
            results.append({
                'id': record['id'],
                'title': record['title'],
                'content': record['content'],
                'similarity': round(similarity, 4)
            })

    # Step 4: Sort by similarity
    results.sort(
        key=lambda item: item['similarity'],
        reverse=True
    )

    return results[:limit]


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
        app.state.http_client = client
        yield


app = FastAPI(title='Ollama AI Chatbot with MySQL', version='2.0.0', lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    answer: str
    model: str
    session_id: uuid.UUID


@app.get('/')
async def home():
    return FileResponse(BASE_DIR / 'static' / 'index.html')


@app.get('/health')
async def health():
    return {'status': 'ok', 'model': OLLAMA_MODEL}


@app.get('/favicon.ico', include_in_schema=False, status_code=204)
async def favicon():
    return None




@app.post('/chat', response_model=ChatResponse)
async def chat(payload: ChatRequest):
    session_id = payload.session_id or uuid.uuid4()

    # STEP 1: Load previous conversation from MySQL
    try:
        history = get_previous_messages(session_id)
    except pymysql.MySQLError as exc:
        raise HTTPException(
            status_code=503,
            detail='Unable to load chat history from MySQL.'
        ) from exc

    # STEP 2: Search knowledge base
    try:
        knowledge = await search_knowledge(payload.message)

    except (
        pymysql.MySQLError,
        httpx.HTTPError,
        ValueError,
        KeyError,
        TypeError
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail=f'Semantic knowledge search failed: {type(exc).__name__}'
        ) from exc

    knowledge_text = "\n\n".join(
        f"Title: {item['title']}\nContent: {item['content']}"
        for item in knowledge
    )

    # STEP 3: Prepare previous conversation
    conversation = []

    for item in history:
        conversation.append(
            f"User: {item['question']}\n"
            f"Assistant: {item['answer']}"
        )

    previous_conversation = "\n\n".join(conversation)

    # STEP 4: Build the final prompt
    prompt = f"""
You are an AI technical support assistant.

Use the KNOWLEDGE BASE to answer questions about
the products or policies described in it.

If requested product or policy information is not
available in the knowledge base, say so.
Do not invent product specifications.

KNOWLEDGE BASE:
{knowledge_text if knowledge_text else "No relevant records found."}

PREVIOUS CONVERSATION:
{previous_conversation if previous_conversation else "No previous conversation."}

CURRENT USER QUESTION:
{payload.message}

ASSISTANT ANSWER:
"""

    # STEP 5: Send the prompt to Ollama
    try:
        response = await app.state.http_client.post(
            f'{OLLAMA_URL}/api/generate',
            json={
                'model': OLLAMA_MODEL,
                'system': SYSTEM_PROMPT,
                'prompt': prompt,
                'stream': False
            },
        )

        response.raise_for_status()

        answer = response.json().get('response')

        if not isinstance(answer, str) or not answer.strip():
            raise HTTPException(
                status_code=502,
                detail='Ollama returned an empty response.'
            )

    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail='Cannot connect to Ollama on port 11434.'
        ) from exc

    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail='Ollama timed out.'
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f'Ollama returned HTTP {exc.response.status_code}.'
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail='Ollama returned invalid JSON.'
        ) from exc

    # STEP 6: Save question and answer in MySQL
    try:
        store_chat(
            str(session_id),
            payload.message,
            answer.strip()
        )
    except pymysql.MySQLError as exc:
        raise HTTPException(
            status_code=503,
            detail='Unable to save conversation to MySQL.'
        ) from exc

    # STEP 7: Return response to index.html
    return ChatResponse(
        answer=answer.strip(),
        model=OLLAMA_MODEL,
        session_id=session_id
    )


@app.get('/history/{session_id}')
async def history(session_id: uuid.UUID):
    try:
        records = read_history(str(session_id))
    except pymysql.MySQLError as exc:
        raise HTTPException(status_code=503, detail='MySQL unavailable. Check database settings.') from exc
    return {'session_id': str(session_id), 'messages': records}
