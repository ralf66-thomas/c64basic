#!/usr/bin/env python3
"""
Lexer for Commodore 64 BASIC V2
Tokenizes a line of BASIC source code (without the line number prefix).
"""

# Token types
TT_NUMBER    = 'NUMBER'
TT_STRING    = 'STRING'
TT_IDENT     = 'IDENT'
TT_KEYWORD   = 'KEYWORD'
TT_PLUS      = '+'
TT_MINUS     = '-'
TT_MUL       = '*'
TT_DIV       = '/'
TT_POW       = '^'
TT_LPAREN    = '('
TT_RPAREN    = ')'
TT_COMMA     = ','
TT_SEMICOLON = ';'
TT_COLON     = ':'
TT_EQ        = '='
TT_LT        = '<'
TT_GT        = '>'
TT_LE        = '<='
TT_GE        = '>='
TT_NE        = '<>'
TT_EOF       = 'EOF'

# C64 BASIC V2 keywords (order matters - sorted longest first for greedy match)
KEYWORDS = [
    'RESTORE', 'STRING$', 'RETURN', 'STATUS', 'PRINT', 'INPUT', 'GOSUB',
    'RIGHT$', 'LEFT$', 'STEP', 'THEN', 'ELSE', 'GOTO', 'NEXT', 'DATA',
    'READ', 'STOP', 'POKE', 'LOAD', 'SAVE', 'WAIT', 'CONT', 'LIST',
    'MID$', 'CHR$', 'STR$', 'TI$', 'DS$', 'FOR', 'DIM', 'GET', 'NEW',
    'RUN', 'CLR', 'CMD', 'SYS', 'LET', 'REM', 'END', 'NOT', 'AND', 'OR',
    'DEF', 'FN', 'IF', 'TO', 'ON',
    'PRINT', 'ABS', 'INT', 'RND', 'SQR', 'SIN', 'COS', 'TAN', 'ATN',
    'EXP', 'LOG', 'SGN', 'FRE', 'POS', 'LEN', 'ASC', 'VAL', 'SPC',
    'TAB', 'PEEK', 'TI',
]

# Sort by length descending for greedy matching
KEYWORDS_SORTED = sorted(set(KEYWORDS), key=len, reverse=True)
KEYWORDS_SET    = set(KEYWORDS)


class Token:
    __slots__ = ('type', 'value')

    def __init__(self, ttype, value):
        self.type  = ttype
        self.value = value

    def __repr__(self):
        return f'Token({self.type}, {self.value!r})'


class LexError(Exception):
    pass


def _normalize_varname(name: str) -> str:
    """C64: only first 2 characters of a variable name are significant."""
    if name.endswith('$'):
        body = name[:-1]
        return (body[:2] + '$').upper()
    if name.endswith('%'):
        body = name[:-1]
        return (body[:2] + '%').upper()
    return name[:2].upper()


class Lexer:
    """Tokenise a single BASIC statement/line (no leading line-number)."""

    def __init__(self, text: str):
        self.raw  = text          # original (preserves string case)
        self.text = text.upper()  # uppercased view for keyword/ident matching
        self.pos  = 0

    # ------------------------------------------------------------------ helpers

    def _peek(self, offset: int = 0) -> str:
        p = self.pos + offset
        return self.text[p] if p < len(self.text) else ''

    def _peek_raw(self, offset: int = 0) -> str:
        p = self.pos + offset
        return self.raw[p] if p < len(self.raw) else ''

    # ------------------------------------------------------------------ readers

    def _read_string(self) -> str:
        """Read a quoted string literal (preserves original case)."""
        self.pos += 1  # skip opening "
        start = self.pos
        while self.pos < len(self.raw) and self.raw[self.pos] != '"':
            self.pos += 1
        s = self.raw[start:self.pos]
        if self.pos < len(self.raw):
            self.pos += 1  # skip closing "
        return s

    def _read_number(self) -> float:
        start = self.pos
        # integer / decimal part
        while self._peek().isdigit() or self._peek() == '.':
            self.pos += 1
        # optional exponent
        if self._peek() == 'E':
            self.pos += 1
            if self._peek() in '+-':
                self.pos += 1
            while self._peek().isdigit():
                self.pos += 1
        try:
            return float(self.text[start:self.pos])
        except ValueError:
            raise LexError(f'Bad number: {self.text[start:self.pos]}')

    def _read_ident(self) -> str:
        """Read an identifier; apply C64 two-char significance rule."""
        start = self.pos
        self.pos += 1  # first char already checked (alpha)
        while self._peek().isalnum():
            self.pos += 1
        # type suffix
        if self._peek() in '$%':
            self.pos += 1
        raw_name = self.text[start:self.pos]
        return _normalize_varname(raw_name)

    # ------------------------------------------------------------------ main

    def tokenize(self) -> list:
        tokens = []

        while self.pos < len(self.text):
            c  = self.text[self.pos]
            cr = self.raw[self.pos]

            # Whitespace
            if c == ' ':
                self.pos += 1
                continue

            # String literal
            if cr == '"':
                tokens.append(Token(TT_STRING, self._read_string()))
                continue

            # Numeric literal
            if c.isdigit() or (c == '.' and self._peek(1).isdigit()):
                tokens.append(Token(TT_NUMBER, self._read_number()))
                continue

            # Identifier or keyword
            if c.isalpha():
                # REM is special: rest of line is a comment string
                rest = self.text[self.pos:]
                if rest.startswith('REM'):
                    tokens.append(Token(TT_KEYWORD, 'REM'))
                    comment = self.raw[self.pos + 3:]
                    tokens.append(Token(TT_STRING, comment.lstrip()))
                    self.pos = len(self.text)
                    continue

                # Try greedy keyword match
                matched_kw = None
                for kw in KEYWORDS_SORTED:
                    if rest.startswith(kw):
                        end_pos   = self.pos + len(kw)
                        next_char = self.text[end_pos] if end_pos < len(self.text) else ''
                        # keyword must not be followed by alphanumeric
                        # (unless the keyword itself ends with $ or %)
                        if kw[-1] in '$%' or not next_char.isalnum():
                            matched_kw = kw
                            self.pos  += len(kw)
                            break

                if matched_kw:
                    tokens.append(Token(TT_KEYWORD, matched_kw))
                else:
                    tokens.append(Token(TT_IDENT, self._read_ident()))
                continue

            # Two-character operators
            two = self.text[self.pos:self.pos + 2]
            if two in ('<>', '<=', '>='):
                mapping = {'<>': TT_NE, '<=': TT_LE, '>=': TT_GE}
                tokens.append(Token(mapping[two], two))
                self.pos += 2
                continue

            # Single-character operators / punctuation
            single = {
                '+': TT_PLUS, '-': TT_MINUS, '*': TT_MUL, '/': TT_DIV,
                '^': TT_POW,  '(': TT_LPAREN, ')': TT_RPAREN,
                ',': TT_COMMA, ';': TT_SEMICOLON, ':': TT_COLON,
                '=': TT_EQ,  '<': TT_LT, '>': TT_GT,
            }
            if c in single:
                tokens.append(Token(single[c], c))
                self.pos += 1
                continue

            # Unknown – skip silently (C64 behaviour)
            self.pos += 1

        tokens.append(Token(TT_EOF, None))
        return tokens
