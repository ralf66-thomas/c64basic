# Commodore 64 BASIC V2 Interpreter & Editor

A fully compatible C64 BASIC V2 interpreter and screen editor written in Python.

---

## Requirements

- Python 3.7+
- No external dependencies (uses standard library only)
- fully done with CloudCode and Sonnet 4.6

---

## Usage

### Interactive Editor (curses UI)

Launches a C64-style screen editor with blue/cyan colour scheme:

```bash
python run_c64.py
```

### Plain-Text REPL

For terminals without curses support:

```bash
python run_c64.py --text
```

### Run a .bas File Directly

```bash
python run_c64.py examples/hello.bas
python run_c64.py examples/fibonacci.bas
python run_c64.py examples/primes.bas
```

---

## Editor Controls

| Key | Action |
|-----|--------|
| `F1` | LIST program |
| `F3` | RUN program |
| `F5` | LOAD file |
| `F7` | SAVE file |
| `ESC` | Break / stop execution |
| `↑ / ↓` | Command history |
| `← / →` | Move cursor in input line |
| `Home / End` | Jump to start/end of input |
| `Page Up / Down` | Scroll screen output |
| `Backspace / Del` | Delete characters |
| `Enter` | Execute command or store program line |

---

## Writing Programs

Type a line number followed by BASIC code to store it in the program.
Type a command **without** a line number to execute it immediately (direct mode).

```basic
10 PRINT "HELLO, WORLD!"
20 END
RUN
```

To delete a line, type its number with nothing after it:

```basic
20
```

---

## BASIC Statements

### PRINT
Outputs text and numbers to the screen.

```basic
PRINT "HELLO"
PRINT 1 + 2
PRINT "A ="; A
PRINT "COL1", "COL2", "COL3"   ' comma = next 10-col tab stop
PRINT A; B; C                   ' semicolon = no space between
PRINT TAB(15); "INDENTED"
PRINT SPC(5); "SPACED"
```

### INPUT
Reads user input into variables.

```basic
INPUT A
INPUT "ENTER NAME: "; N$
INPUT "X,Y: "; X, Y
```

### GET
Reads a single character (non-blocking on real C64, blocking here).

```basic
GET K$
```

### LET
Assigns a value to a variable (`LET` keyword is optional).

```basic
LET A = 10
B = A * 2 + 1
A$ = "HELLO"
```

### IF / THEN
Conditional branching. `THEN` can be followed by a line number or a statement.

```basic
IF A > 10 THEN PRINT "BIG"
IF A = 0 THEN GOTO 100
IF A$ = "YES" THEN GOSUB 500
```

### GOTO
Unconditional jump to a line number.

```basic
GOTO 100
```

### GOSUB / RETURN
Call a subroutine and return from it.

```basic
GOSUB 1000
...
1000 PRINT "SUBROUTINE"
1010 RETURN
```

### FOR / TO / STEP / NEXT
Counted loop. `STEP` defaults to 1.

```basic
FOR I = 1 TO 10
  PRINT I
NEXT I

FOR X = 10 TO 1 STEP -1
  PRINT X
NEXT X
```

### ON … GOTO / ON … GOSUB
Branch to one of several targets based on an index (1-based).

```basic
ON X GOTO 100, 200, 300
ON X GOSUB 100, 200, 300
```

### DIM
Declare an array. Indices are `0` to `n` (n+1 elements).
Arrays are auto-dimensioned to 10 (11 elements) if not DIM'd first.

```basic
DIM A(20)
DIM M(5, 5)
DIM N$(10)
```

### DATA / READ / RESTORE
Embed data in the program and read it sequentially.

```basic
100 DATA 10, 20, 30, "HELLO", "WORLD"
...
READ A, B, C, X$, Y$
RESTORE           ' reset data pointer to beginning
```

### DEF FN
Define a single-line user function.

```basic
DEF FN SQ(X) = X * X
DEF FN AV(X) = (X + 1) / 2
PRINT FN SQ(5)    ' prints 25
```

### POKE / PEEK
Write/read a byte at a simulated memory address.

```basic
POKE 1024, 65
PRINT PEEK(1024)   ' prints 65
```

### REM
Comment — rest of the line is ignored.

```basic
10 REM THIS IS A COMMENT
```

### END / STOP
`END` terminates the program. `STOP` halts with a `BREAK IN <line>` message (can be resumed with `CONT`).

```basic
END
STOP
```

---

## Direct-Mode Commands

These are typed without a line number and execute immediately.

| Command | Description |
|---------|-------------|
| `RUN` | Run the program from the first line |
| `RUN 100` | Run from line 100 |
| `LIST` | List the entire program |
| `LIST 10-50` | List lines 10 through 50 |
| `NEW` | Clear program and variables |
| `CLR` | Clear variables only (keep program) |
| `CONT` | Continue after STOP |
| `LOAD "filename"` | Load a .bas file |
| `SAVE "filename"` | Save the program to a .bas file |
| `QUIT` / `EXIT` | Exit the interpreter |

---

## Numeric Functions

