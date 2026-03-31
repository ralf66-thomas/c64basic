#!/usr/bin/env python3
"""
Commodore 64 BASIC Editor
Provides a curses-based screen editor that mimics the C64 feel:
  - Blue border, blue background, light blue text (classic C64 palette)
  - 40-column display (or wider for modern convenience)
  - Screen editor: cursor movement, line editing, ENTER to execute/store
  - Direct-mode commands: LIST, RUN, NEW, LOAD, SAVE, etc.
"""

import curses
import curses.ascii
import sys
import os
import re

from .interpreter import (
    Interpreter, InterpreterState, BasicError, BasicRuntimeError,
    BasicSyntaxError, BasicEnd, BasicStop, BasicNew,
    _run_program,
)

# ─────────────────────────────────────────────────────────────────────────────
# C64 Colour approximations (curses colour pairs)
# ─────────────────────────────────────────────────────────────────────────────

# Pair numbers
PAIR_NORMAL   = 1   # light blue on blue  (main text)
PAIR_BORDER   = 2   # light blue on black (border)
PAIR_REVERSE  = 3   # blue on light blue  (reverse/highlight)
PAIR_STATUS   = 4   # black on light blue (status bar)
PAIR_ERROR    = 5   # yellow on red

C64_BORDER_CHAR = ' '   # solid block for border


# ─────────────────────────────────────────────────────────────────────────────
# Screen layout constants
# ─────────────────────────────────────────────────────────────────────────────

BORDER_W  = 2    # border width (cols)
BORDER_H  = 1    # border height (rows)
STATUS_H  = 1    # bottom status bar height

# C64 was 40×25 but we allow full terminal width


# ─────────────────────────────────────────────────────────────────────────────
# Editor class
# ─────────────────────────────────────────────────────────────────────────────

