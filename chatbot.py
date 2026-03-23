import requests
import json

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:3b"

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
    "With each response, share where you got your information from, and if possible, include a link to the source. " 
    "Additionally, share your confidence level in the information you provide, on a scale from 0 to 100. " 
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
       
        history.append({"role": "user", "content": user_input})
        history = trim_history(history) # Apply sliding window before sending
        
        # Go through sources.db table, search for sources that meet the trustworthy threshold,
        # and send them to the MCP, where it will determine what is relvant and sends to the LLM.
        # send them to the model as context, and let it decide what to use.

        reply = chat(history)
        history.append({"role": "assistant", "content": reply})
        
        print(f"\nModel: {reply}")
        print("-" * 60)

if __name__ == "__main__":
    main()
