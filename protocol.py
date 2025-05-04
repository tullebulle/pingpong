from __future__ import annotations

"""
Shared protocol definitions for the UDP-based pong game.
Both client and server import this file so they always agree on
packet format and version.
"""

import json
import time
from dataclasses import dataclass, asdict
from enum import IntEnum
from typing import Tuple, Type, Dict, Any, Union

PROTOCOL_VERSION: int = 1  # Bump this whenever the wire format changes


class MessageType(IntEnum):
    HELLO = 0
    PULSE = 1
    WELCOME = 2
    INPUT = 3
    STATE = 4
    PING = 5
    PONG = 6
    DENIED = 7
    GAME_OVER = 8
    LOGIN = 9
    LOGIN_RESULT = 10


@dataclass
class BaseMessage:
    """Parent class that provides encode() helper common to all messages."""

    type: MessageType

    def encode(self) -> bytes:
        payload = asdict(self)
        payload["version"] = PROTOCOL_VERSION
        payload["type"] = int(self.type)
        return json.dumps(payload).encode("utf-8")


@dataclass
class Hello(BaseMessage):
    username: str

    def __init__(self, username: str):
        super().__init__(MessageType.HELLO)
        self.username = username

@dataclass
class Pulse(BaseMessage):
    username: str

    def __init__(self, username: str):
        super().__init__(MessageType.PULSE)
        self.username = username       


@dataclass
class Welcome(BaseMessage):
    player_id: int  # 0 (left) or 1 (right)

    def __init__(self, player_id: int):
        super().__init__(MessageType.WELCOME)
        self.player_id = player_id


@dataclass
class Input(BaseMessage):
    seq: int
    paddle_y: float

    def __init__(self, seq: int, paddle_y: float):
        super().__init__(MessageType.INPUT)
        self.seq = seq
        self.paddle_y = paddle_y


@dataclass
class State(BaseMessage):
    tick: int
    ball_x: float
    ball_y: float
    paddle0_y: float
    paddle1_y: float
    score0: int
    score1: int
    player0_username: str | None
    player1_username: str | None

    def __init__(self, tick: int, ball_x: float, ball_y: float, paddle0_y: float, paddle1_y: float, 
                 score0: int, score1: int, player0_username: str | None = None, player1_username: str | None = None):
        super().__init__(MessageType.STATE)
        self.tick = tick
        self.ball_x = ball_x
        self.ball_y = ball_y
        self.paddle0_y = paddle0_y
        self.paddle1_y = paddle1_y
        self.score0 = score0
        self.score1 = score1
        self.player0_username = player0_username
        self.player1_username = player1_username


@dataclass
class Ping(BaseMessage):
    ts: float

    def __init__(self, ts: float | None = None):
        super().__init__(MessageType.PING)
        self.ts = ts if ts is not None else time.time()


@dataclass
class Pong(BaseMessage):
    ts: float

    def __init__(self, ts: float):
        super().__init__(MessageType.PONG)
        self.ts = ts


@dataclass
class Denied(BaseMessage):
    reason: str

    def __init__(self, reason: str):
        super().__init__(MessageType.DENIED)
        self.reason = reason


@dataclass
class GameOver(BaseMessage):
    reason: str

    def __init__(self, reason: str):
        super().__init__(MessageType.GAME_OVER)
        self.reason = reason


@dataclass
class Login(BaseMessage):
    username: str
    password_hash: str

    def __init__(self, username: str, password_hash: str):
        super().__init__(MessageType.LOGIN)
        self.username = username
        self.password_hash = password_hash


@dataclass
class LoginResult(BaseMessage):
    success: bool
    message: str

    def __init__(self, success: bool, message: str = ""):
        super().__init__(MessageType.LOGIN_RESULT)
        self.success = success
        self.message = message


# Mapping from MessageType to its concrete dataclass constructor
_TYPE_TO_CLS: Dict[MessageType, Type[BaseMessage]] = {
    MessageType.HELLO: Hello,  # type: ignore[arg-type]
    MessageType.PULSE: Pulse,  # type: ignore[arg-type]
    MessageType.WELCOME: Welcome,  # type: ignore[arg-type]
    MessageType.INPUT: Input,  # type: ignore[arg-type]
    MessageType.STATE: State,  # type: ignore[arg-type]
    MessageType.PING: Ping,  # type: ignore[arg-type]
    MessageType.PONG: Pong,  # type: ignore[arg-type]
    MessageType.DENIED: Denied,  # type: ignore[arg-type]
    MessageType.GAME_OVER: GameOver,  # type: ignore[arg-type]
    MessageType.LOGIN: Login,  # type: ignore[arg-type]
    MessageType.LOGIN_RESULT: LoginResult,  # type: ignore[arg-type]
}

def decode(raw: bytes) -> BaseMessage:
    """Convert raw UDP payload into a concrete message instance."""
    try:
        obj: Dict[str, Any] = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid JSON packet: {exc}") from exc

    if obj.get("version") != PROTOCOL_VERSION:
        raise ValueError("Protocol version mismatch")

    try:
        mtype = MessageType(obj["type"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Unknown or missing message type") from exc

    cls = _TYPE_TO_CLS[mtype]

    # Pop fields that are not dataclass members
    payload = {k: v for k, v in obj.items() if k not in {"type", "version"}}

    return cls(**payload)  # type: ignore[arg-type] 