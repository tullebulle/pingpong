from __future__ import annotations

"""UDP-based Pong game server (authoritative).
Run with: python main.py server [port]
"""

import hashlib
import os
import socket
import sqlite3
import time
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from protocol import (
    Denied,
    Pulse,
    GameOver,
    Hello,
    Input,
    Login,
    LoginResult,
    MessageType,
    State,
    Welcome,
    decode,
)

# Constants
PLAYER_TIMEOUT = 5.0  # seconds before considering a player disconnected

# Database constants
DB_FILE = Path(__file__).with_suffix(".db")  # users.db
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    games INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0
);
"""

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [SERVER] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('pong_server')

class ServerDB:
    """Server-side user database for authentication and stats."""
    
    def __init__(self, db_path: str | os.PathLike | None = None):
        self.db_path = Path(db_path) if db_path else DB_FILE
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(_SCHEMA)
        self.conn.commit()
        print(f"Initialized user database at {self.db_path}")




    # --------------------------------------------------- #
    def add_user(self, username: str, password_hash: str) -> None:
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
        except sqlite3.IntegrityError:
            raise ValueError("Username already exists")

    def verify_user(self, username: str, password_hash: str) -> bool:
        cur = self.conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        )
        row = cur.fetchone()
        if not row:
            return False
        return row[0] == password_hash

    # --------------------------------------------------- #
    def record_game(self, username: str, win: bool) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE users SET games = games + 1, wins = wins + ?, losses = losses + ? WHERE username = ?",
                (1 if win else 0, 0 if win else 1, username,),
            )

    def get_stats(self, username: str) -> Tuple[int, int, int]:
        cur = self.conn.execute(
            "SELECT games, wins, losses FROM users WHERE username = ?", (username,)
        )
        row = cur.fetchone()
        if row:
            return int(row[0]), int(row[1]), int(row[2])
        return (0, 0, 0)

@dataclass
class PlayerSlot:
    id: int
    addr: Tuple[str, int]
    paddle_y: float = 0.0
    last_pulse_time: float = 0.0
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
        self.ball_vy = self.BALL_SPEED * (random.random() - 0.5)

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
                self.ball_vy += self.BALL_SPEED * (random.random() - 0.5)/5
        # Right paddle collision
        if self.ball_x + self.BALL_SZ >= self.W - self.PADDLE_W:
            if self.paddles[1] <= self.ball_y <= self.paddles[1] + self.PADDLE_H:
                self.ball_x = self.W - self.PADDLE_W - self.BALL_SZ
                self.ball_vx = -abs(self.ball_vx)
                self.ball_vy += self.BALL_SPEED * (random.random() - 0.5)/5

        # Scoring
        if self.ball_x < 0:
            self.scores[1] += 1
            self.reset_ball(direction=1)
        elif self.ball_x > self.W:
            self.scores[0] += 1
            self.reset_ball(direction=-1)
        self.tick += 1


class PongServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 9999, db_path: str | os.PathLike | None = None):
        logger.info(f"Initializing server on {host}:{port}")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.setblocking(False)
        logger.debug("Created non-blocking UDP socket")

        self.slots: List[Optional[PlayerSlot]] = [None, None]
        self.game = GameState()
        self.game_running = False
        self.start_time: float | None = None
        logger.debug("Game state initialized")
        
        # Authentication
        self.db = ServerDB(db_path)
        # Mapping of authenticated clients by address
        self.authenticated_users = {}  # addr -> username
        logger.debug("Authentication system initialized")

    # ------------- networking helpers ------------- #
    def send(self, msg, addr):
        logger.debug(f"Sending {msg.__class__.__name__} to {addr}")
        self.sock.sendto(msg.encode(), addr)

    def broadcast_state(self):
        logger.debug(f"Broadcasting state: ball=({self.game.ball_x:.1f},{self.game.ball_y:.1f}), " + 
                    f"scores={self.game.scores[0]}-{self.game.scores[1]}")
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
                logger.debug(f"Sending state to player {slot.id} ({slot.addr})")
                self.sock.sendto(payload, slot.addr)

    # ------------- packet dispatch ------------- #
    def handle_packet(self, raw: bytes, addr):
        # self.last_pulse_time = time.perf_counter()
        try:
            msg = decode(raw)
            logger.info(f"Received {msg.__class__.__name__} from {addr}")
            
            # Update last_pulse_time for ANY message from client
            slot = self._find_slot_by_addr(addr)
            if slot:
                slot.last_pulse_time = time.perf_counter()
                logger.debug(f"Updated last_pulse_time for player {slot.id} to {slot.last_pulse_time}")
        except ValueError as exc:
            logger.error(f"Bad packet from {addr}: {exc}")
            return
        if msg.type == MessageType.LOGIN:
            logger.debug(f"Handling LOGIN from {addr}")
            self._handle_login(msg, addr)  # type: ignore[arg-type]
        elif msg.type == MessageType.HELLO:
            logger.debug(f"Handling HELLO from {addr}")
            self._handle_hello(msg, addr)
        else:
            if msg.type == MessageType.INPUT:
                logger.debug(f"Handling INPUT from {addr}")
                self._handle_input(msg, addr)  # type: ignore[arg-type]
            elif msg.type == MessageType.PULSE:
                logger.debug(f"Handling PULSE from {addr}")
                self._handle_pulse(msg, addr) 

    def _find_slot_by_addr(self, addr):
        logger.debug(f"Looking for slot with addr={addr}")
        for slot in self.slots:
            if slot and slot.addr == addr:
                logger.debug(f"Found slot with id={slot.id}")
                return slot
        logger.debug(f"No slot found for addr={addr}")
        return None

    def _find_slot_by_username(self, name: str):
        logger.debug(f"Looking for slot with username={name}")
        for slot in self.slots:
            if slot and getattr(slot, "username", None) == name:
                logger.debug(f"Found slot with id={slot.id}")
                return slot
        logger.debug(f"No slot found for username={name}")
        return None
    
    def _handle_pulse(self, msg: Pulse, addr):
        logger.debug(f"PULSE received from {msg.username} at {addr}")
        slot = self._find_slot_by_addr(addr)
        
        # Always echo pulse back to client even if not in slot
        return_msg = Pulse(username=msg.username)
        self.send(return_msg, addr)

    def _handle_login(self, msg: Login, addr):
        """Handle login request and respond with success/failure."""
        logger.debug(f"Processing LOGIN request for username={msg.username} from {addr}")
        try:
            if self.db.verify_user(msg.username, msg.password_hash):
                # check if user is already logged in
                if self._find_slot_by_username(msg.username):
                    result = LoginResult(success=False, message="User already authenticated")
                    self.send(result, addr)
                    logger.warning(f"User {msg.username} already authenticated from {addr}")
                else:
                    # Login successful
                    self.authenticated_users[addr] = msg.username
                    logger.debug(f"Added {addr} to authenticated_users with username={msg.username}")
                    result = LoginResult(success=True, message="User authenticated")
                    self.send(result, addr)
                    logger.info(f"User {msg.username} authenticated from {addr}")
            else:
                # Try creating user if not exists
                try:
                    logger.debug(f"User {msg.username} not found, trying to create")
                    self.db.add_user(msg.username, msg.password_hash)
                    self.authenticated_users[addr] = msg.username
                    logger.debug(f"Added {addr} to authenticated_users with username={msg.username}")
                    result = LoginResult(success=True, message="User created")
                    self.send(result, addr)
                    logger.info(f"New user {msg.username} created from {addr}")
                except ValueError:
                    # User exists but wrong password
                    result = LoginResult(success=False, message="Invalid credentials")
                    self.send(result, addr)
                    logger.warning(f"Failed login attempt for {msg.username} from {addr} (wrong password)")
        except Exception as e:
            result = LoginResult(success=False, message=f"Error: {str(e)}")
            self.send(result, addr)
            logger.error(f"Login error for {addr}: {e}")

    def _handle_hello(self, msg: Hello, addr):
        logger.debug(f"Processing HELLO request from {addr} with username={msg.username}")  # type: ignore[attr-defined]
        # Ensure user is authenticated
        if addr not in self.authenticated_users:
            denied = Denied("authentication required")
            self.send(denied, addr)
            logger.warning(f"Rejecting unauthenticated HELLO from {addr}")
            return

        # Already joined with this address?
        if self._find_slot_by_addr(addr):
            logger.debug(f"Ignoring duplicate HELLO from {addr}")
            return  # ignore duplicate

        # Reject if username already taken in current game
        existing_slot = self._find_slot_by_username(msg.username)  # type: ignore[attr-defined]
        if existing_slot and existing_slot.addr != addr:
            denied = Denied("username already active")
            self.send(denied, addr)
            logger.warning(f"Rejecting duplicate username {msg.username} from {addr}")
            return

        # Find free slot
        for i in (0, 1):
            if self.slots[i] is None:
                logger.debug(f"Assigning player {i} to {addr} with username={msg.username}")  # type: ignore[attr-defined]
                self.slots[i] = PlayerSlot(i, addr, paddle_y=self.game.H / 2 - self.game.PADDLE_H / 2, username=msg.username, last_pulse_time=time.perf_counter())
                welcome = Welcome(player_id=i)
                self.send(welcome, addr)
                logger.info(f"Player {i} joined from {addr}")
                break
        else:
            logger.warning(f"Game full, rejecting connection from {addr}")
            return

        # Start game once both players present
        if all(self.slots):
            # Reset game fresh and schedule a 2-second countdown before physics starts
            logger.info("Both players connected, resetting game state and starting countdown")
            self.game = GameState()
            self.game_running = True
            self.start_time = time.perf_counter() + 2.0  # 2-second grace
            logger.info("Both players connected. Game starts in 2 seconds …")
            logger.info(f"Player 0: {self.slots[0].username} from {self.slots[0].addr}")
            logger.info(f"Player 1: {self.slots[1].username} from {self.slots[1].addr}")

    def _handle_input(self, msg: Input, addr):
        logger.debug(f"Processing INPUT from {addr}, seq={msg.seq}, paddle_y={msg.paddle_y}")
        slot = self._find_slot_by_addr(addr)
        if slot is None:
            logger.warning(f"Received INPUT from unknown player {addr}")
            return  # unknown player
        slot.paddle_y = max(0, min(self.game.H - self.game.PADDLE_H, msg.paddle_y))
        logger.debug(f"Updated player {slot.id} paddle_y={slot.paddle_y}, last_pulse_time={slot.last_pulse_time}")
        self.game.paddles[slot.id] = slot.paddle_y

    def _process_network_packets(self):
        """Process all pending network packets in the UDP receive buffer."""
        packets_processed = 0
        while packets_processed < 100:  # Safety limit to prevent infinite loop
            try:
                data, addr = self.sock.recvfrom(4096)
                self.handle_packet(data, addr)
                packets_processed += 1
            except BlockingIOError:
                break  # No more packets waiting
        if packets_processed > 0:
            logger.debug(f"Processed {packets_processed} packets this cycle")
        return packets_processed

    def _check_player_timeouts(self, now):
        """Check for disconnected players."""
        logger.debug("Checking for disconnected players")
        for i, slot in enumerate(self.slots):
            if slot and now - slot.last_pulse_time > PLAYER_TIMEOUT:
                elapsed = now - slot.last_pulse_time
                logger.warning(f"Player {i} ({slot.username}) timed out after {elapsed:.1f}s")
                logger.debug(f"Last pulse time: {slot.last_pulse_time}, current time: {now}")
                
                # More lenient: only timeout if it's been a very long time
                if elapsed < PLAYER_TIMEOUT * 2:
                    logger.info(f"Giving player {i} extra time before timeout...")
                    continue
                
                self._handle_player_disconnect(i, slot)
                break  # only handle one disconnect per frame

    def _handle_player_disconnect(self, player_id, slot):
        """Handle a player disconnect by cleaning up and notifying other players."""
        if self.game_running:
            # Notify other player
            for other in self.slots:
                if other and other.id != player_id:
                    logger.info(f"Notifying player {other.id} about disconnect")
                    game_over = GameOver(reason="opponent_disconnected")
                    self.send(game_over, other.addr)
        
        # Clean up this game
        if slot.addr in self.authenticated_users:
            logger.debug(f"Removing {slot.addr} from authenticated_users")
            del self.authenticated_users[slot.addr]  # Remove from authenticated list
        logger.debug(f"Clearing slot {player_id}")
        self.slots[player_id] = None
        self.game_running = False
        logger.debug("Setting game_running=False")
        self.game = GameState()  # reset game state
        logger.debug("Reset game state")

    def _update_game_state(self, now, next_tick, tick_interval):
        """Update game physics and broadcast state to clients."""
        if not self.game_running:
            return next_tick  # No changes if game isn't running
            
        # Grace period before physics begins
        if self.start_time and now < self.start_time:
            # Keep sending neutral state so clients show countdown-like pause
            logger.debug(f"In grace period, {self.start_time - now:.1f}s remaining")
            self.broadcast_state()
            return next_tick
            
        # Grace period just ended
        if self.start_time is not None:
            logger.info("Grace period ended, starting game physics")
            next_tick = now  # reset so we don't try to catch up
            self.start_time = None
            
        # Time to update physics
        if now >= next_tick:
            logger.debug(f"Physics step at tick {self.game.tick}")
            self.game.step(tick_interval)
            self.broadcast_state()
            next_tick += tick_interval
            
        return next_tick

    # ------------- main loop ------------- #
    def run(self):
        TICK_RATE = 60
        tick_interval = 1.0 / TICK_RATE
        next_tick = time.perf_counter()
        last_timeout_check = time.perf_counter()  # Track last timeout check
        logger.info("Server running, waiting for players …")

        while True:
            # Process network
            packets_processed = self._process_network_packets()

            now = time.perf_counter()

            # Check for disconnected players (once per second)
            if now - last_timeout_check > 1.0:  
                logger.debug(f"Running timeout check after {now - last_timeout_check:.1f}s")
                self._check_player_timeouts(now)
                last_timeout_check = now

            # Update game state
            next_tick = self._update_game_state(now, next_tick, tick_interval)

            # Only sleep if we're inactive (no physics and no recent packets)
            if not self.game_running and packets_processed == 0:
                time.sleep(0.001)  # Tiny sleep to avoid 100% CPU when truly idle


def run_server_main(port: int = 9999):
    logger.info(f"Starting server on port {port}")
    server = PongServer(port=port)
    server.run() 