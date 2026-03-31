#!/usr/bin/env python3
"""
Commodore 64 BASIC V2 Interpreter
Implements full C64 BASIC V2 compatibility including:
  - All standard statements and functions
  - FOR/NEXT with proper stack semantics
  - GOSUB/RETURN stack
  - DATA/READ/RESTORE
  - String and numeric operations
  - Logical operators returning -1/0 (C64 TRUE/FALSE)
"""

import math
import random
import os
import sys
import time
import re

from .lexer import (
    Lexer, Token, LexError,
    TT_NUMBER, TT_STRING, TT_IDENT, TT_KEYWORD,
    TT_PLUS, TT_MINUS, TT_MUL, TT_DIV, TT_POW,
    TT_LPAREN, TT_RPAREN, TT_COMMA, TT_SEMICOLON, TT_COLON,
    TT_EQ, TT_LT, TT_GT, TT_LE, TT_GE, TT_NE, TT_EOF,
)

# ─────────────────────────────────────────────────────────────────────────────
# Exceptions used as control flow
# ─────────────────────────────────────────────────────────────────────────────

class BasicError(Exception):
    def __init__(self, msg, line=None):
        self.msg  = msg
        self.line = line
        super().__init__(msg)

class BasicSyntaxError(BasicError):  pass
class BasicRuntimeError(BasicError): pass
class BasicStop(Exception):          pass   # STOP statement
class BasicEnd(Exception):           pass   # END statement
class BasicNew(Exception):           pass   # NEW command during run


# ─────────────────────────────────────────────────────────────────────────────
# Helper: format a number like C64 BASIC does
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_number(n: float) -> str:
    """Format a number the way C64 BASIC prints it."""
    if n == int(n) and abs(n) < 1e10:
        i = int(n)
        return (' ' if i >= 0 else '') + str(i)
    # Use Python's repr-style but trim trailing zeros
    s = f'{n:.9G}'
    # Add leading space for positive numbers
    if not s.startswith('-'):
        s = ' ' + s
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Token-stream helper
# ─────────────────────────────────────────────────────────────────────────────

class TokenStream:
    def __init__(self, tokens):
        self._tokens = tokens
        self._pos    = 0

    def peek(self) -> Token:
        return self._tokens[self._pos]

    def peek_type(self) -> str:
        return self._tokens[self._pos].type

    def peek_value(self):
        return self._tokens[self._pos].value

    def advance(self) -> Token:
        t = self._tokens[self._pos]
        if t.type != TT_EOF:
            self._pos += 1
        return t

    def at_end(self) -> bool:
        return self._tokens[self._pos].type == TT_EOF

    def match(self, *types) -> bool:
        return self._tokens[self._pos].type in types

    def match_kw(self, *kws) -> bool:
        t = self._tokens[self._pos]
        return t.type == TT_KEYWORD and t.value in kws

    def expect(self, ttype: str) -> Token:
        t = self.advance()
        if t.type != ttype:
            raise BasicSyntaxError(f'Expected {ttype}, got {t.type}({t.value!r})')
        return t

    def expect_kw(self, kw: str) -> Token:
        t = self.advance()
        if t.type != TT_KEYWORD or t.value != kw:
            raise BasicSyntaxError(f'Expected keyword {kw!r}, got {t!r}')
        return t

    def save(self) -> int:
        return self._pos

    def restore(self, pos: int):
        self._pos = pos


# ─────────────────────────────────────────────────────────────────────────────
# Expression Parser (recursive descent)
# ─────────────────────────────────────────────────────────────────────────────

