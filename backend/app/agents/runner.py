"""
The agent runtime -- spawn the user's CLI, pump its streams, normalize its events.

This is the Python equivalent of what routes/chat.js did with `child_process.spawn`
plus `.on('data')` callbacks. The shape is different because FastAPI wants to *pull*
from an async iterator while the parsers *push* events, so a queue bridges the two:

    subprocess stdout -> incremental decoder -> parser -> queue -> async generator -> SSE

Details that matter and are easy to get wrong in a port:

* Concurrency. stdin writing, stdout reading and stderr reading all run together in one
  task group. Doing them in sequence risks a deadlock: a large prompt can fill the pipe
  buffer while nobody drains stdout.
* Chunked decoding. stdout is read in byte chunks, not lines, exactly like Node's
  `chunk.toString()`. A multi-byte character (a rupee sign in a product name) can land
  across a chunk boundary, so an incremental UTF-8 decoder is required -- plain
  `bytes.decode()` per chunk would corrupt it.
* Cleanup. If the browser disconnects mid-turn the generator is closed, which raises at
  the `yield`. The `finally` terminates the child, so a cancelled turn never leaves an
  orphaned `claude`/`codex` process behind.
"""

from __future__ import annotations

import asyncio
import codecs
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ..core.logging import get_logger
from .base import AgentDef
from .executable import resolve_executable
from .streams import create_parser

log = get_logger("runner")

Event = dict[str, Any]

CHUNK_SIZE = 65536
STDERR_TAIL_CHARS = 2000
TERMINATE_GRACE_SECONDS = 5.0

_SENTINEL = object()


async def terminate(process: asyncio.subprocess.Process) -> None:
    """Stop a child that is still running, escalating if it ignores the first ask."""
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), TERMINATE_GRACE_SECONDS)
    except (asyncio.TimeoutError, TimeoutError):
        try:
            process.kill()
        except ProcessLookupError:
            return
        await process.wait()


async def stream_agent_events(
    agent: AgentDef,
    argv: list[str],
    *,
    cwd: Path | str,
    prompt: str,
    env: dict[str, str] | None = None,
) -> AsyncIterator[Event]:
    """Run one turn and yield normalized events until the process exits.

    Does NOT emit a terminal `end` event -- callers that speak SSE add it, matching the
    Node routes where `send({type:'end'})` lived in the route, not the parser.
    """
    launcher = resolve_executable(agent.bin)
    if launcher is None:
        yield {
            "type": "error",
            "message": f"Failed to launch {agent.bin}: command not found on PATH",
        }
        return

    try:
        process = await asyncio.create_subprocess_exec(
            *launcher,
            *argv,
            cwd=str(cwd),
            env=env if env is not None else os.environ.copy(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, ValueError) as exc:
        yield {"type": "error", "message": f"Failed to launch {agent.bin}: {exc}"}
        return

    queue: asyncio.Queue[Any] = asyncio.Queue()
    parser = create_parser(agent.stream_format, queue.put_nowait)
    stderr_tail = ""

    async def write_stdin() -> None:
        """Prompt goes in as plain text for both CLIs, then stdin closes to signal
        end-of-turn. Delivering it here (not via argv) keeps it clear of length limits."""
        assert process.stdin is not None
        try:
            process.stdin.write(prompt.encode("utf-8"))
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the child exited early; its exit code is the real error
        finally:
            try:
                process.stdin.close()
            except (BrokenPipeError, ConnectionResetError, AttributeError):
                pass

    async def pump_stdout() -> None:
        assert process.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while True:
            chunk = await process.stdout.read(CHUNK_SIZE)
            if not chunk:
                break
            parser.feed(decoder.decode(chunk))
        tail = decoder.decode(b"", final=True)
        if tail:
            parser.feed(tail)
        parser.flush()

    async def pump_stderr() -> None:
        nonlocal stderr_tail
        assert process.stderr is not None
        while True:
            chunk = await process.stderr.read(CHUNK_SIZE)
            if not chunk:
                break
            stderr_tail = (stderr_tail + chunk.decode("utf-8", "replace"))[-STDERR_TAIL_CHARS:]

    async def drive() -> None:
        try:
            await asyncio.gather(write_stdin(), pump_stdout(), pump_stderr())
            code = await process.wait()
            if code != 0:
                queue.put_nowait(
                    {
                        "type": "error",
                        "message": stderr_tail.strip()
                        or f"{agent.name} exited with code {code}",
                    }
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface, never swallow
            log.exception("[runner] %s stream failed", agent.bin)
            queue.put_nowait({"type": "error", "message": str(exc) or "Agent stream failed"})
        finally:
            queue.put_nowait(_SENTINEL)

    driver = asyncio.create_task(drive())

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            yield item
    finally:
        # Reached on normal completion AND when the browser disconnects mid-stream
        # (the generator is closed, raising here). Either way the child must not
        # outlive the request.
        driver.cancel()
        await terminate(process)
        await asyncio.gather(driver, return_exceptions=True)


async def run_agent_once(
    agent: AgentDef, argv: list[str], *, cwd: Path | str, prompt: str
) -> str:
    """Collect a whole turn's visible text. Raises RuntimeError on failure.

    This is the primitive behind the one-shot calls (day details, grocery-list
    consolidation): same spawn path and same parser as chat, but nothing is streamed,
    persisted, or resumed.
    """
    text: list[str] = []
    error: str | None = None

    async for event in stream_agent_events(agent, argv, cwd=cwd, prompt=prompt):
        if event.get("type") == "delta" and event.get("text"):
            text.append(event["text"])
        elif event.get("type") == "error":
            error = event.get("message") or "Agent run failed"

    if error:
        raise RuntimeError(error)
    return "".join(text).strip()
