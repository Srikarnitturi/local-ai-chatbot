
import os
import json
import httpx
from dotenv import load_dotenv
from main import get_db_connection

load_dotenv()

OLLAMA_URL = os.getenv(
    "OLLAMA_URL", "http://127.0.0.1:11434"
).rstrip("/")

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "nomic-embed-text"
)

def generate_embeddings():
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, title, content
                FROM knowledge_base
                WHERE embedding IS NULL
            """)

            records = cursor.fetchall()

            with httpx.Client(timeout=120.0) as client:
                for record in records:
                    text = (
                        f"{record['title']}\n"
                        f"{record['content']}"
                    )

                    response = client.post(
                        f"{OLLAMA_URL}/api/embed",
                        json={
                            "model": EMBEDDING_MODEL,
                            "input": text
                        }
                    )
                    response.raise_for_status()

                    vector = response.json()["embeddings"][0]

                    cursor.execute("""
                        UPDATE knowledge_base
                        SET embedding = %s
                        WHERE id = %s
                    """, (json.dumps(vector), record["id"]))

                    connection.commit()

                    print(
                        f"Embedded record {record['id']}: "
                        f"{record['title']}"
                    )

        print("Embedding generation completed.")

    finally:
        connection.close()


if __name__ == "__main__":
    generate_embeddings()
