#!/usr/bin/env python3
#
#  Copyright 2002-2026 Barcelona Supercomputing Center (www.bsc.es)
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

from __future__ import annotations

import fcntl
import os
import pty
import shutil
import struct
import struct
import subprocess
from pathlib import Path
import termios


class LocalPyCompssMetadataInspector:
    """Runs `pycompss inspect` using a PTY so Rich keeps colors."""

    def __init__(self, executable: str = "pycompss") -> None:
        self._executable = executable

    def inspect(self, crate_path: Path) -> tuple[bool, str | None, str | None]:
        
        command = [self._executable, "inspect", str(crate_path)]

        try:
            master_fd, slave_fd = pty.openpty()
            terminal_size = shutil.get_terminal_size(fallback=(120, 40))
            winsize = struct.pack("HHHH", terminal_size.lines, terminal_size.columns, 0, 0 )
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
        except OSError as exc:
            return False, None, f"pycompss inspect PTY allocation failed: {exc}"

        try:
            process = subprocess.Popen( command, stdin=slave_fd, stdout=slave_fd,stderr=slave_fd,close_fds=True)
        except FileNotFoundError:
            os.close(master_fd)
            os.close(slave_fd)
            return False, None, "pycompss inspect unavailable: executable 'pycompss' not found"
        except OSError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            return False, None, f"pycompss inspect could not be executed: {exc}"

        os.close(slave_fd)

        chunks: list[bytes] = []
        try:
            while True:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass

        return_code = process.wait()
        output = b"".join(chunks).decode("utf-8", errors="replace").rstrip()

        if return_code == 0:
            return True, output or None, None

        details = output or "no diagnostic output"
        return False, output or None, f"pycompss inspect failed (exit code {return_code}): {details}"