| Function | Description |
|----------|-------------|
| `ABS(x)` | Absolute value |
| `INT(x)` | Floor (toward −∞) |
| `SGN(x)` | Sign: −1, 0, or 1 |
| `SQR(x)` | Square root |
| `SIN(x)` | Sine (radians) |
| `COS(x)` | Cosine (radians) |
| `TAN(x)` | Tangent (radians) |
| `ATN(x)` | Arctangent (radians) |
| `EXP(x)` | e^x |
| `LOG(x)` | Natural logarithm |
| `RND(x)` | Random float 0–1; `RND(0)` = last; `RND(-n)` = seed |
| `PEEK(addr)` | Read simulated memory byte |
| `FRE(x)` | Returns 38911 (C64 free memory constant) |
| `POS(x)` | Current cursor column |
| `TI` | Timer (jiffy clock, 60ths of a second) |

## String Functions

| Function | Description |
|----------|-------------|
| `LEN(s$)` | Length of string |
| `LEFT$(s$, n)` | First n characters |
| `RIGHT$(s$, n)` | Last n characters |
| `MID$(s$, start, len)` | Substring (1-based start) |
| `ASC(s$)` | ASCII code of first character |
| `CHR$(n)` | Character from ASCII code |
| `STR$(n)` | Number to string |
| `VAL(s$)` | String to number |
| `STRING$(n, x)` | String of n copies of character x |
| `SPC(n)` | n spaces (in PRINT) |
| `TAB(n)` | Move to column n (in PRINT) |
| `TI$` | Time as `HHMMSS` string |

---

## Operators

| Operator | Description |
|----------|-------------|
| `+` `-` `*` `/` | Arithmetic |
| `^` | Exponentiation |
| `=` `<` `>` `<=` `>=` `<>` | Comparison (return −1 or 0) |
| `AND` `OR` `NOT` | Logical (C64-style: TRUE = −1, FALSE = 0) |

> **C64 Note:** Comparison and logical operators return **-1 for TRUE** and **0 for FALSE**, matching real C64 behaviour.

---

## Variable Names

- **C64 compatible:** Only the first **2 characters** of a variable name are significant.
  `APPLE` and `APRICOT` refer to the same variable `AP`.
- Numeric variables: `A`, `AB`, `A1`, etc.
- String variables: `A$`, `AB$`, etc.
- Variables default to `0` (numeric) or `""` (string) if not set.

---

## Example Programs

### Hello World
```basic
10 PRINT "HELLO, WORLD!"
20 END
```

### Fibonacci Sequence
```basic
10 LET A = 0
20 LET B = 1
30 FOR I = 1 TO 20
40   PRINT A;
50   LET C = A + B
60   LET A = B
70   LET B = C
80 NEXT I
90 PRINT
```

### Guessing Game
```basic
10 PRINT "GUESS THE NUMBER (1-100)"
20 LET S = INT(RND(1)*100)+1
30 LET G = 0
40 INPUT "YOUR GUESS? "; N
50 LET G = G + 1
60 IF N = S THEN GOTO 100
70 IF N < S THEN PRINT "TOO LOW!"
80 IF N > S THEN PRINT "TOO HIGH!"
90 GOTO 40
100 PRINT "CORRECT! YOU GOT IT IN"; G; "GUESSES!"
110 END
```

### Sieve of Eratosthenes (Primes to 100)
```basic
10 DIM P(100)
20 FOR I = 2 TO 100 : P(I) = 1 : NEXT I
30 FOR I = 2 TO 10
40   IF P(I) = 0 THEN GOTO 70
50   FOR J = I*2 TO 100 STEP I : P(J) = 0 : NEXT J
60 NEXT I
70 FOR I = 2 TO 100
80   IF P(I) = 1 THEN PRINT I;
90 NEXT I
100 PRINT
```

### Subroutine Example
```basic
10 FOR I = 1 TO 3
20   GOSUB 100
30 NEXT I
40 END
100 PRINT "SUBROUTINE CALLED"
110 RETURN
```

### String Operations
```basic
10 A$ = "COMMODORE 64"
20 PRINT LEFT$(A$, 9)     ' COMMODORE
30 PRINT RIGHT$(A$, 2)    ' 64
40 PRINT MID$(A$, 1, 9)   ' COMMODORE
50 PRINT LEN(A$)           ' 12
60 PRINT ASC("A")          ' 65
70 PRINT CHR$(65)          ' A
```

---

## File Format

Programs are saved as plain text `.bas` files, one line per statement:

```
10 REM My Program
20 PRINT "HELLO"
30 END
```

Load with `LOAD "myfile"` or `LOAD "myfile.bas"` (extension added automatically if missing).

---

## Project Structure

```
c64basic/
  __init__.py       Package init
  lexer.py          Tokeniser (greedy C64 keyword matching)
  interpreter.py    Core interpreter, expression parser, runtime
  editor.py         Curses screen editor (C64 colour scheme)
  main.py           Entry point (curses / text-REPL / file modes)
run_c64.py          Top-level launcher
examples/
  hello.bas
  fibonacci.bas
  guessing_game.bas
  multiplication_table.bas
  primes.bas
  data_demo.bas
```
