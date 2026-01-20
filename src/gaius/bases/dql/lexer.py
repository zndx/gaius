"""DQL Lexer - tokenize Dataview Query Language input."""

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class TokenType(Enum):
    """Token types for DQL lexer."""

    # Keywords
    WHERE = auto()
    ORDER = auto()
    BY = auto()
    LIMIT = auto()
    AS = auto()
    OF = auto()
    GROUP = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    ASC = auto()
    DESC = auto()
    IN = auto()
    LIKE = auto()

    # Operators
    EQ = auto()  # =
    NE = auto()  # !=
    LT = auto()  # <
    LE = auto()  # <=
    GT = auto()  # >
    GE = auto()  # >=
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    COMMA = auto()  # ,

    # Values
    IDENTIFIER = auto()
    STRING = auto()
    NUMBER = auto()
    BOOLEAN = auto()
    NULL = auto()
    TIMESTAMP = auto()

    EOF = auto()


@dataclass
class Token:
    """A single token from the lexer."""

    type: TokenType
    value: Any
    position: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, pos={self.position})"


class DQLLexer:
    """Tokenize DQL input."""

    KEYWORDS = {
        "WHERE",
        "ORDER",
        "BY",
        "LIMIT",
        "AS",
        "OF",
        "GROUP",
        "AND",
        "OR",
        "NOT",
        "ASC",
        "DESC",
        "IN",
        "LIKE",
        "TRUE",
        "FALSE",
        "NULL",
    }

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """Tokenize the entire input and return token list."""
        while self.pos < len(self.text):
            self._skip_whitespace()
            if self.pos >= len(self.text):
                break

            # Check operators first (order matters for multi-char ops)
            if self._match_operators():
                continue

            # Check for strings
            if self.text[self.pos] in ('"', "'"):
                self._read_string()
                continue

            # Check for numbers
            if self.text[self.pos].isdigit() or (
                self.text[self.pos] == "-"
                and self.pos + 1 < len(self.text)
                and self.text[self.pos + 1].isdigit()
            ):
                self._read_number()
                continue

            # Check for identifiers/keywords
            if self.text[self.pos].isalpha() or self.text[self.pos] == "_":
                self._read_identifier()
                continue

            raise DQLLexerError(
                f"Unexpected character at position {self.pos}: {self.text[self.pos]!r}"
            )

        self.tokens.append(Token(TokenType.EOF, None, self.pos))
        return self.tokens

    def _skip_whitespace(self) -> None:
        """Skip whitespace characters."""
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _match_operators(self) -> bool:
        """Match and consume operator tokens."""
        ops = [
            ("!=", TokenType.NE),
            ("<>", TokenType.NE),  # Alternative not-equals
            ("<=", TokenType.LE),
            (">=", TokenType.GE),
            ("=", TokenType.EQ),
            ("<", TokenType.LT),
            (">", TokenType.GT),
            ("(", TokenType.LPAREN),
            (")", TokenType.RPAREN),
            (",", TokenType.COMMA),
        ]
        for op, tok_type in ops:
            if self.text[self.pos :].startswith(op):
                self.tokens.append(Token(tok_type, op, self.pos))
                self.pos += len(op)
                return True
        return False

    def _read_string(self) -> None:
        """Read a quoted string literal."""
        quote = self.text[self.pos]
        start = self.pos
        self.pos += 1
        value = []

        while self.pos < len(self.text) and self.text[self.pos] != quote:
            if self.text[self.pos] == "\\" and self.pos + 1 < len(self.text):
                # Handle escape sequences
                self.pos += 1
                if self.text[self.pos] == "n":
                    value.append("\n")
                elif self.text[self.pos] == "t":
                    value.append("\t")
                elif self.text[self.pos] == "\\":
                    value.append("\\")
                elif self.text[self.pos] == quote:
                    value.append(quote)
                else:
                    value.append(self.text[self.pos])
            else:
                value.append(self.text[self.pos])
            self.pos += 1

        if self.pos >= len(self.text):
            raise DQLLexerError(f"Unterminated string at position {start}")

        self.pos += 1  # Skip closing quote

        # Check if it looks like an ISO 8601 timestamp
        val_str = "".join(value)
        if re.match(r"^\d{4}-\d{2}-\d{2}", val_str):
            self.tokens.append(Token(TokenType.TIMESTAMP, val_str, start))
        else:
            self.tokens.append(Token(TokenType.STRING, val_str, start))

    def _read_number(self) -> None:
        """Read a numeric literal."""
        start = self.pos
        if self.text[self.pos] == "-":
            self.pos += 1

        # Integer part
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1

        # Decimal part
        if (
            self.pos < len(self.text)
            and self.text[self.pos] == "."
            and self.pos + 1 < len(self.text)
            and self.text[self.pos + 1].isdigit()
        ):
            self.pos += 1
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                self.pos += 1

        # Scientific notation
        if (
            self.pos < len(self.text)
            and self.text[self.pos] in ("e", "E")
            and self.pos + 1 < len(self.text)
        ):
            next_char = self.text[self.pos + 1]
            if next_char.isdigit() or (
                next_char in ("+", "-")
                and self.pos + 2 < len(self.text)
                and self.text[self.pos + 2].isdigit()
            ):
                self.pos += 1
                if self.text[self.pos] in ("+", "-"):
                    self.pos += 1
                while self.pos < len(self.text) and self.text[self.pos].isdigit():
                    self.pos += 1

        value_str = self.text[start : self.pos]
        value = float(value_str) if "." in value_str or "e" in value_str.lower() else int(value_str)
        self.tokens.append(Token(TokenType.NUMBER, value, start))

    def _read_identifier(self) -> None:
        """Read an identifier or keyword."""
        start = self.pos
        while self.pos < len(self.text) and (
            self.text[self.pos].isalnum() or self.text[self.pos] == "_"
        ):
            self.pos += 1

        value = self.text[start : self.pos]
        upper = value.upper()

        if upper in ("TRUE", "FALSE"):
            self.tokens.append(Token(TokenType.BOOLEAN, upper == "TRUE", start))
        elif upper == "NULL":
            self.tokens.append(Token(TokenType.NULL, None, start))
        elif upper in self.KEYWORDS:
            self.tokens.append(Token(TokenType[upper], value, start))
        else:
            self.tokens.append(Token(TokenType.IDENTIFIER, value, start))


class DQLLexerError(Exception):
    """Error during DQL lexing."""

    pass
