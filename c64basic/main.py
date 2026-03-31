#!/usr/bin/env python3
"""
C64 BASIC V2 Interpreter & Editor
Entry point – supports both interactive (curses) and headless modes.

Usage:
  python -m c64basic            # interactive editor (curses)
  python -m c64basic prog.bas   # load and run a .bas file
  python -m c64basic --text     # plain-text REPL (no curses)
"""

import sys
import os
import re
import argparse


def _run_file_headless(filename: str):
    """Load and run a BASIC file without curses."""
    from .interpreter import Interpreter, InterpreterState, _run_program, BasicError

    state  = InterpreterState()
    interp = Interpreter(state)

    def _input_fn(prompt):
        sys.stdout.write(prompt)
        sys.stdout.flush()
        return input()

    state.input_fn = _input_fn

    # Load
    try:
        with open(filename, 'r') as f:
            for line in f:
                line = line.rstrip('\n\r')
                m    = re.match(r'^(\d+) ?(.*)', line)
                if m:
                    state.program[int(m.group(1))] = m.group(2)
    except FileNotFoundError:
        print(f'FILE NOT FOUND: {filename}', file=sys.stderr)
        sys.exit(1)

    try:
        _run_program(interp)
        out = state.flush_output()
        if out:
            sys.stdout.write(out)
    except BasicError as e:
        out = state.flush_output()
        if out:
            sys.stdout.write(out)
        ln = f' IN {state.current_line}' if state.current_line else ''
        print(f'\n?{e.msg} ERROR{ln}', file=sys.stderr)
        sys.exit(1)


def _run_text_repl():
    """Plain-text REPL for environments without curses."""
    from .interpreter import (
        Interpreter, InterpreterState, _run_program,
        BasicError, BasicSyntaxError, BasicRuntimeError, BasicNew,
    )

    state  = InterpreterState()
    interp = Interpreter(state)

    def _input_fn(prompt):
        sys.stdout.write(prompt)
        sys.stdout.flush()
        return input()

    state.input_fn = _input_fn

    print()
    print(' **** COMMODORE 64 BASIC V2 ****')
    print()
    print(' 64K RAM SYSTEM  38911 BASIC BYTES FREE')
    print()
    print('READY.')

    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper() in ('QUIT', 'EXIT', 'BYE'):
            break

        # Line number → store
        # Use ' ?' (at most one space) so extra leading spaces are kept as indentation
        m = re.match(r'^(\d+) ?(.*)', stripped)
        if m:
            ln  = int(m.group(1))
            src = m.group(2).rstrip()   # preserve leading spaces (indentation)
            if src:
                state.program[ln] = src
            elif ln in state.program:
                del state.program[ln]
            continue

        # Direct command
        cmd_upper = stripped.upper()
        try:
            if cmd_upper.startswith('RUN'):
                m2 = re.match(r'RUN\s*(\d+)?', cmd_upper)
                start_ln = int(m2.group(1)) if m2 and m2.group(1) else None
                _run_program(interp, start_ln)
                out = state.flush_output()
                if out:
                    sys.stdout.write(out)
            elif cmd_upper.startswith('LIST'):
                m2 = re.match(r'LIST\s*(\d+)?(?:-(\d+))?', cmd_upper)
                s  = int(m2.group(1)) if m2 and m2.group(1) else None
                e  = int(m2.group(2)) if m2 and m2.group(2) else s
                for ln in state.sorted_lines():
                    if s is not None and ln < s: continue
                    if e is not None and ln > e: break
                    print(f'{ln} {state.program[ln]}')
            elif cmd_upper == 'NEW':
                state.clear_program()
            else:
                interp.exec_line(stripped)
                out = state.flush_output()
                if out:
                    sys.stdout.write(out)
        except BasicNew:
            state.clear_program()
        except (BasicSyntaxError, BasicRuntimeError) as e:
            out = state.flush_output()
            if out:
                sys.stdout.write(out)
            ln_info = f' IN {state.current_line}' if state.current_line else ''
            print(f'?{e.msg} ERROR{ln_info}')
        except Exception as exc:
            out = state.flush_output()
            if out:
                sys.stdout.write(out)
            print(f'?RUNTIME ERROR: {exc}')

        print()
        print('READY.')


def main():
    parser = argparse.ArgumentParser(
        description='Commodore 64 BASIC V2 Interpreter & Editor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('file',     nargs='?', help='.bas file to load and run')
    parser.add_argument('--text',   action='store_true', help='Plain-text REPL (no curses)')
    parser.add_argument('--run',    action='store_true', help='Run file immediately (with --file)')
    args = parser.parse_args()

    if args.file:
        _run_file_headless(args.file)
    elif args.text:
        _run_text_repl()
    else:
        # Launch curses editor
        try:
            from .editor import Editor
            ed = Editor()
            # If a file was specified, pre-load it
            ed.run()
        except Exception as e:
            # Fall back to text REPL if curses fails
            print(f'Curses unavailable ({e}), falling back to text mode.')
            _run_text_repl()


if __name__ == '__main__':
    main()
