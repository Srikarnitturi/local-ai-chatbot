# Ollama AI Chatbot — Version 2 (MySQL)

## What's new
- Stores each question and Ollama answer in MySQL.
- Returns a UUID session ID and reuses it in the browser.
- `GET /history/{session_id}` retrieves up to 100 saved exchanges.
- This version **does not pass previous conversation turns back into Ollama**. Conversation memory comes in Version 3.

## Windows installation
1. Install MySQL Server (or use your existing local MySQL server).
2. Run `sql/schema.sql` in MySQL Workbench or MySQL CLI to create `ai_chatbot.chat_history`.
3. Copy `.env.example` to `.env` and fill in your own MySQL username/password.
4. In PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

5. Visit http://127.0.0.1:8000/ — with Ollama running and `llama3.1` downloaded.

## API test
`POST /chat` body: `{"message":"What is FastAPI?"}`
Response includes `answer`, `model`, and `session_id`.
Use the returned session ID for the next `POST /chat`, and visit `GET /history/{session_id}` to retrieve saved exchanges.

## Architecture
Browser -> FastAPI -> Ollama -> MySQL insert -> Browser

**Security:** Prototype only. Session IDs are not authentication tokens. Do not expose these endpoints to the public Internet until authentication and authorization are added. Do not commit `.env` to Git.