class ExprParser:
    """Parse and evaluate expressions from a TokenStream against a given state."""

    def __init__(self, ts: TokenStream, state: 'InterpreterState'):
        self.ts    = ts
        self.state = state

    # ── entry point ──────────────────────────────────────────────────────────

    def parse(self):
        return self._or_expr()

    # ── grammar ──────────────────────────────────────────────────────────────

    def _or_expr(self):
        left = self._and_expr()
        while self.ts.match_kw('OR'):
            self.ts.advance()
            right = self._and_expr()
            left  = -1 if (self._truthy(left) or self._truthy(right)) else 0
        return left

    def _and_expr(self):
        left = self._not_expr()
        while self.ts.match_kw('AND'):
            self.ts.advance()
            right = self._not_expr()
            left  = -1 if (self._truthy(left) and self._truthy(right)) else 0
        return left

    def _not_expr(self):
        if self.ts.match_kw('NOT'):
            self.ts.advance()
            val = self._not_expr()
            return 0 if self._truthy(val) else -1
        return self._compare_expr()

    def _compare_expr(self):
        left = self._add_expr()
        while self.ts.match(TT_EQ, TT_LT, TT_GT, TT_LE, TT_GE, TT_NE):
            op    = self.ts.advance().type
            right = self._add_expr()
            # Comparisons return -1 (true) or 0 (false) like C64
            if isinstance(left, str) or isinstance(right, str):
                ls, rs = str(left), str(right)
                result = (op == TT_EQ and ls == rs) or \
                         (op == TT_LT and ls  < rs) or \
                         (op == TT_GT and ls  > rs) or \
                         (op == TT_LE and ls <= rs) or \
                         (op == TT_GE and ls >= rs) or \
                         (op == TT_NE and ls != rs)
            else:
                result = (op == TT_EQ and left == right) or \
                         (op == TT_LT and left  < right) or \
                         (op == TT_GT and left  > right) or \
                         (op == TT_LE and left <= right) or \
                         (op == TT_GE and left >= right) or \
                         (op == TT_NE and left != right)
            left = -1 if result else 0
        return left

    def _add_expr(self):
        left = self._mul_expr()
        while self.ts.match(TT_PLUS, TT_MINUS):
            op    = self.ts.advance().type
            right = self._mul_expr()
            if op == TT_PLUS:
                if isinstance(left, str) or isinstance(right, str):
                    left = str(left) + str(right)
                else:
                    left = left + right
            else:
                left = left - right
        return left

    def _mul_expr(self):
        left = self._pow_expr()
        while self.ts.match(TT_MUL, TT_DIV):
            op    = self.ts.advance().type
            right = self._pow_expr()
            if op == TT_MUL:
                left = left * right
            else:
                if right == 0:
                    raise BasicRuntimeError('DIVISION BY ZERO')
                left = left / right
        return left

    def _pow_expr(self):
        base = self._unary()
        if self.ts.match(TT_POW):
            self.ts.advance()
            exp = self._unary()
            return base ** exp
        return base

    def _unary(self):
        if self.ts.match(TT_MINUS):
            self.ts.advance()
            return -self._unary()
        if self.ts.match(TT_PLUS):
            self.ts.advance()
            return self._unary()
        return self._primary()

    # ── primary ──────────────────────────────────────────────────────────────

    def _primary(self):
        t = self.ts.peek()

        if t.type == TT_NUMBER:
            self.ts.advance()
            return t.value

        if t.type == TT_STRING:
            self.ts.advance()
            return t.value

        if t.type == TT_LPAREN:
            self.ts.advance()
            val = self.parse()
            self.ts.expect(TT_RPAREN)
            return val

        if t.type == TT_KEYWORD:
            return self._builtin_func()

        if t.type == TT_IDENT:
            return self._variable_or_array()

        raise BasicSyntaxError(f'Unexpected token in expression: {t!r}')

    # ── variable / array access ───────────────────────────────────────────────

    def _variable_or_array(self) -> object:
        name = self.ts.advance().value  # IDENT token
        if self.ts.match(TT_LPAREN):
            # Array access
            self.ts.advance()
            indices = [self.parse()]
            while self.ts.match(TT_COMMA):
                self.ts.advance()
                indices.append(self.parse())
            self.ts.expect(TT_RPAREN)
            return self.state.get_array_element(name, tuple(int(i) for i in indices))
        return self.state.get_variable(name)

    # ── built-in functions ────────────────────────────────────────────────────

    def _builtin_func(self) -> object:
        kw = self.ts.peek().value

        # ── numeric functions ──────────────────────────────────────────
        if kw == 'ABS':
            return abs(self._single_arg())
        if kw == 'INT':
            return float(math.floor(self._single_arg()))
        if kw == 'SGN':
            v = self._single_arg()
            return -1.0 if v < 0 else (1.0 if v > 0 else 0.0)
        if kw == 'SQR':
            v = self._single_arg()
            if v < 0:
                raise BasicRuntimeError('ILLEGAL QUANTITY')
            return math.sqrt(v)
        if kw == 'SIN':
            return math.sin(self._single_arg())
        if kw == 'COS':
            return math.cos(self._single_arg())
        if kw == 'TAN':
            return math.tan(self._single_arg())
        if kw == 'ATN':
            return math.atan(self._single_arg())
        if kw == 'EXP':
            return math.exp(self._single_arg())
        if kw == 'LOG':
            v = self._single_arg()
            if v <= 0:
                raise BasicRuntimeError('ILLEGAL QUANTITY')
            return math.log(v)
        if kw == 'RND':
            v = self._single_arg()
            if v > 0:
                return random.random()
            elif v == 0:
                return self.state.last_rnd
            else:  # seed
                random.seed(int(v))
                return random.random()
        if kw == 'PEEK':
            addr = int(self._single_arg())
            return float(self.state.peek_mem(addr))
        if kw == 'FRE':
            self._single_arg()   # consume argument (ignored)
            return 38911.0       # C64 free memory constant
        if kw == 'POS':
            self._single_arg()
            return float(self.state.print_col)
        if kw == 'TI':
            self.ts.advance()    # consume TI keyword (no parens)
            return float(int(time.time() * 60) % 5184000)

        # ── string functions ───────────────────────────────────────────
        if kw == 'LEN':
            return float(len(self._single_arg_str()))
        if kw == 'ASC':
            s = self._single_arg_str()
            if not s:
                raise BasicRuntimeError('ILLEGAL QUANTITY')
            return float(ord(s[0]))
        if kw == 'CHR$':
            n = int(self._single_arg())
            return chr(n)
        if kw == 'STR$':
            v = self._single_arg()
            return _fmt_number(v).lstrip()
        if kw == 'VAL':
            s = self._single_arg_str().strip()
            try:
                return float(s)
            except ValueError:
                return 0.0
        if kw == 'LEFT$':
            s, n = self._two_args_str_num()
            return s[:int(n)]
        if kw == 'RIGHT$':
            s, n = self._two_args_str_num()
            return s[max(0, len(s) - int(n)):]
        if kw == 'MID$':
            self.ts.advance()  # keyword
            self.ts.expect(TT_LPAREN)
            s = self.parse()
            self.ts.expect(TT_COMMA)
            start = int(self.parse()) - 1  # 1-based
            length = None
            if self.ts.match(TT_COMMA):
                self.ts.advance()
                length = int(self.parse())
            self.ts.expect(TT_RPAREN)
            if length is None:
                return s[max(0, start):]
            return s[max(0, start): max(0, start) + length]
        if kw == 'STRING$':
            self.ts.advance()  # keyword
            self.ts.expect(TT_LPAREN)
            n = int(self.parse())
            self.ts.expect(TT_COMMA)
            v = self.parse()
            self.ts.expect(TT_RPAREN)
            if isinstance(v, str):
                ch = v[0] if v else ''
            else:
                ch = chr(int(v))
            return ch * n
        if kw == 'TI$':
            self.ts.advance()
            t   = int(time.time() * 60) % 5184000
            h   = t // 360000
            m   = (t % 360000) // 6000
            s   = (t % 6000) // 100
            return f'{h:02d}{m:02d}{s:02d}'
        if kw == 'SPC':
            n = int(self._single_arg())
            return ' ' * max(0, n)
        if kw == 'TAB':
            n = int(self._single_arg())
            spaces = max(0, n - 1 - self.state.print_col)
            return ' ' * spaces

        # ── user-defined functions (DEF FN) ───────────────────────────
        if kw == 'FN':
            self.ts.advance()  # consume FN
            fn_name = self.ts.expect(TT_IDENT).value
            self.ts.expect(TT_LPAREN)
            arg_val = self.parse()
            self.ts.expect(TT_RPAREN)
            if fn_name not in self.state.user_functions:
                raise BasicRuntimeError(f'UNDEFINED FUNCTION {fn_name}')
            param_name, expr_tokens = self.state.user_functions[fn_name]
            # Evaluate with param bound
            old_val = self.state.variables.get(param_name)
            self.state.variables[param_name] = arg_val
            result = self._eval_tokens(expr_tokens)
            if old_val is None:
                self.state.variables.pop(param_name, None)
            else:
                self.state.variables[param_name] = old_val
            return result

        raise BasicSyntaxError(f'Unknown function: {kw}')

    # ── helpers ───────────────────────────────────────────────────────────────

    def _single_arg(self) -> float:
        self.ts.advance()  # consume keyword
        self.ts.expect(TT_LPAREN)
        v = self.parse()
        self.ts.expect(TT_RPAREN)
        if isinstance(v, str):
            raise BasicRuntimeError('TYPE MISMATCH')
        return float(v)

    def _single_arg_str(self) -> str:
        self.ts.advance()  # consume keyword
        self.ts.expect(TT_LPAREN)
        v = self.parse()
        self.ts.expect(TT_RPAREN)
        if not isinstance(v, str):
            raise BasicRuntimeError('TYPE MISMATCH')
        return v

    def _two_args_str_num(self):
        self.ts.advance()  # consume keyword
        self.ts.expect(TT_LPAREN)
        s = self.parse()
        self.ts.expect(TT_COMMA)
        n = self.parse()
        self.ts.expect(TT_RPAREN)
        return s, float(n)

    def _eval_tokens(self, tokens) -> object:
        """Evaluate a pre-tokenised expression (for DEF FN)."""
        ts_old = self.ts
        self.ts = TokenStream(tokens)
        result  = self.parse()
        self.ts = ts_old
        return result

    @staticmethod
    def _truthy(v) -> bool:
        if isinstance(v, str):
            return v != ''
        return v != 0


