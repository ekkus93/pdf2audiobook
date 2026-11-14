#!/usr/bin/env python3
"""Run a command with IPv4 and IPv6 sockets refused for it and everything it starts (spec D8.d).

    python3 desktop/scripts/no_network.py [--report FILE] -- COMMAND [ARGS...]

A seccomp filter (through libseccomp, no privileges needed) makes `socket()` fail with EACCES
for AF_INET and AF_INET6. The filter is inherited by every child, so it covers WebKit's helper
processes and the CLI too. Unix sockets (X11, D-Bus, audio) still work. Used by the desktop
app's no-network check: the app must do its offline work with no network at all.

`--report FILE` writes the command's exit code to FILE as JSON when it ends.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import os
import socket
import sys

SCMP_ACT_ALLOW = 0x7FFF0000
SCMP_ACT_ERRNO = 0x00050000
EACCES = 13
SCMP_CMP_EQ = 4


class ArgCmp(ctypes.Structure):
    _fields_ = [
        ("arg", ctypes.c_uint),
        ("op", ctypes.c_int),
        ("datum_a", ctypes.c_uint64),
        ("datum_b", ctypes.c_uint64),
    ]


def block_inet() -> None:
    """Installs the filter on this process; it survives exec and fork."""
    name = ctypes.util.find_library("seccomp") or "libseccomp.so.2"
    lib = ctypes.CDLL(name, use_errno=True)
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add_array.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(ArgCmp),
    ]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(SCMP_ACT_ALLOW)
    if not context:
        raise SystemExit("seccomp_init failed")
    for call in (b"socket", b"socketpair"):
        number = lib.seccomp_syscall_resolve_name(call)
        for family in (socket.AF_INET, socket.AF_INET6):
            rule = ArgCmp(0, SCMP_CMP_EQ, family, 0)
            if lib.seccomp_rule_add_array(context, SCMP_ACT_ERRNO | EACCES, number, 1, ctypes.byref(rule)):
                raise SystemExit("seccomp_rule_add failed")
    if lib.seccomp_load(context):
        raise SystemExit("seccomp_load failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    command = options.command[1:] if options.command[:1] == ["--"] else options.command
    if not command:
        parser.error("a command is required")
    block_inet()
    # Prove the filter is in force before handing over.
    try:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).close()
    except PermissionError:
        pass
    else:
        raise SystemExit("the filter did not block IPv4 sockets")
    if not options.report:
        os.execvp(command[0], command)
    pid = os.fork()
    if pid == 0:
        os.execvp(command[0], command)
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    with open(options.report, "w", encoding="utf-8") as report:
        report.write(f'{{"exit_code": {code}}}\n')
    return code


if __name__ == "__main__":
    sys.exit(main())
