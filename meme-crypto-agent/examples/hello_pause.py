"""The smallest useful Agent Stack agent: stream, pause for the user, resume.

Run:   uv run python examples/hello_pause.py
Talk:  agentstack run my_agent "hi"      (or see the raw A2A calls in the README)
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from a2a.types import Message, TaskStatus, TextPart

from agentstack_sdk.a2a.types import AuthRequired
from agentstack_sdk.server import Server

server = Server()


@server.agent()
async def my_agent(message: Message) -> AsyncGenerator[TaskStatus | Message | str, Message]:
    """Streams a reply, pauses for confirmation, then echoes the follow-up."""
    assert isinstance(message.parts[0].root, TextPart)
    yield f"first reply (you sent: {message.parts[0].root.text})\n"  # stream text back
    followup = yield AuthRequired(text="ok?")  # pause: the task waits here for the user
    yield f"you said: {followup.parts[0].root.text}"  # resumes with the user's answer


if __name__ == "__main__":
    server.run(host="127.0.0.1", port=int(os.getenv("PORT", 8000)), self_registration=False)