# ─────────────────────────────────────────────────────────────────────────────
# Interpreter state
# ─────────────────────────────────────────────────────────────────────────────

class InterpreterState:
    def __init__(self):
        self.program: dict   = {}   # {line_num: raw_text}
        self.variables: dict = {}   # {'A': 1.0, 'A$': 'hello'}
        self.arrays: dict    = {}   # {'A': {(0,): 0.0, ...}, dims: (11,) }
        self.array_dims: dict = {}  # {'A': (11,)} default

        self.data_items: list = []  # flattened DATA values
        self.data_ptr: int    = 0

        self.gosub_stack: list = []  # [(return_line, return_stmt_idx)]
        self.for_stack: list   = []  # ForEntry objects

        self.current_line: int  = None
        self.running: bool      = False
        self.stopped_line: int  = None  # line STOP was hit on
        self.stop_stmt_idx: int = None

        self.print_col: int  = 0    # current cursor column (for , and TAB)
        self.last_rnd: float = 0.0

        self.user_functions: dict = {}  # {'FN_NAME': (param, [tokens])}

        self.output_buffer: list = []   # written to by _print; consumed by UI
        self.input_fn    = None         # callable() -> str, injected by editor

        # Simulated C64 memory (PEEK/POKE)
        self._memory: dict = {}

    # ── memory ────────────────────────────────────────────────────────────────

    def peek_mem(self, addr: int) -> int:
        return self._memory.get(addr, 0)

    def poke_mem(self, addr: int, val: int):
        self._memory[addr] = val & 0xFF

    # ── variables ─────────────────────────────────────────────────────────────

    def get_variable(self, name: str):
        if name not in self.variables:
            # default value: '' for strings, 0.0 for numbers
            return '' if name.endswith('$') else 0.0
        return self.variables[name]

    def set_variable(self, name: str, value):
        if name.endswith('$'):
            if not isinstance(value, str):
                raise BasicRuntimeError('TYPE MISMATCH')
        else:
            if isinstance(value, str):
                raise BasicRuntimeError('TYPE MISMATCH')
            value = float(value)
        self.variables[name] = value

    # ── arrays ────────────────────────────────────────────────────────────────

    def dim_array(self, name: str, dims: tuple):
        """DIM an array. Sizes are upper bounds (0..n inclusive)."""
        if name in self.arrays:
            raise BasicRuntimeError('REDIM\'D ARRAY')
        size = tuple(d + 1 for d in dims)
        self.array_dims[name] = size
        self.arrays[name]     = {}

    def get_array_element(self, name: str, indices: tuple):
        if name not in self.arrays:
            # Auto-DIM with size 11 per dimension
            self.arrays[name]     = {}
            self.array_dims[name] = tuple(11 for _ in indices)
        dims = self.array_dims[name]
        for i, (idx, dim) in enumerate(zip(indices, dims)):
            if idx < 0 or idx >= dim:
                raise BasicRuntimeError('BAD SUBSCRIPT')
        return self.arrays[name].get(indices, '' if name.endswith('$') else 0.0)

    def set_array_element(self, name: str, indices: tuple, value):
        if name not in self.arrays:
            self.arrays[name]     = {}
            self.array_dims[name] = tuple(11 for _ in indices)
        dims = self.array_dims[name]
        for idx, dim in zip(indices, dims):
            if idx < 0 or idx >= dim:
                raise BasicRuntimeError('BAD SUBSCRIPT')
        if name.endswith('$'):
            if not isinstance(value, str):
                raise BasicRuntimeError('TYPE MISMATCH')
        else:
            if isinstance(value, str):
                raise BasicRuntimeError('TYPE MISMATCH')
            value = float(value)
        self.arrays[name][indices] = value

    # ── output ────────────────────────────────────────────────────────────────

    def write_output(self, text: str):
        self.output_buffer.append(text)
        # Track column position
        nl = text.rfind('\n')
        if nl == -1:
            self.print_col += len(text)
        else:
            self.print_col = len(text) - nl - 1

    def flush_output(self) -> str:
        s = ''.join(self.output_buffer)
        self.output_buffer.clear()
        return s

    # ── DATA collection ───────────────────────────────────────────────────────

    def rebuild_data(self):
        """Scan program for DATA statements and build data_items list."""
        self.data_items = []
        for line_num in sorted(self.program):
            text  = self.program[line_num]
            stmts = _split_statements(text)
            for stmt in stmts:
                ts = TokenStream(Lexer(stmt).tokenize())
                if ts.match_kw('DATA'):
                    ts.advance()
                    while not ts.at_end():
                        t = ts.peek()
                        if t.type == TT_NUMBER:
                            self.data_items.append(ts.advance().value)
                        elif t.type == TT_STRING:
                            self.data_items.append(ts.advance().value)
                        elif t.type == TT_MINUS:
                            ts.advance()
                            if ts.peek().type == TT_NUMBER:
                                self.data_items.append(-ts.advance().value)
                        elif t.type == TT_COMMA:
                            ts.advance()
                        else:
                            ts.advance()

    # ── program lines ─────────────────────────────────────────────────────────

    def sorted_lines(self) -> list:
        return sorted(self.program.keys())

    def clear_program(self):
        self.program.clear()
        self.clr()

    def clr(self):
        """CLR – clear variables but keep program."""
        self.variables.clear()
        self.arrays.clear()
        self.array_dims.clear()
        self.gosub_stack.clear()
        self.for_stack.clear()
        self.data_ptr   = 0
        self.print_col  = 0
        self.stopped_line = None


