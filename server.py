from __future__ import annotations

"""UDP-based Pong game server (authoritative).
Run with: python main.py server [port]
"""

import socket
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from protocol import (
    Hello,
    Input,
    MessageType,
    State,
    Welcome,
    decode,
    Denied,
)


@dataclass
class PlayerSlot:
    id: int
    addr: Tuple[str, int]
    paddle_y: float = 0.0
    last_input_ts: float = 0.0
    username: str | None = None


class GameState:
    """Simple Pong physics simulation (no spin, no acceleration)."""

    # Static dimensions
    W, H = 640, 480
    PADDLE_W, PADDLE_H = 10, 60
    BALL_SZ = 10
    PADDLE_MARGIN = 0  # x-offset of paddles from edge
    BALL_SPEED = 300.0  # px/s (initial)

    def __init__(self) -> None:
        self.tick: int = 0
        self.ball_x: float = self.W / 2
        self.ball_y: float = self.H / 2
        self.ball_vx: float = self.BALL_SPEED
        self.ball_vy: float = self.BALL_SPEED * 0.3
        # paddles indexed by player id
        self.paddles: List[float] = [self.H / 2 - self.PADDLE_H / 2] * 2
        self.scores: List[int] = [0, 0]

    # ---------------- physics helpers ---------------- #
    def reset_ball(self, direction: int) -> None:
        """Place ball in center moving toward given horizontal direction (±1)."""
        self.ball_x = self.W / 2
        self.ball_y = self.H / 2
        self.ball_vx = self.BALL_SPEED * direction
        self.ball_vy = self.BALL_SPEED * 0.3

    def step(self, dt: float) -> None:
        """Advance world simulation by dt seconds."""
        self.ball_x += self.ball_vx * dt
        self.ball_y += self.ball_vy * dt

        # Top/bottom bounce
        if self.ball_y <= 0:
            self.ball_y = 0
            self.ball_vy *= -1
        elif self.ball_y + self.BALL_SZ >= self.H:
            self.ball_y = self.H - self.BALL_SZ
            self.ball_vy *= -1

        # Left paddle collision
        if self.ball_x <= self.PADDLE_W:
            if self.paddles[0] <= self.ball_y <= self.paddles[0] + self.PADDLE_H:
                self.ball_x = self.PADDLE_W
                self.ball_vx = abs(self.ball_vx)
        # Right paddle collision
        if self.ball_x + self.BALL_SZ >= self.W - self.PADDLE_W:
            if self.paddles[1] <= self.ball_y <= self.paddles[1] + self.PADDLE_H:
                self.ball_x = self.W - self.PADDLE_W - self.BALL_SZ
                self.ball_vx = -abs(self.ball_vx)

        # Scoring
        if self.ball_x < 0:
            self.scores[1] += 1
            self.reset_ball(direction=1)
        elif self.ball_x > self.W:
            self.scores[0] += 1
            self.reset_ball(direction=-1)

        self.tick += 1


class PongServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 9999):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.setblocking(False)

        self.slots: List[Optional[PlayerSlot]] = [None, None]
        self.game = GameState()
        self.running = False
        self.start_time: float | None = None

    # ------------- networking helpers ------------- #
    def send(self, msg, addr):
        self.sock.sendto(msg.encode(), addr)

    def broadcast_state(self):
        state_msg = State(
            tick=self.game.tick,
            ball_x=self.game.ball_x,
            ball_y=self.game.ball_y,
            paddle0_y=self.game.paddles[0],
            paddle1_y=self.game.paddles[1],
            score0=self.game.scores[0],
            score1=self.game.scores[1],
        )
        payload = state_msg.encode()
        for slot in self.slots:
            if slot is not None:
                self.sock.sendto(payload, slot.addr)

    # ------------- packet dispatch ------------- #
    def handle_packet(self, raw: bytes, addr):
        try:
            msg = decode(raw)
        except ValueError as exc:
            print(f"Bad packet from {addr}: {exc}")
            return

        if msg.type == MessageType.HELLO:
            self._handle_hello(msg, addr)
        elif msg.type == MessageType.INPUT:
            self._handle_input(msg, addr)  # type: ignore[arg-type]

    def _find_slot_by_addr(self, addr):
        for slot in self.slots:
            if slot and slot.addr == addr:
                return slot
        return None

    def _find_slot_by_username(self, name: str):
        for slot in self.slots:
            if slot and getattr(slot, "username", None) == name:
                return slot
        return None

    def _handle_hello(self, msg: Hello, addr):
        # Already joined with this address?
        if self._find_slot_by_addr(addr):
            return  # ignore duplicate

        # Reject if username already taken in current game
        if self._find_slot_by_username(msg.name):  # type: ignore[attr-defined]
            denied = Denied("username already active")
            self.send(denied, addr)
            print(f"Rejecting duplicate username {msg.name} from {addr}")
            return

        # Find free slot
        for i in (0, 1):
            if self.slots[i] is None:
                self.slots[i] = PlayerSlot(i, addr, paddle_y=self.game.H / 2 - self.game.PADDLE_H / 2, username=msg.name)
                welcome = Welcome(player_id=i)
                self.send(welcome, addr)
                print(f"Player {i} joined from {addr}")
                break
        else:
            print("Game full, rejecting connection from", addr)
            return

        # Start game once both players present
        if all(self.slots):
            # Reset game fresh and schedule a 2-second countdown before physics starts
            self.game = GameState()
            self.running = True
            self.start_time = time.perf_counter() + 2.0  # 2-second grace
            print("Both players connected. Game starts in 2 seconds …")

    def _handle_input(self, msg: Input, addr):
        slot = self._find_slot_by_addr(addr)
        if slot is None:
            return  # unknown player
        slot.paddle_y = max(0, min(self.game.H - self.game.PADDLE_H, msg.paddle_y))
        slot.last_input_ts = time.time()
        self.game.paddles[slot.id] = slot.paddle_y

    # ------------- main loop ------------- #
    def run(self):
        TICK_RATE = 60
        tick_interval = 1.0 / TICK_RATE
        next_tick = time.perf_counter()
        print("Server running, waiting for players …")

        while True:
            # network receive (non-blocking)
            try:
                data, addr = self.sock.recvfrom(4096)
            except BlockingIOError:
                data = None
            if data:
                self.handle_packet(data, addr)

            now = time.perf_counter()
            if self.running:
                # Grace period before physics begins
                if self.start_time and now < self.start_time:
                    # Keep sending neutral state so clients show countdown-like pause
                    self.broadcast_state()
                else:
                    if self.start_time is not None:
                        # Grace period just ended; align the simulation schedule
                        next_tick = now  # reset so we don't try to catch up
                        self.start_time = None
                    if now >= next_tick:
                        self.game.step(tick_interval)
                        self.broadcast_state()
                        next_tick += tick_interval

            # Very small sleep to avoid 100% CPU when idle
            time.sleep(0.001)


def run_server_main(port: int = 9999):
    server = PongServer(port=port)
    server.run() 