class Editor:
    def __init__(self):
        self.interp    = Interpreter()
        self.state     = self.interp.state

        # Screen buffer: list of strings (lines of output + editing area)
        self.screen_lines: list  = []   # strings shown on screen
        self.input_line: str     = ''   # current input being typed
        self.cursor_x: int       = 0    # position in input_line
        self.scroll_offset: int  = 0    # first visible screen_line index

        self.history: list       = []   # command history
        self.hist_idx: int       = -1

        self.running: bool       = False

        # Inject input function so interpreter can ask for input
        self.state.input_fn      = self._interpreter_input_fn
        self._pending_input: str = None   # set when interpreter requests input
        self._input_prompt: str  = ''

        self._stdscr             = None
        self._rows               = 25
        self._cols               = 80
        self._text_rows          = 23   # rows available for text
        self._text_cols          = 40   # C64 default

    # ─────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────────────────────

    def run(self):
        curses.wrapper(self._main)

    def _main(self, stdscr):
        self._stdscr = stdscr
        self._setup_curses()
        self._draw_all()
        self._show_banner()
        self._event_loop()

    def _setup_curses(self):
        curses.start_color()
        curses.use_default_colors()

        # Try to define C64-like colours
        # C64 background: dark blue (#352879 ~ color 4)
        # C64 text: light blue (#6C5EB5 ~ bright cyan)
        # We approximate with terminal colours
        try:
            # C64 classic: blue background, light blue/cyan text
            curses.init_pair(PAIR_NORMAL,  curses.COLOR_CYAN,   curses.COLOR_BLUE)
            curses.init_pair(PAIR_BORDER,  curses.COLOR_CYAN,   curses.COLOR_BLUE)
            curses.init_pair(PAIR_REVERSE, curses.COLOR_BLUE,   curses.COLOR_CYAN)
            curses.init_pair(PAIR_STATUS,  curses.COLOR_BLACK,  curses.COLOR_CYAN)
            curses.init_pair(PAIR_ERROR,   curses.COLOR_YELLOW, curses.COLOR_RED)
        except Exception:
            curses.init_pair(PAIR_NORMAL,  -1, -1)
            curses.init_pair(PAIR_BORDER,  -1, -1)
            curses.init_pair(PAIR_REVERSE, -1, -1)
            curses.init_pair(PAIR_STATUS,  -1, -1)
            curses.init_pair(PAIR_ERROR,   -1, -1)

        curses.noecho()
        curses.cbreak()
        curses.curs_set(1)
        self._stdscr.keypad(True)
        self._stdscr.timeout(100)   # ms; for non-blocking getch

        self._rows, self._cols = self._stdscr.getmaxyx()
        # Text area: full width minus border, but cap at 80 cols
        self._text_rows = self._rows - BORDER_H * 2 - STATUS_H
        self._text_cols = min(self._cols - BORDER_W * 2, 80)

    # ─────────────────────────────────────────────────────────────────────────
    # Drawing
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_all(self):
        self._stdscr.erase()
        self._draw_border()
        self._draw_text_area()
        self._draw_input_line()
        self._draw_status()
        self._stdscr.refresh()

    def _draw_border(self):
        attr = curses.color_pair(PAIR_BORDER) | curses.A_BOLD
        # Top border
        for c in range(self._cols):
            self._safe_addch(0, c, ' ', attr)
        # Bottom border (above status)
        for c in range(self._cols):
            self._safe_addch(self._rows - STATUS_H - 1, c, ' ', attr)
        # Left/right borders
        for r in range(1, self._rows - STATUS_H - 1):
            for c in range(BORDER_W):
                self._safe_addch(r, c, ' ', attr)
            for c in range(self._cols - BORDER_W, self._cols):
                self._safe_addch(r, c, ' ', attr)

    def _draw_text_area(self):
        attr      = curses.color_pair(PAIR_NORMAL)
        text_attr = curses.color_pair(PAIR_NORMAL) | curses.A_BOLD

        # Fill text area with blue background
        for r in range(self._text_rows):
            screen_r = r + BORDER_H
            for c in range(self._text_cols):
                self._safe_addch(screen_r, c + BORDER_W, ' ', attr)

        # Draw visible screen_lines
        total  = len(self.screen_lines)
        # Auto-scroll so latest lines are visible
        visible_lines = self._text_rows - 1  # leave one line for input
        if total > visible_lines:
            self.scroll_offset = total - visible_lines

        for i in range(visible_lines):
            line_idx = self.scroll_offset + i
            if line_idx < total:
                line = self.screen_lines[line_idx]
            else:
                line = ''
            self._draw_text_row(i + BORDER_H, line, text_attr)

    def _draw_text_row(self, screen_row: int, text: str, attr):
        col = BORDER_W
        for ch in text[:self._text_cols]:
            self._safe_addch(screen_row, col, ch, attr)
            col += 1
        # Pad rest of row
        while col < BORDER_W + self._text_cols:
            self._safe_addch(screen_row, col, ' ', curses.color_pair(PAIR_NORMAL))
            col += 1

    def _draw_input_line(self):
        row  = BORDER_H + self._text_rows - 1
        attr = curses.color_pair(PAIR_NORMAL) | curses.A_BOLD

        # Prompt
        prompt = ''
        display = (prompt + self.input_line)[:self._text_cols]
        self._draw_text_row(row, display, attr)

        # Position cursor
        cx = len(prompt) + self.cursor_x
        self._safe_move(row, BORDER_W + min(cx, self._text_cols - 1))

    def _draw_status(self):
        attr = curses.color_pair(PAIR_STATUS) | curses.A_BOLD
        row  = self._rows - STATUS_H
        fn_keys = ' F1:LIST  F3:RUN  F5:LOAD  F7:SAVE  ESC:STOP '
        status  = fn_keys.ljust(self._cols)[:self._cols]
        for i, ch in enumerate(status):
            if i < self._cols - 1:
                self._safe_addch(row, i, ch, attr)

    def _safe_addch(self, r, c, ch, attr):
        try:
            if 0 <= r < self._rows and 0 <= c < self._cols:
                self._stdscr.addch(r, c, ch, attr)
        except curses.error:
            pass

    def _safe_move(self, r, c):
        try:
            r = max(0, min(r, self._rows - 1))
            c = max(0, min(c, self._cols - 1))
            self._stdscr.move(r, c)
        except curses.error:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Output helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _append_output(self, text: str):
        """Append text to screen_lines, handling newlines."""
        if not text:
            return
        lines = text.split('\n')
        if self.screen_lines and not text.startswith('\n'):
            # Append first chunk to last line
            self.screen_lines[-1] += lines[0]
        else:
            self.screen_lines.append(lines[0])
        for line in lines[1:]:
            self.screen_lines.append(line)
        # Trim long history
        if len(self.screen_lines) > 500:
            self.screen_lines = self.screen_lines[-400:]

    def _println(self, text: str = ''):
        self._append_output(text + '\n')

    # ─────────────────────────────────────────────────────────────────────────
    # Banner
    # ─────────────────────────────────────────────────────────────────────────

    def _show_banner(self):
        self._println()
        self._println(' **** COMMODORE 64 BASIC V2 ****')
        self._println()
        self._println(' 64K RAM SYSTEM  38911 BASIC BYTES FREE')
        self._println()
        self._println('READY.')
        self._println()
        self._draw_all()

    # ─────────────────────────────────────────────────────────────────────────
    # Event loop
    # ─────────────────────────────────────────────────────────────────────────

    def _event_loop(self):
        while True:
            self._draw_all()
            key = self._stdscr.getch()

            if key == -1:
                continue

            # Resize
            if key == curses.KEY_RESIZE:
                self._rows, self._cols = self._stdscr.getmaxyx()
                self._text_rows = self._rows - BORDER_H * 2 - STATUS_H
                self._text_cols = min(self._cols - BORDER_W * 2, 80)
                continue

            # ESC = break / stop
            if key == 27:
                self._println('BREAK')
                self.input_line = ''
                self.cursor_x   = 0
                continue

            # Function keys
            if key == curses.KEY_F1:
                self._execute('LIST')
                continue
            if key == curses.KEY_F3:
                self._execute('RUN')
                continue
            if key == curses.KEY_F5:
                self._execute('LOAD')
                continue
            if key == curses.KEY_F7:
                self._execute('SAVE')
                continue

            # Navigation
            if key == curses.KEY_UP:
                if self.hist_idx < len(self.history) - 1:
                    self.hist_idx   += 1
                    self.input_line  = self.history[-(self.hist_idx + 1)]
                    self.cursor_x    = len(self.input_line)
                continue
            if key == curses.KEY_DOWN:
                if self.hist_idx > 0:
                    self.hist_idx   -= 1
                    self.input_line  = self.history[-(self.hist_idx + 1)]
                    self.cursor_x    = len(self.input_line)
                elif self.hist_idx == 0:
                    self.hist_idx   = -1
                    self.input_line = ''
                    self.cursor_x   = 0
                continue
            if key == curses.KEY_LEFT:
                self.cursor_x = max(0, self.cursor_x - 1)
                continue
            if key == curses.KEY_RIGHT:
                self.cursor_x = min(len(self.input_line), self.cursor_x + 1)
                continue
            if key == curses.KEY_HOME:
                self.cursor_x = 0
                continue
            if key == curses.KEY_END:
                self.cursor_x = len(self.input_line)
                continue
            if key == curses.KEY_PPAGE:   # page up: scroll
                self.scroll_offset = max(0, self.scroll_offset - (self._text_rows - 2))
                continue
            if key == curses.KEY_NPAGE:   # page down: scroll
                max_scroll = max(0, len(self.screen_lines) - (self._text_rows - 1))
                self.scroll_offset = min(max_scroll, self.scroll_offset + (self._text_rows - 2))
                continue

            # Delete / Backspace
            if key in (curses.KEY_BACKSPACE, 127, 8):
                if self.cursor_x > 0:
                    self.input_line = self.input_line[:self.cursor_x - 1] + self.input_line[self.cursor_x:]
                    self.cursor_x  -= 1
                continue
            if key == curses.KEY_DC:
                if self.cursor_x < len(self.input_line):
                    self.input_line = self.input_line[:self.cursor_x] + self.input_line[self.cursor_x + 1:]
                continue

            # ENTER
            if key in (10, 13, curses.KEY_ENTER):
                line = self.input_line
                self.input_line = ''
                self.cursor_x   = 0
                self.hist_idx   = -1
                if line.strip():
                    self.history.append(line)
                self._handle_enter(line)
                continue

            # Printable character
            if 32 <= key <= 126:
                ch = chr(key)
                self.input_line = (self.input_line[:self.cursor_x] + ch +
                                   self.input_line[self.cursor_x:])
                self.cursor_x  += 1
                continue

    # ─────────────────────────────────────────────────────────────────────────
    # Handle ENTER key
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_enter(self, line: str):
        """Process a line entered by the user."""
        stripped = line.strip()
        if not stripped:
            self._println()
            return

        # Echo the line
        self._println(stripped)

        # Check if it starts with a line number → store/delete program line
        # Use ' ?' (at most one space) so extra leading spaces are kept as indentation
        m = re.match(r'^(\d+) ?(.*)', stripped)
        if m:
            ln  = int(m.group(1))
            src = m.group(2).rstrip()   # preserve leading spaces (indentation)
            if src:
                self.state.program[ln] = src
            elif ln in self.state.program:
                del self.state.program[ln]
            # No output for storing a line (C64 behaviour)
            return

        # Direct command
        self._execute(stripped)

    def _execute(self, cmd: str):
        """Execute a direct-mode BASIC command or expression."""
        cmd_upper = cmd.strip().upper()

        # Quit command (not in C64 BASIC but useful here)
        if cmd_upper in ('QUIT', 'EXIT', 'BYE'):
            curses.endwin()
            sys.exit(0)

        try:
            # Handle LIST specially to stream output
            if cmd_upper.startswith('LIST'):
                self._do_list_cmd(cmd)
                return
            if cmd_upper == 'NEW':
                self.state.clear_program()
                self._println('NEW')
                self._println()
                self._println('READY.')
                return
            if cmd_upper == 'CLR':
                self.state.clr()
                self._println()
                self._println('READY.')
                return
            if cmd_upper.startswith('RUN'):
                self._do_run_cmd(cmd)
                return
            if cmd_upper.startswith('LOAD'):
                self._do_load_cmd(cmd)
                return
            if cmd_upper.startswith('SAVE'):
                self._do_save_cmd(cmd)
                return
            if cmd_upper == 'CONT':
                self._do_cont_cmd()
                return

            # Generic execution via interpreter
            self.interp.exec_line(cmd)
            out = self.state.flush_output()
            if out:
                self._append_output(out)

        except BasicNew:
            self.state.clear_program()
            self._println()
            self._println('READY.')
            return
        except (BasicSyntaxError, BasicRuntimeError) as e:
            self._println(f'?{e.msg} ERROR')
        except BasicError as e:
            self._println(f'?{e.msg} ERROR')
        except Exception as e:
            self._println(f'?SYNTAX  ERROR')

        self._println()
        self._println('READY.')

    # ─────────────────────────────────────────────────────────────────────────
    # Command handlers
    # ─────────────────────────────────────────────────────────────────────────

    def _do_list_cmd(self, cmd: str):
        """LIST [start[-end]]"""
        m = re.match(r'LIST\s*(\d+)?(?:-(\d+))?', cmd.strip().upper())
        start_ln = int(m.group(1)) if m and m.group(1) else None
        end_ln   = int(m.group(2)) if m and m.group(2) else start_ln

        lines = self.state.sorted_lines()
        if not lines:
            self._println()
            self._println('READY.')
            return

        for ln in lines:
            if start_ln is not None and ln < start_ln:
                continue
            if end_ln is not None and ln > end_ln:
                break
            self._println(f'{ln} {self.state.program[ln]}')
        self._println()
        self._println('READY.')

    def _do_run_cmd(self, cmd: str):
        """RUN [line]"""
        m = re.match(r'RUN\s*(\d+)?', cmd.strip().upper())
        start_ln = int(m.group(1)) if m and m.group(1) else None

        if not self.state.program:
            self._println()
            self._println('READY.')
            return

        try:
            _run_program(self.interp, start_ln)
        except BasicNew:
            self.state.clear_program()
        except (BasicSyntaxError, BasicRuntimeError) as e:
            out = self.state.flush_output()
            if out:
                self._append_output(out)
            ln_info = f' IN {self.state.current_line}' if self.state.current_line else ''
            self._println(f'?{e.msg} ERROR{ln_info}')
        except Exception as e:
            out = self.state.flush_output()
            if out:
                self._append_output(out)
            self._println(f'?RUNTIME ERROR: {e}')

        out = self.state.flush_output()
        if out:
            self._append_output(out)
        self._println()
        self._println('READY.')

    def _do_load_cmd(self, cmd: str):
        """LOAD "filename" """
        m = re.search(r'"([^"]+)"', cmd)
        if not m:
            # Prompt for filename
            self._println('?MISSING FILENAME')
            self._println()
            self._println('READY.')
            return
        filename = m.group(1)
        if not filename.endswith('.bas'):
            filename += '.bas'
        try:
            self.state.program.clear()
            with open(filename, 'r') as f:
                for line in f:
                    line = line.rstrip('\n\r')
                    lm = re.match(r'^(\d+) ?(.*)', line)
                    if lm:
                        self.state.program[int(lm.group(1))] = lm.group(2)
            self._println(f'LOADING {filename}')
            self._println()
            self._println('READY.')
        except FileNotFoundError:
            self._println('?FILE NOT FOUND  ERROR')
            self._println()
            self._println('READY.')

    def _do_save_cmd(self, cmd: str):
        """SAVE "filename" """
        m = re.search(r'"([^"]+)"', cmd)
        if not m:
            self._println('?MISSING FILENAME')
            self._println()
            self._println('READY.')
            return
        filename = m.group(1)
        if not filename.endswith('.bas'):
            filename += '.bas'
        try:
            with open(filename, 'w') as f:
                for ln in self.state.sorted_lines():
                    f.write(f'{ln} {self.state.program[ln]}\n')
            self._println(f'SAVING {filename}')
            self._println()
            self._println('READY.')
        except IOError as e:
            self._println(f'?I/O ERROR: {e}')
            self._println()
            self._println('READY.')

    def _do_cont_cmd(self):
        if self.state.stopped_line is None:
            self._println("?CAN'T CONTINUE  ERROR")
            self._println()
            self._println('READY.')
            return
        try:
            # Re-run from stopped line
            _run_program(self.interp, self.state.stopped_line)
        except (BasicSyntaxError, BasicRuntimeError) as e:
            out = self.state.flush_output()
            if out:
                self._append_output(out)
            self._println(f'?{e.msg} ERROR')
        out = self.state.flush_output()
        if out:
            self._append_output(out)
        self._println()
        self._println('READY.')

    # ─────────────────────────────────────────────────────────────────────────
    # Interpreter input callback
    # ─────────────────────────────────────────────────────────────────────────

    def _interpreter_input_fn(self, prompt_output: str) -> str:
        """Called by the interpreter when it needs user input."""
        # Show any pending output first
        if prompt_output:
            self._append_output(prompt_output)
        self._draw_all()

        # Switch input_line to input mode
        saved_line   = self.input_line
        saved_cursor = self.cursor_x
        self.input_line = ''
        self.cursor_x   = 0

        result = ''
        while True:
            self._draw_all()
            key = self._stdscr.getch()
            if key == -1:
                continue
            if key in (10, 13, curses.KEY_ENTER):
                result = self.input_line
                self._println(self.input_line)
                self.input_line = ''
                self.cursor_x   = 0
                break
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if self.cursor_x > 0:
                    self.input_line = self.input_line[:self.cursor_x - 1] + self.input_line[self.cursor_x:]
                    self.cursor_x  -= 1
            elif key == curses.KEY_LEFT:
                self.cursor_x = max(0, self.cursor_x - 1)
            elif key == curses.KEY_RIGHT:
                self.cursor_x = min(len(self.input_line), self.cursor_x + 1)
            elif key == 27:  # ESC = abort
                result = ''
                break
            elif 32 <= key <= 126:
                ch = chr(key)
                self.input_line = (self.input_line[:self.cursor_x] + ch +
                                   self.input_line[self.cursor_x:])
                self.cursor_x += 1

        # Restore any partial input
        self.input_line = saved_line
        self.cursor_x   = saved_cursor
        return result