# ─────────────────────────────────────────────────────────────────────────────
# FOR/NEXT stack entry
# ─────────────────────────────────────────────────────────────────────────────

class ForEntry:
    __slots__ = ('var', 'limit', 'step', 'line_num', 'stmt_idx')

    def __init__(self, var, limit, step, line_num, stmt_idx):
        self.var      = var
        self.limit    = limit
        self.step     = step
        self.line_num = line_num
        self.stmt_idx = stmt_idx   # index of the FOR stmt in this line's stmt list


# ─────────────────────────────────────────────────────────────────────────────
# Utility: split a raw BASIC line into individual statements on ':'
# (but not splitting inside strings or REM)
# ─────────────────────────────────────────────────────────────────────────────

def _split_statements(text: str) -> list:
    stmts  = []
    buf    = []
    in_str = False
    i      = 0
    # Check if line starts with REM (after optional whitespace)
    stripped = text.strip().upper()
    if stripped.startswith('REM'):
        return [text]
    while i < len(text):
        c = text[i]
        if c == '"':
            in_str = not in_str
            buf.append(c)
        elif c == ':' and not in_str:
            stmts.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    if buf:
        stmts.append(''.join(buf).strip())
    return [s for s in stmts if s]


# ─────────────────────────────────────────────────────────────────────────────
# Main Interpreter
# ─────────────────────────────────────────────────────────────────────────────

