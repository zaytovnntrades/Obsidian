"""Drive examples/hello_pause.py over raw A2A JSON-RPC (start it first with PORT=8770)."""
import httpx, json, uuid
URL = "http://127.0.0.1:8770/jsonrpc/"

def send(text, task_id=None, context_id=None):
    msg = {"role": "user", "kind": "message", "messageId": str(uuid.uuid4()), "parts": [{"kind": "text", "text": text}]}
    if task_id: msg["taskId"] = task_id
    if context_id: msg["contextId"] = context_id
    body = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {"message": msg}}
    r = httpx.post(URL, json=body, timeout=30, trust_env=False).json()
    return r.get("result") or r

def texts(task):
    out = []
    for m in task.get("history", []):
        if m["role"] == "agent":
            out += [p.get("text") for p in m["parts"] if p.get("kind") == "text"]
    st = task["status"]
    if st.get("message"):
        out += [f'[status msg] {p.get("text")}' for p in st["message"]["parts"] if p.get("kind") == "text"]
    return out

t1 = send("hello agent")
print("CALL 1 -> state:", t1["status"]["state"])
for x in texts(t1): print("   ", repr(x))
t2 = send("yes, go ahead", task_id=t1["id"], context_id=t1["contextId"])
print("CALL 2 (same task) -> state:", t2["status"]["state"])
for x in texts(t2)[-1:]: print("   ", repr(x))
