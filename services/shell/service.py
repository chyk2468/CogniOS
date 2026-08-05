# services/shell/service.py
"""Shell service — safe command execution."""

from dataclasses import dataclass
from typing import Optional, AsyncIterator
import asyncio
import os
import signal
import sys
from pathlib import Path


@dataclass
class ShellResult:
    """Result of a shell command execution."""
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


class ShellService:
    """Shell execution service with timeout and output bounding."""

    def __init__(self, timeout: int = 30, max_output: int = 200_000):
        self.timeout = timeout
        self.max_output = max_output
        self.cwd = str(Path.home())

    def _get_subprocess_kwargs(self) -> dict:
        """Configures platform-specific process group creation."""
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(asyncio.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        else:
            kwargs["start_new_session"] = True
        return kwargs

    async def _kill_process_tree(self, proc: asyncio.subprocess.Process) -> None:
        """Kills the target process and all child processes spawned by it."""
        if proc.returncode is not None:
            return
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            await proc.wait()
        except (ProcessLookupError, OSError):
            pass

    async def execute(
        self,
        command: str,
        timeout: Optional[int] = None,
        cwd: Optional[str] = None,
    ) -> ShellResult:
        """Execute a shell command and return captured bounded output."""
        exec_timeout = self.timeout if timeout is None else timeout
        exec_cwd = cwd or self.cwd

        proc = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=exec_cwd,
                **self._get_subprocess_kwargs(),
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=exec_timeout
            )
            stdout = stdout_b.decode(errors="replace")[: self.max_output]
            stderr = stderr_b.decode(errors="replace")[: self.max_output]
            return ShellResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            if proc:
                await self._kill_process_tree(proc)
            return ShellResult(
                stdout="",
                stderr=f"Command timed out after {exec_timeout}s",
                exit_code=-1,
                timed_out=True,
            )
        except Exception as e:
            return ShellResult(stdout="", stderr=str(e), exit_code=-1)

    async def stream(
        self,
        command: str,
        timeout: Optional[int] = None,
        cwd: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """Execute a command and stream output line-by-line."""
        exec_timeout = 120 if timeout is None else timeout
        exec_cwd = cwd or self.cwd

        proc = None
        reader_tasks = []
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=exec_cwd,
                **self._get_subprocess_kwargs(),
            )

            q: asyncio.Queue = asyncio.Queue()

            async def _reader(stream: asyncio.StreamReader, name: str) -> None:
                try:
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        text = line.decode(errors="replace").rstrip("\r\n")
                        await q.put((name, text))
                finally:
                    await q.put((name, None))

            reader_tasks = [
                asyncio.create_task(_reader(proc.stdout, "stdout")),
                asyncio.create_task(_reader(proc.stderr, "stderr")),
            ]

            loop = asyncio.get_running_loop()
            finished = 0
            deadline = loop.time() + exec_timeout

            while finished < 2:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()

                try:
                    name, text = await asyncio.wait_for(
                        q.get(), timeout=min(remaining, 1.0)
                    )
                except asyncio.TimeoutError:
                    continue

                if text is None:
                    finished += 1
                    continue

                yield {"stream": name, "data": text}

            await proc.wait()
            yield {"exit_code": proc.returncode or 0}

        except asyncio.TimeoutError:
            if proc:
                await self._kill_process_tree(proc)
            yield {"stream": "stderr", "data": f"Command timed out after {exec_timeout}s"}
            yield {"exit_code": -1}
        except Exception as e:
            yield {"stream": "stderr", "data": str(e)}
            yield {"exit_code": -1}
        finally:
            for t in reader_tasks:
                t.cancel()
            if reader_tasks:
                await asyncio.gather(*reader_tasks, return_exceptions=True)