class Interpreter:
    def __init__(self, state: InterpreterState = None):
        self.state = state or InterpreterState()

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, start_line: int = None):
        """Run the loaded program from start_line (or first line if None)."""
        self.state.running      = True
        self.state.stopped_line = None
        self.state.rebuild_data()
        self.state.clr()

        lines = self.state.sorted_lines()
        if not lines:
            self.state.running = False
            return

        if start_line is None:
            start_line = lines[0]
        if start_line not in self.state.program:
            raise BasicRuntimeError(f'UNDEFINED LINE {start_line}')

        pc = lines.index(start_line)  # index into sorted lines list
        stmt_idx = 0

        try:
            while pc < len(lines):
                line_num = lines[pc]
                self.state.current_line = line_num
                text  = self.state.program[line_num]
                stmts = _split_statements(text)

                while stmt_idx < len(stmts):
                    result = self._exec_stmt(stmts[stmt_idx], line_num, stmt_idx, stmts)
                    if result is None:
                        stmt_idx += 1
                    elif isinstance(result, tuple):
                        action, *args = result
                        if action == 'goto':
                            target = args[0]
                            if target not in self.state.program:
                                raise BasicRuntimeError(f'UNDEFINED LINE {target}')
                            pc       = lines.index(target)
                            stmt_idx = 0
                            break
                        elif action == 'next_line':
                            break
                        elif action == 'stmt':
                            stmt_idx = args[0]
                    else:
                        stmt_idx += 1
                else:
                    # Fell off end of statements for this line
                    pc       += 1
                    stmt_idx  = 0

        except BasicEnd:
            pass
        except BasicStop as e:
            pass
        finally:
            self.state.running = False

    def exec_line(self, text: str):
        """Execute a single line of BASIC (direct mode)."""
        stmts = _split_statements(text.strip())
        for stmt in stmts:
            self._exec_stmt(stmt, None, 0, stmts)

    # ── statement dispatcher ──────────────────────────────────────────────────

    def _exec_stmt(self, stmt: str, line_num, stmt_idx: int, all_stmts: list):
        """Execute one statement. Returns None (continue), ('goto', n), or ('next_line',)."""
        if not stmt:
            return None
        try:
            ts = TokenStream(Lexer(stmt).tokenize())
        except LexError as e:
            raise BasicSyntaxError(str(e))

        if ts.at_end():
            return None

        t = ts.peek()

        # Optional LET
        if t.type == TT_IDENT or (t.type == TT_KEYWORD and t.value == 'LET'):
            if t.type == TT_KEYWORD and t.value == 'LET':
                ts.advance()
            # Peek ahead: if IDENT followed by = or (, it's assignment
            if ts.peek().type == TT_IDENT:
                saved = ts.save()
                name  = ts.advance().value
                if ts.match(TT_EQ):
                    ts.advance()
                    val = ExprParser(ts, self.state).parse()
                    self.state.set_variable(name, val)
                    return None
                elif ts.match(TT_LPAREN):
                    # Array assignment
                    ts.advance()
                    indices = [ExprParser(ts, self.state).parse()]
                    while ts.match(TT_COMMA):
                        ts.advance()
                        indices.append(ExprParser(ts, self.state).parse())
                    ts.expect(TT_RPAREN)
                    ts.expect(TT_EQ)
                    val = ExprParser(ts, self.state).parse()
                    self.state.set_array_element(name, tuple(int(i) for i in indices), val)
                    return None
                else:
                    ts.restore(saved)

        if t.type != TT_KEYWORD:
            raise BasicSyntaxError(f'Syntax error: {stmt!r}')

        kw = ts.advance().value

        # ── dispatch ──────────────────────────────────────────────────────────
        if kw == 'REM':
            return None

        if kw == 'PRINT':
            return self._do_print(ts)

        if kw == 'INPUT':
            return self._do_input(ts)

        if kw == 'GET':
            return self._do_get(ts)

        if kw == 'IF':
            return self._do_if(ts, line_num, stmt_idx, all_stmts)

        if kw == 'GOTO':
            target = int(ExprParser(ts, self.state).parse())
            return ('goto', target)

        if kw == 'GOSUB':
            target    = int(ExprParser(ts, self.state).parse())
            ret_line  = line_num
            ret_stmt  = stmt_idx + 1
            self.state.gosub_stack.append((ret_line, ret_stmt))
            return ('goto', target)

        if kw == 'RETURN':
            if not self.state.gosub_stack:
                raise BasicRuntimeError('RETURN WITHOUT GOSUB')
            ret_line, ret_stmt = self.state.gosub_stack.pop()
            if ret_line is None:
                raise BasicEnd()
            lines = self.state.sorted_lines()
            if ret_line not in self.state.program:
                raise BasicRuntimeError(f'UNDEFINED LINE {ret_line}')
            # We need to jump to ret_line and stmt ret_stmt
            # Encode as special goto with stmt hint
            return self._jump_to(ret_line, ret_stmt)

        if kw == 'FOR':
            return self._do_for(ts, line_num, stmt_idx)

        if kw == 'NEXT':
            return self._do_next(ts, line_num)

        if kw == 'ON':
            return self._do_on(ts)

        if kw == 'DIM':
            return self._do_dim(ts)

        if kw == 'DATA':
            return None   # already collected by rebuild_data()

        if kw == 'READ':
            return self._do_read(ts)

        if kw == 'RESTORE':
            self.state.data_ptr = 0
            return None

        if kw == 'LET':
            # Handled above by fall-through; if we end up here, syntax error
            raise BasicSyntaxError('SYNTAX ERROR')

        if kw == 'END':
            raise BasicEnd()

        if kw == 'STOP':
            self.state.stopped_line  = line_num
            self.state.stop_stmt_idx = stmt_idx
            raise BasicStop()

        if kw == 'CLR':
            self.state.clr()
            return None

        if kw == 'NEW':
            raise BasicNew()

        if kw == 'LIST':
            self._do_list(ts)
            return None

        if kw == 'RUN':
            # RUN [line] – restart from optional line
            if not ts.at_end():
                target = int(ExprParser(ts, self.state).parse())
            else:
                target = None
            self.run(target)
            return None

        if kw == 'POKE':
            addr = int(ExprParser(ts, self.state).parse())
            ts.expect(TT_COMMA)
            val  = int(ExprParser(ts, self.state).parse())
            self.state.poke_mem(addr, val)
            return None

        if kw == 'DEF':
            return self._do_def(ts)

        if kw == 'SYS':
            ExprParser(ts, self.state).parse()  # consume address (ignored)
            return None

        if kw == 'WAIT':
            addr = int(ExprParser(ts, self.state).parse())
            ts.expect(TT_COMMA)
            ExprParser(ts, self.state).parse()   # mask
            return None

        if kw == 'LOAD':
            return self._do_load(ts)

        if kw == 'SAVE':
            return self._do_save(ts)

        if kw == 'CONT':
            return self._do_cont()

        raise BasicSyntaxError(f'Unknown statement: {kw}')

    # ─────────────────────────────────────────────────────────────── helpers

    def _jump_to(self, line_num, stmt_idx):
        """Return a control token that resumes at (line_num, stmt_idx)."""
        # We encode this as a GOTO with a side-channel for stmt offset
        # Interpreter main loop checks for _pending_stmt
        self._pending_stmt = (line_num, stmt_idx)
        return ('_resume', line_num, stmt_idx)

    # ── PRINT ─────────────────────────────────────────────────────────────────

    def _do_print(self, ts: TokenStream):
        """Execute PRINT (or ?) statement."""
        out     = []
        newline = True

        while not ts.at_end() and not ts.match(TT_COLON):
            if ts.match(TT_SEMICOLON):
                ts.advance()
                newline = True
                continue
            if ts.match(TT_COMMA):
                ts.advance()
                # Advance to next print zone (every 10 chars on C64)
                col    = self.state.print_col + sum(len(s) for s in out)
                spaces = 10 - (col % 10)
                if spaces == 0:
                    spaces = 10
                out.append(' ' * spaces)
                newline = True
                continue
            val = ExprParser(ts, self.state).parse()
            if isinstance(val, float):
                out.append(_fmt_number(val))
            else:
                out.append(str(val))
            newline = True
            # Check what follows
            if ts.match(TT_SEMICOLON):
                ts.advance()
                newline = False
                continue
            if ts.match(TT_COMMA):
                ts.advance()
                col    = self.state.print_col + sum(len(s) for s in out)
                spaces = 10 - (col % 10)
                if spaces == 0:
                    spaces = 10
                out.append(' ' * spaces)
                newline = False
                continue
            break

        line = ''.join(out)
        if newline:
            line += '\n'
        self.state.write_output(line)
        return None

    # ── INPUT ─────────────────────────────────────────────────────────────────

    def _do_input(self, ts: TokenStream):
        prompt = ''
        if ts.peek().type == TT_STRING:
            prompt = ts.advance().value
            if ts.match(TT_SEMICOLON) or ts.match(TT_COMMA):
                ts.advance()

        vars_to_read = []
        while not ts.at_end():
            name = ts.expect(TT_IDENT).value
            if ts.match(TT_LPAREN):
                ts.advance()
                indices = [ExprParser(ts, self.state).parse()]
                while ts.match(TT_COMMA):
                    ts.advance()
                    indices.append(ExprParser(ts, self.state).parse())
                ts.expect(TT_RPAREN)
                vars_to_read.append((name, tuple(int(i) for i in indices)))
            else:
                vars_to_read.append((name, None))
            if ts.match(TT_COMMA):
                ts.advance()

        self.state.write_output(prompt + '? ')
        # Flush so prompt appears before waiting
        raw = self._read_input()
        parts = [p.strip() for p in raw.split(',')]

        for i, (name, idx) in enumerate(vars_to_read):
            val_str = parts[i] if i < len(parts) else ''
            if name.endswith('$'):
                val = val_str
            else:
                try:
                    val = float(val_str)
                except ValueError:
                    val = 0.0
            if idx is None:
                self.state.set_variable(name, val)
            else:
                self.state.set_array_element(name, idx, val)
        return None

    def _do_get(self, ts: TokenStream):
        name = ts.expect(TT_IDENT).value
        # GET reads a single character (non-blocking on C64, blocking here)
        self.state.write_output('')
        ch = self._read_char()
        if name.endswith('$'):
            self.state.set_variable(name, ch)
        else:
            self.state.set_variable(name, float(ord(ch)) if ch else 0.0)
        return None

    def _read_input(self) -> str:
        if self.state.input_fn:
            return self.state.input_fn(self.state.flush_output())
        # flush output first
        sys.stdout.write(self.state.flush_output())
        sys.stdout.flush()
        return input('')

    def _read_char(self) -> str:
        if self.state.input_fn:
            raw = self.state.input_fn(self.state.flush_output())
            return raw[:1] if raw else ''
        sys.stdout.write(self.state.flush_output())
        sys.stdout.flush()
        return input('')[:1]

    # ── IF / THEN ─────────────────────────────────────────────────────────────

    def _do_if(self, ts: TokenStream, line_num, stmt_idx, all_stmts):
        cond = ExprParser(ts, self.state).parse()
        ts.expect_kw('THEN')

        if not cond:
            # skip to next line
            return ('next_line',)

        # THEN linenum  or  THEN statement(s)
        if ts.peek().type == TT_NUMBER:
            target = int(ts.advance().value)
            return ('goto', target)

        # THEN statement
        rest = _tokens_to_text(ts)
        result = self._exec_stmt(rest, line_num, stmt_idx, all_stmts)
        return result

    # ── FOR / NEXT ────────────────────────────────────────────────────────────

    def _do_for(self, ts: TokenStream, line_num: int, stmt_idx: int):
        var   = ts.expect(TT_IDENT).value
        ts.expect(TT_EQ)
        start = ExprParser(ts, self.state).parse()
        ts.expect_kw('TO')
        limit = ExprParser(ts, self.state).parse()
        step  = 1.0
        if ts.match_kw('STEP'):
            ts.advance()
            step = ExprParser(ts, self.state).parse()

        self.state.set_variable(var, float(start))

        # Remove any existing FOR with same variable (re-entrance)
        self.state.for_stack = [f for f in self.state.for_stack if f.var != var]
        self.state.for_stack.append(ForEntry(var, float(limit), float(step), line_num, stmt_idx))
        return None

    def _do_next(self, ts: TokenStream, line_num: int):
        # Optional variable list
        next_vars = []
        while not ts.at_end() and not ts.match(TT_COLON):
            next_vars.append(ts.expect(TT_IDENT).value)
            if ts.match(TT_COMMA):
                ts.advance()

        if not next_vars:
            # Match innermost
            if not self.state.for_stack:
                raise BasicRuntimeError('NEXT WITHOUT FOR')
            entry = self.state.for_stack[-1]
        else:
            var = next_vars[0]
            entries = [e for e in self.state.for_stack if e.var == var]
            if not entries:
                raise BasicRuntimeError('NEXT WITHOUT FOR')
            entry = entries[-1]

        # Increment
        val = self.state.get_variable(entry.var) + entry.step
        self.state.set_variable(entry.var, val)

        # Check loop condition
        if (entry.step > 0 and val <= entry.limit) or \
           (entry.step < 0 and val >= entry.limit) or \
           (entry.step == 0):
            # Loop back: jump to statement AFTER the FOR
            return ('goto_stmt', entry.line_num, entry.stmt_idx + 1)

        # Loop done: pop stack
        self.state.for_stack = [e for e in self.state.for_stack if e is not entry]
        return None

    # ── ON GOTO / ON GOSUB ────────────────────────────────────────────────────

    def _do_on(self, ts: TokenStream):
        idx = int(ExprParser(ts, self.state).parse())
        is_gosub = False
        if ts.match_kw('GOSUB'):
            ts.advance()
            is_gosub = True
        elif ts.match_kw('GOTO'):
            ts.advance()
        else:
            raise BasicSyntaxError('Expected GOTO or GOSUB after ON')

        targets = [int(ExprParser(ts, self.state).parse())]
        while ts.match(TT_COMMA):
            ts.advance()
            targets.append(int(ExprParser(ts, self.state).parse()))

        if idx < 1 or idx > len(targets):
            return None  # out of range: skip

        target = targets[idx - 1]
        if is_gosub:
            self.state.gosub_stack.append((self.state.current_line, 999))
        return ('goto', target)

    # ── DIM ───────────────────────────────────────────────────────────────────

    def _do_dim(self, ts: TokenStream):
        while not ts.at_end():
            name = ts.expect(TT_IDENT).value
            ts.expect(TT_LPAREN)
            dims = [int(ExprParser(ts, self.state).parse())]
            while ts.match(TT_COMMA):
                ts.advance()
                dims.append(int(ExprParser(ts, self.state).parse()))
            ts.expect(TT_RPAREN)
            self.state.dim_array(name, tuple(dims))
            if ts.match(TT_COMMA):
                ts.advance()
        return None

    # ── READ ──────────────────────────────────────────────────────────────────

    def _do_read(self, ts: TokenStream):
        while not ts.at_end() and not ts.match(TT_COLON):
            name = ts.expect(TT_IDENT).value
            idx  = None
            if ts.match(TT_LPAREN):
                ts.advance()
                indices = [ExprParser(ts, self.state).parse()]
                while ts.match(TT_COMMA):
                    ts.advance()
                    indices.append(ExprParser(ts, self.state).parse())
                ts.expect(TT_RPAREN)
                idx = tuple(int(i) for i in indices)

            if self.state.data_ptr >= len(self.state.data_items):
                raise BasicRuntimeError('OUT OF DATA')

            raw = self.state.data_items[self.state.data_ptr]
            self.state.data_ptr += 1

            if name.endswith('$'):
                val = str(raw)
            else:
                try:
                    val = float(raw)
                except (ValueError, TypeError):
                    raise BasicRuntimeError('TYPE MISMATCH')

            if idx is None:
                self.state.set_variable(name, val)
            else:
                self.state.set_array_element(name, idx, val)

            if ts.match(TT_COMMA):
                ts.advance()
        return None

    # ── DEF FN ────────────────────────────────────────────────────────────────

    def _do_def(self, ts: TokenStream):
        ts.expect_kw('FN')
        fn_name = ts.expect(TT_IDENT).value
        ts.expect(TT_LPAREN)
        param   = ts.expect(TT_IDENT).value
        ts.expect(TT_RPAREN)
        ts.expect(TT_EQ)
        # Collect remaining tokens as the expression body (must end with EOF)
        body_tokens = []
        while not ts.at_end():
            body_tokens.append(ts.advance())
        body_tokens.append(Token(TT_EOF, None))
        self.state.user_functions[fn_name] = (param, body_tokens)
        return None

    # ── LIST ──────────────────────────────────────────────────────────────────

    def _do_list(self, ts: TokenStream):
        start_ln = None
        end_ln   = None
        if not ts.at_end() and ts.peek().type == TT_NUMBER:
            start_ln = int(ts.advance().value)
            if ts.match(TT_MINUS):
                ts.advance()
                if not ts.at_end() and ts.peek().type == TT_NUMBER:
                    end_ln = int(ts.advance().value)
            else:
                end_ln = start_ln

        lines = self.state.sorted_lines()
        for ln in lines:
            if start_ln is not None and ln < start_ln:
                continue
            if end_ln is not None and ln > end_ln:
                break
            self.state.write_output(f'{ln} {self.state.program[ln]}\n')

    # ── LOAD / SAVE ───────────────────────────────────────────────────────────

    def _do_load(self, ts: TokenStream):
        filename = ExprParser(ts, self.state).parse()
        if not isinstance(filename, str):
            raise BasicRuntimeError('TYPE MISMATCH')
        self._load_file(filename)
        return None

    def _do_save(self, ts: TokenStream):
        filename = ExprParser(ts, self.state).parse()
        if not isinstance(filename, str):
            raise BasicRuntimeError('TYPE MISMATCH')
        self._save_file(filename)
        return None

    def _load_file(self, filename: str):
        if not filename.endswith('.bas'):
            filename += '.bas'
        try:
            with open(filename, 'r') as f:
                self.state.program.clear()
                for line in f:
                    line = line.rstrip('\n\r')
                    m    = re.match(r'^(\d+) ?(.*)', line)
                    if m:
                        self.state.program[int(m.group(1))] = m.group(2)
        except FileNotFoundError:
            raise BasicRuntimeError(f'FILE NOT FOUND: {filename}')

    def _save_file(self, filename: str):
        if not filename.endswith('.bas'):
            filename += '.bas'
        with open(filename, 'w') as f:
            for ln in self.state.sorted_lines():
                f.write(f'{ln} {self.state.program[ln]}\n')

    # ── CONT ──────────────────────────────────────────────────────────────────

    def _do_cont(self):
        if self.state.stopped_line is None:
            raise BasicRuntimeError("CAN'T CONTINUE")
        # Resume from stopped line
        lines = self.state.sorted_lines()
        self.state.running = True
        # Re-run from stopped position
        # This is handled externally by the REPL
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Helper: reassemble token stream tail as text (for THEN <statement>)
# ─────────────────────────────────────────────────────────────────────────────

