import requests
import json
import sqlite3

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:3b"
DB_PATH = "sources.db"

# ── Inference parameters ──────────────────────────────────────────────
OPTIONS = {
    "temperature": 0.5, # Lower = more focused answers
    "top_p": 0.9,
    "top_k": 40,
    "num_ctx": 4096, # Context window size in tokens
    "num_predict": 2512, # Max tokens in the reply
    "repeat_penalty": 1.1,
}

# ── System prompt ──────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are a LLM who's main focus is reciting factual information from trustworthy sources. "
    "You MUST ONLY use the provided 'Retrieved sources' to answer the question, which are stoed in a file called 'sources.db'. "
    "If no sources provided contain the relevant information, you MUST respond exactly with: 'I'm sorry, I don't have enough information to answer that question.' "
    "Then tell the user that you will try to answer the question to the best of your ability, but that your answer may be incomplete or inaccurate due to lack of information. "
    "With each response, share where you got your information from, and if possible, include a link to the source. " 
    "You are discouraged from using wikis such as Reddit, Wikipedia, or Quora, as they can be unreliable. " 
    "Instead, prioritize information from reputable news outlets, academic journals, and official websites. "
)

# ── Context window management: keep last N user+assistant pairs ────────
MAX_TURNS = 10 # Each turn = 1 user message + 1 assistant message

def trim_history(history):
    """
    Keep the system prompt (index 0) and the most recent MAX_TURNS
    pairs of user/assistant messages. This prevents context overflow.
    """
    system = [history[0]] # Always preserve the system prompt
    dialog = history[1:] # All user/assistant turns
    # Each pair is 2 messages; keep the most recent MAX_TURNS pairs
    trimmed = dialog[-(MAX_TURNS * 2):]
    return system + trimmed

def chat(history):
    """
    Send the conversation history to the model and stream the reply
    back token-by-token, printing each chunk as it arrives.
    Returns the complete reply string for appending to history.
    """
    payload = {
        "model": MODEL,
        "messages": history,
        "options": OPTIONS,
        "stream": True # <-- the only change to the payload
    }
    
    # stream=True keeps the connection open; lines arrive as they are generated
    response = requests.post(OLLAMA_URL, json=payload, stream=True)
    response.raise_for_status()

    full_reply = [] # accumulate chunks so we can return the complete text

    print("Model: ", end="", flush=True) # label before the first token arrives

    for line in response.iter_lines():
        if not line:
            continue # skip keep-alive blank lines
        
        chunk = json.loads(line) # each line is a complete JSON object
        token = chunk["message"]["content"]
        
        # end="" suppresses the automatic newline so tokens run together
        # flush=True forces the terminal to display immediately, not in a batch
        print(token, end="", flush=True)
        full_reply.append(token)

        if chunk.get("done"): # the final chunk signals end of generation
            break
       
    print() # advance the cursor to a new line after the response is complete
    return "".join(full_reply)


def fetch_sources(query, max_results=3):
    """Return up to `max_results` rows from the `sources` table that match words in `query`.
    Only return rows where `is_good` is true. Matches are performed against
    `abstract`, `url`, and `authors` using simple LIKE queries.
    Returns a list of dicts with keys: url, authors, publish_date, abstract.
    """
    if not query:
        return []

    words = [w.strip() for w in query.split() if w.strip()]
    if not words:
        return []

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Build WHERE clause: any word matching any of the searchable columns
    conds = []
    params = []
    for w in words:
        pattern = f"%{w}%"
        conds.append("(abstract LIKE ? OR url LIKE ? OR authors LIKE ?)")
        params.extend([pattern, pattern, pattern])

    where = " OR ".join(conds)
    # Only include rows marked as good in the DB (is_good == 1)
    sql = f"SELECT url, authors, publish_date, abstract FROM sources WHERE ({where}) AND is_good = 1 ORDER BY publish_date DESC LIMIT ?"
    params.append(max_results)

    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()

    results = []
    for r in rows:
        results.append({
            "url": r[0],
            "authors": r[1],
            "publish_date": r[2],
            "abstract": r[3],
        })
    return results


def main():
    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    print("Fact reciter ready. Conversation history limited to " + str(int(MAX_TURNS/2)) + " messages. Type 'quit' to exit.")
    print("-" * 60)
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("quit", "exit", "bye"):
            print("Goodbye!")
            break
        if not user_input:
            continue
        
        # Fetch relevant sources from local SQLite DB and inject them into context
        sources = fetch_sources(user_input, max_results=3)
        if sources:
            # build a concise sources summary to give the model context/citations
            lines = []
            for s in sources:
                abstract_snip = (s["abstract"][:200] + '...') if s.get("abstract") else ""
                pub = s.get("publish_date") or "unknown"
                auth = s.get("authors") or "unknown"
                lines.append(f"- {s.get('url')} ({auth}, {pub}): {abstract_snip}")
            sources_text = "\n".join(lines)
            # Add the user's question and the retrieved sources to the conversation
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": "Retrieved sources:\n" + sources_text})
        else:
            history.append({"role": "user", "content": user_input})
        history = trim_history(history) # Apply sliding window before sending

        reply = chat(history)
        history.append({"role": "assistant", "content": reply})
        print("-" * 60)

if __name__ == "__main__":
    main()