def _tokens_to_text(ts: TokenStream) -> str:
    """Consume all remaining tokens from ts and return them as a string."""
    parts = []
    while not ts.at_end():
        t = ts.advance()
        if t.type == TT_NUMBER:
            parts.append(str(t.value))
        elif t.type in (TT_STRING,):
            parts.append(f'"{t.value}"')
        else:
            parts.append(str(t.value))
    return ' '.join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Patch Interpreter.run() to handle FOR/NEXT and GOSUB returns properly
# ─────────────────────────────────────────────────────────────────────────────

def _run_program(interp: Interpreter, start_line: int = None):
    """Full run loop with proper GOTO/GOSUB/NEXT handling."""
    state = interp.state
    state.running      = True
    state.stopped_line = None
    state.rebuild_data()
    state.clr()

    lines = state.sorted_lines()
    if not lines:
        state.running = False
        return

    if start_line is None:
        start_line = lines[0]
    if start_line not in state.program:
        raise BasicRuntimeError(f'UNDEFINED LINE {start_line}')

    pc       = lines.index(start_line)
    stmt_idx = 0

    try:
        while pc < len(lines):
            line_num = lines[pc]
            state.current_line = line_num
            text  = state.program[line_num]
            stmts = _split_statements(text)

            jumped = False
            while stmt_idx < len(stmts):
                result = interp._exec_stmt(stmts[stmt_idx], line_num, stmt_idx, stmts)

                if result is None:
                    stmt_idx += 1

                elif isinstance(result, tuple):
                    action = result[0]

                    if action == 'goto':
                        target = result[1]
                        if target not in state.program:
                            raise BasicRuntimeError(f'UNDEFINED LINE {target}')
                        pc       = lines.index(target)
                        stmt_idx = 0
                        jumped   = True
                        break

                    elif action == 'goto_stmt':
                        # FOR/NEXT loop back to stmt after FOR
                        target_line = result[1]
                        target_stmt = result[2]
                        if target_line not in state.program:
                            raise BasicRuntimeError(f'UNDEFINED LINE {target_line}')
                        pc       = lines.index(target_line)
                        stmt_idx = target_stmt
                        # Re-fetch stmts for this line
                        stmts = _split_statements(state.program[lines[pc]])
                        jumped = True
                        break

                    elif action == '_resume':
                        target_line = result[1]
                        target_stmt = result[2]
                        if target_line not in state.program:
                            raise BasicRuntimeError(f'UNDEFINED LINE {target_line}')
                        pc       = lines.index(target_line)
                        stmts    = _split_statements(state.program[lines[pc]])
                        stmt_idx = target_stmt
                        jumped   = True
                        break

                    elif action == 'next_line':
                        break

                    else:
                        stmt_idx += 1
                else:
                    stmt_idx += 1

            if not jumped:
                pc       += 1
                stmt_idx  = 0

    except BasicEnd:
        pass
    except BasicStop:
        state.running = False
        line_info = f' IN {state.current_line}' if state.current_line else ''
        state.write_output(f'\nBREAK{line_info}\n')
        return
    except BasicNew:
        state.clear_program()
        return
    finally:
        state.running = False


# Monkey-patch the run method
Interpreter.run = _run_program
