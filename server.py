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
import multiprocessing
import random
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import json

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
PLAYER_TIMEOUT = 3.0  # seconds before considering a player disconnected
LOBBY_PORT_RANGE = (10000, 20000)  # Range of ports to use for game lobbies
MAX_LOBBIES = 50  # Maximum number of concurrent game lobbies

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

# ------------------- Lobby Management ------------------ #
class LobbyStatus(IntEnum):
    """Status of a game lobby."""
    WAITING = 0   # Waiting for players
    ACTIVE = 1    # Game in progress
    COMPLETED = 2 # Game finished

@dataclass
class LobbyInfo:
    """Information about a game lobby."""
    lobby_id: int
    port: int
    process: multiprocessing.Process
    players: List[str]  # Usernames of players in this lobby
    creation_time: float
    status: LobbyStatus
    pipe_conn: multiprocessing.connection.Connection  # For communication with lobby process

class ServerDB:
    """Server-side user database for authentication and stats."""
    
    def __init__(self, db_path: str | os.PathLike | None = None):
        self.db_path = Path(db_path) if db_path else DB_FILE
        # Create connection and initialize schema
        with self._get_connection() as conn:
            conn.execute(_SCHEMA)
            conn.commit()
        print(f"Initialized user database at {self.db_path}")

    def _get_connection(self):
        """Get a new database connection. Always call this instead of reusing connections."""
        return sqlite3.connect(self.db_path)

    # --------------------------------------------------- #
    def add_user(self, username: str, password_hash: str) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
        except sqlite3.IntegrityError:
            raise ValueError("Username already exists")

    def verify_user(self, username: str, password_hash: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?", (username,)
            )
            row = cur.fetchone()
        if not row:
            return False
        return row[0] == password_hash

    # --------------------------------------------------- #
    def record_game(self, username: str, win: bool) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET games = games + 1, wins = wins + ?, losses = losses + ? WHERE username = ?",
                (1 if win else 0, 0 if win else 1, username,),
            )

    def get_stats(self, username: str) -> Tuple[int, int, int]:
        with self._get_connection() as conn:
            cur = conn.execute(
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
    def __init__(self, host: str = "0.0.0.0", port: int = 9999, db_path: str | os.PathLike | None = None, pipe_conn=None, lobby_id: int = -1):
        logger.info(f"Initializing game lobby {lobby_id} on {host}:{port}")
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind((host, port))
            self.sock.setblocking(False)
            logger.debug("Created non-blocking UDP socket")
        except OSError as e:
            logger.error(f"Failed to bind socket on {host}:{port}: {e}")
            if pipe_conn:
                pipe_conn.send({"type": "error", "message": f"Socket binding failed: {e}"})
            raise

        self.slots: List[Optional[PlayerSlot]] = [None, None]
        self.game = GameState()
        self.game_running = False
        self.start_time: float | None = None
        logger.debug("Game state initialized")
        
        try:
            # Authentication
            # Convert db_path to Path if it's a string
            if isinstance(db_path, str):
                db_path = Path(db_path)
            self.db = ServerDB(db_path)
            # Mapping of authenticated clients by address
            self.authenticated_users = {}  # addr -> username
            logger.debug("Authentication system initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            if pipe_conn:
                pipe_conn.send({"type": "error", "message": f"Database initialization failed: {e}"})
            raise
        
        # Lobby info
        self.lobby_id = lobby_id
        self.pipe_conn = pipe_conn
        self.status = LobbyStatus.WAITING

    # ------------- networking helpers ------------- #
    def send(self, msg, addr):
        self.sock.sendto(msg.encode(), addr)

    def update_authenticated_users(self):
        # get all authenticated users from the parent process
        if self.pipe_conn:
            self.pipe_conn.send({"type": "get_authenticated_users"})
            self.authenticated_users = self.pipe_conn.recv()

    def broadcast_state(self):
        
        # Get usernames from slots
        player0_username = self.slots[0].username if self.slots[0] else None
        player1_username = self.slots[1].username if self.slots[1] else None
        
        state_msg = State(
            tick=self.game.tick,
            ball_x=self.game.ball_x,
            ball_y=self.game.ball_y,
            paddle0_y=self.game.paddles[0],
            paddle1_y=self.game.paddles[1],
            score0=self.game.scores[0],
            score1=self.game.scores[1],
            player0_username=player0_username,
            player1_username=player1_username
        )
        payload = state_msg.encode()
        for slot in self.slots:
            if slot is not None:
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
        except ValueError as exc:
            logger.error(f"Bad packet from {addr}: {exc}")
            return
        if msg.type == MessageType.LOGIN:
            self._handle_login(msg, addr)  # type: ignore[arg-type]
        elif msg.type == MessageType.HELLO:
            self._handle_hello(msg, addr)
        else:
            if msg.type == MessageType.INPUT:
                self._handle_input(msg, addr)  # type: ignore[arg-type]
            elif msg.type == MessageType.PULSE:
                self._handle_pulse(msg, addr) 

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
    
    def _handle_pulse(self, msg: Pulse, addr):
        slot = self._find_slot_by_addr(addr)
        
        # Always echo pulse back to client even if not in slot
        return_msg = Pulse(username=msg.username)
        self.send(return_msg, addr)

    def _handle_login(self, msg: Login, addr):
        """Handle login request and respond with success/failure."""
        logger.debug(f"Processing LOGIN request for username={msg.username} from {addr}")
        self.update_authenticated_users()
        try:
            if self.db.verify_user(msg.username, msg.password_hash):
                # check if user is already logged in
                if self._find_slot_by_username(msg.username):
                    result = LoginResult(success=False, message="User already authenticated")
                    self.send(result, addr)
                    logger.warning(f"User {msg.username} already authenticated from {addr}")
                else:
                    # Login successful
                    logger.debug(f"Added {addr} to authenticated_users with username={msg.username}")
                    result = LoginResult(success=True, message="User authenticated")
                    self.send(result, addr)
                    logger.info(f"User {msg.username} authenticated from {addr}")
            else:
                # Try creating user if not exists
                try:
                    logger.debug(f"User {msg.username} not found, trying to create")
                    self.db.add_user(msg.username, msg.password_hash)
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
                
                # Notify parent process about player join
                if self.pipe_conn:
                    self.pipe_conn.send({"type": "player_joined", "username": msg.username, "slot": i})
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
            self.start_time = time.perf_counter()
            self.status = LobbyStatus.ACTIVE
            
            # Notify parent process that game is starting
            if self.pipe_conn:
                players = [slot.username for slot in self.slots if slot and slot.username]
                self.pipe_conn.send({"type": "game_started", "players": players})
                
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
        return packets_processed

    def _check_player_timeouts(self, now):
        """Check for disconnected players."""
        logger.debug(f"Connected players in Lobby {self.lobby_id}: {[slot.username for slot in self.slots if slot]}")
        for i, slot in enumerate(self.slots):
            if slot and now - slot.last_pulse_time > PLAYER_TIMEOUT:
                elapsed = now - slot.last_pulse_time
                logger.warning(f"Player {i} ({slot.username}) timed out after {elapsed:.1f}s")
                logger.debug(f"Last pulse time: {slot.last_pulse_time}, current time: {now}")
                
                # More lenient: only timeout if it's been a very long time
                if elapsed < PLAYER_TIMEOUT * 2:
                    logger.info(f"Giving player {i} extra time before timeout...")
                    continue
                
                # Player has definitely timed out - disconnect them
                logger.error(f"DISCONNECTING player {i} ({slot.username}) due to timeout after {elapsed:.1f}s")
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
            
        # Notify parent process about game over
        if self.pipe_conn:
            # Send a more detailed message including the disconnected user
            username = slot.username if slot and slot.username else "unknown"
            addr = slot.addr if slot else None
            self.pipe_conn.send({
                "type": "player_disconnected", 
                "player_id": player_id,
                "username": username,
                "addr": addr
            })
            self.status = LobbyStatus.COMPLETED
        
        # Clean up this game
        if slot and slot.addr in self.authenticated_users:
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
            next_tick = now  # reset so we don't try to catch up
            self.start_time = None
            
        # Time to update physics
        if now >= next_tick:
            self.game.step(tick_interval)
            self.broadcast_state()
            next_tick += tick_interval
            
        return next_tick

    def _check_parent_messages(self):
        """Check for messages from the parent process."""
        if not self.pipe_conn:
            return
            
        # Non-blocking check for messages
        if self.pipe_conn.poll():
            msg = self.pipe_conn.recv()
            if msg.get("type") == "shutdown":
                logger.info(f"Received shutdown request from parent process")
                # Notify players
                for slot in self.slots:
                    if slot:
                        game_over = GameOver(reason="server_shutdown")
                        self.send(game_over, slot.addr)
                # Exit the process
                return False
        return True

    # ------------- main loop ------------- #
    def run(self):
        TICK_RATE = 60
        tick_interval = 1.0 / TICK_RATE
        next_tick = time.perf_counter()
        last_timeout_check = time.perf_counter()  # Track last timeout check
        logger.info(f"Game lobby {self.lobby_id} running, waiting for players...")

        # Send ready signal to parent process
        if self.pipe_conn:
            self.pipe_conn.send({"type": "lobby_ready", "lobby_id": self.lobby_id})

        running = True
        while running:
            # Check for parent messages (shutdown, etc.)
            if self.pipe_conn and not self._check_parent_messages():
                break

            # Process network
            packets_processed = self._process_network_packets()

            now = time.perf_counter()

            # Check for disconnected players (once per second)
            if now - last_timeout_check > 1.0:  
                self._check_player_timeouts(now)
                last_timeout_check = now

            # Update game state
            next_tick = self._update_game_state(now, next_tick, tick_interval)

            # Only sleep if we're inactive (no physics and no recent packets)
            if not self.game_running and packets_processed == 0:
                time.sleep(0.001)  # Tiny sleep to avoid 100% CPU when truly idle

        logger.info(f"Game lobby {self.lobby_id} shutting down")


# Run a game lobby process in a separate function outside of the LobbyManager class
def run_lobby_process(host: str, port: int, lobby_id: int, pipe_conn, db_path: str):
    """Run a game lobby process."""
    try:
        # Create a new server instance with its own resources
        lobby = PongServer(host=host, port=port, pipe_conn=pipe_conn, lobby_id=lobby_id, db_path=db_path)
        lobby.run()
    except Exception as e:
        logger.error(f"Error in lobby {lobby_id}: {e}")
        if pipe_conn:
            pipe_conn.send({"type": "error", "message": str(e)})


class LobbyManager:
    """Manages multiple game lobbies for concurrent Pong games."""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 9999, db_path: str | os.PathLike | None = None):
        logger.info(f"Initializing lobby manager on {host}:{port}")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.setblocking(False)
        logger.debug("Created non-blocking UDP socket")
        
        self.host = host
        self.main_port = port
        self.db_path = DB_FILE if db_path is None else db_path
        # Convert Path to string to avoid pickling issues
        self.db_path_str = str(self.db_path)
        self.db = ServerDB(self.db_path)
        
        # Lobbies management
        self.next_lobby_id = 1
        self.lobbies: Dict[int, LobbyInfo] = {}
        self.waiting_players: Dict[str, Tuple[str, Tuple[str, int]]] = {}  # username -> (username, address)
        
        # Authentication tracking
        self.authenticated_users = {}  # addr -> username
        
        logger.info("Lobby manager initialized")
    
    def _create_new_lobby(self, first_player: Tuple[str, Tuple[str, int]]) -> int:
        """Create a new game lobby for the waiting player."""
        username, addr = first_player
        
        # Find an available port
        port = self._find_available_port()
        if not port:
            logger.error("Failed to find available port for new lobby")
            return -1
            
        # Create pipes for communication
        parent_conn, child_conn = multiprocessing.Pipe()
        
        # Create and start the game lobby process
        lobby_id = self.next_lobby_id
        self.next_lobby_id += 1
        
        # Pass only the necessary simple data types, not complex objects
        process = multiprocessing.Process(
            target=run_lobby_process,  # Use the standalone function instead of a method
            args=(self.host, port, lobby_id, child_conn, self.db_path_str),
            daemon=True
        )
        process.start()
        
        # Wait for ready signal from lobby
        if parent_conn.poll(5.0):  # Wait up to 5 seconds
            msg = parent_conn.recv()
            if msg.get("type") != "lobby_ready":
                logger.error(f"Unexpected message from lobby process: {msg}")
                process.terminate()
                return -1
        else:
            logger.error("Timeout waiting for lobby process to start")
            process.terminate()
            return -1
            
        # Store lobby info
        lobby_info = LobbyInfo(
            lobby_id=lobby_id,
            port=port,
            process=process,
            players=[username],
            creation_time=time.perf_counter(),
            status=LobbyStatus.WAITING,
            pipe_conn=parent_conn
        )
        self.lobbies[lobby_id] = lobby_info
        
        # Send redirect message to player
        self._send_lobby_redirect(addr, port, lobby_id)
        
        logger.info(f"Created new lobby {lobby_id} on port {port} for player {username}")
        return lobby_id
    
    def _find_available_port(self) -> int:
        """Find an available port for a new lobby."""
        # Try random ports from the range
        attempts = 0
        while attempts < 50:  # Limit attempts to avoid infinite loop
            port = random.randint(LOBBY_PORT_RANGE[0], LOBBY_PORT_RANGE[1])
            
            # Skip if port is already in use by another lobby
            if any(lobby.port == port for lobby in self.lobbies.values()):
                attempts += 1
                continue
                
            # Try to bind to this port
            try:
                test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                test_sock.bind((self.host, port))
                test_sock.close()
                return port
            except OSError:
                # Port is in use
                attempts += 1
        
        logger.error("Failed to find available port after 50 attempts")
        return 0
    
    def _send_lobby_redirect(self, addr: Tuple[str, int], port: int, lobby_id: int):
        """Send a message to the client redirecting them to the appropriate lobby."""
        # For now, we'll use the Denied message type with a special format to indicate a redirect
        redirect_msg = Denied(f"redirect:{port}:{lobby_id}")
        self.sock.sendto(redirect_msg.encode(), addr)
        logger.info(f"Sent redirect to {addr} for lobby {lobby_id} on port {port}")
    
    def _match_players(self, username: str, addr: Tuple[str, int]):
        """Match a player with a waiting player or create a new lobby."""
        if self.waiting_players:
            # Get the first waiting player
            wait_username, wait_info = next(iter(self.waiting_players.items()))
            wait_name, wait_addr = wait_info
            
            # Create a new lobby for these two players
            lobby_id = self._create_new_lobby((wait_name, wait_addr))
            if lobby_id > 0:
                # Add the second player to the lobby
                lobby = self.lobbies[lobby_id]
                lobby.players.append(username)
                
                # Send redirect to the second player
                self._send_lobby_redirect(addr, lobby.port, lobby_id)
                
                # Remove waiting player from list
                del self.waiting_players[wait_username]
                
                logger.info(f"Matched players {wait_name} and {username} in lobby {lobby_id}")
            else:
                # Failed to create lobby, add this player to waiting list
                self.waiting_players[username] = (username, addr)
                logger.error(f"Failed to create lobby, adding {username} to waiting list")
        else:
            # No waiting players, add this one to the list
            self.waiting_players[username] = (username, addr)
            logger.info(f"Added {username} to waiting list")
    
    def _handle_login(self, msg: Login, addr: Tuple[str, int]):
        """Handle login request and respond with success/failure."""
        logger.debug(f"Processing LOGIN request for username={msg.username} from {addr}")
        try:
            if self.db.verify_user(msg.username, msg.password_hash):
                # Check if user is already logged in
                if any(name == msg.username for name in self.authenticated_users.values()):
                    result = LoginResult(success=False, message="User already authenticated")
                    self.sock.sendto(result.encode(), addr)
                    logger.warning(f"User {msg.username} already authenticated from {addr}")
                else:
                    # Login successful
                    self.authenticated_users[addr] = msg.username
                    logger.debug(f"Added {addr} to authenticated_users with username={msg.username}")
                    result = LoginResult(success=True, message="User authenticated")
                    self.sock.sendto(result.encode(), addr)
                    logger.info(f"User {msg.username} authenticated from {addr}")
                    
                    # Check for existing lobbies with waiting players or create new lobby
                    self._match_players(msg.username, addr)
            else:
                # Try creating user if not exists
                try:
                    logger.debug(f"User {msg.username} not found, trying to create")
                    self.db.add_user(msg.username, msg.password_hash)
                    self.authenticated_users[addr] = msg.username
                    logger.debug(f"Added {addr} to authenticated_users with username={msg.username}")
                    result = LoginResult(success=True, message="User created")
                    self.sock.sendto(result.encode(), addr)
                    logger.info(f"New user {msg.username} created from {addr}")
                    
                    # Match with waiting player or add to waiting list
                    self._match_players(msg.username, addr)
                except ValueError:
                    # User exists but wrong password
                    result = LoginResult(success=False, message="Invalid credentials")
                    self.sock.sendto(result.encode(), addr)
                    logger.warning(f"Failed login attempt for {msg.username} from {addr} (wrong password)")
        except Exception as e:
            result = LoginResult(success=False, message=f"Error: {str(e)}")
            self.sock.sendto(result.encode(), addr)
            logger.error(f"Login error for {addr}: {e}")
    
    def _handle_hello(self, msg: Hello, addr: Tuple[str, int]):
        """Handle hello message by redirecting to the appropriate lobby."""
        logger.debug(f"Processing HELLO from {addr} with username={msg.username}")
        
        # Ensure user is authenticated
        if addr not in self.authenticated_users:
            # Check if this user was previously authenticated but in a different lobby
            username_exists = False
            for a, name in self.authenticated_users.items():
                if name == msg.username:
                    username_exists = True
                    break
                    
            if username_exists:
                # User exists but with different address - update the mapping
                logger.info(f"User {msg.username} reconnecting from new address {addr}")
                self.authenticated_users[addr] = msg.username
            else:
                # User not authenticated at all
                denied = Denied("authentication required")
                self.sock.sendto(denied.encode(), addr)
                logger.warning(f"Rejecting unauthenticated HELLO from {addr}")
                return
        
        # If user is in waiting list, continue waiting
        if msg.username in self.waiting_players:
            # Update the address in case it changed
            self.waiting_players[msg.username] = (msg.username, addr)
            
            # Send a message to let them know they're waiting
            wait_msg = Denied("waiting_for_opponent")
            self.sock.sendto(wait_msg.encode(), addr)
            return
        
        # Check if user should be in a specific lobby
        for lobby_id, lobby in self.lobbies.items():
            if msg.username in lobby.players and lobby.status != LobbyStatus.COMPLETED:
                # Send redirect to the correct lobby
                self._send_lobby_redirect(addr, lobby.port, lobby_id)
                logger.info(f"Redirecting {msg.username} to existing lobby {lobby_id}")
                return
        
        # If we get here, the user isn't in a lobby and isn't waiting
        # Add them to waiting list
        self.waiting_players[msg.username] = (msg.username, addr)
        logger.info(f"User {msg.username} not found in any lobby, adding to waiting list")
        wait_msg = Denied("waiting_for_opponent")
        self.sock.sendto(wait_msg.encode(), addr)
    
    def _handle_pulse(self, msg: Pulse, addr: Tuple[str, int]):
        """Handle pulse message by updating last activity time."""
        # Send pulse response immediately
        return_msg = Pulse(username=msg.username)
        self.sock.sendto(return_msg.encode(), addr)
        
        # Update last activity time for this address
        if not hasattr(self, '_last_activity_times'):
            self._last_activity_times = {}
        self._last_activity_times[addr] = time.perf_counter()
        
        # If player is waiting, update their address
        if msg.username in self.waiting_players:
            self.waiting_players[msg.username] = (msg.username, addr)
    
    def _check_lobby_status(self):
        """Check status of all lobbies and clean up completed ones."""
        now = time.perf_counter()
        lobbies_to_remove = []
        
        for lobby_id, lobby in self.lobbies.items():
            # Check for pipe messages
            if lobby.pipe_conn and lobby.pipe_conn.poll():
                msg = lobby.pipe_conn.recv()
                if msg.get("type") == "game_over":
                    logger.info(f"Lobby {lobby_id} reported game over: {msg.get('reason')}")
                    lobby.status = LobbyStatus.COMPLETED
                elif msg.get("type") == "game_started":
                    logger.info(f"Lobby {lobby_id} started game with players: {msg.get('players')}")
                    lobby.status = LobbyStatus.ACTIVE
                elif msg.get("type") == "player_joined":
                    logger.info(f"Player {msg.get('username')} joined lobby {lobby_id} in slot {msg.get('slot')}")
                    if msg.get('username') not in lobby.players:
                        lobby.players.append(msg.get('username'))
                elif msg.get("type") == "player_disconnected":
                    username = msg.get('username')
                    player_id = msg.get('player_id')
                    addr = msg.get('addr')
                    logger.info(f"Player {username} (ID: {player_id}) disconnected from lobby {lobby_id}")
                    
                    # Remove from authenticated users list if address is available
                    if addr and addr in self.authenticated_users:
                        print(f"Removing {addr} from authenticated_users in LOBBY MANAGER")
                        del self.authenticated_users[addr]
                        print(f"Authenticated users after removal: {self.authenticated_users}")
                    
                    # Remove from this lobby's player list
                    if username in lobby.players:
                        lobby.players.remove(username)
                        logger.info(f"Removed {username} from lobby {lobby_id} player list")
                    
                    # If both players are gone, mark lobby for cleanup
                    if not lobby.players:
                        logger.info(f"No players left in lobby {lobby_id}, marking for cleanup")
                        lobby.status = LobbyStatus.COMPLETED
                elif msg.get("type") == "get_authenticated_users":
                    lobby.pipe_conn.send(self.authenticated_users)
            
            # Check if process is still alive
            if not lobby.process.is_alive():
                logger.warning(f"Lobby {lobby_id} process died unexpectedly")
                
                # Remove any players in this lobby from authenticated users
                for player in lobby.players:
                    # Find their address in the authenticated_users dict
                    for addr, username in list(self.authenticated_users.items()):
                        if username == player:
                            logger.info(f"Removing {player} from authenticated users due to dead lobby")
                            del self.authenticated_users[addr]
                
                lobbies_to_remove.append(lobby_id)
                continue
            
            # Clean up completed games after a timeout
            if lobby.status == LobbyStatus.COMPLETED:
                age = now - lobby.creation_time
                if age > 60:  # 1 minute timeout for cleaning up completed games
                    logger.info(f"Cleaning up completed lobby {lobby_id} (age: {age:.1f}s)")
                    lobbies_to_remove.append(lobby_id)
        
        # Clean up lobbies that need removal
        for lobby_id in lobbies_to_remove:
            self._cleanup_lobby(lobby_id)
    
    def _cleanup_lobby(self, lobby_id):
        """Clean up resources for a lobby that's no longer needed."""
        if lobby_id not in self.lobbies:
            return
            
        lobby = self.lobbies[lobby_id]
        try:
            if lobby.pipe_conn:
                lobby.pipe_conn.send({"type": "shutdown"})
                lobby.pipe_conn.close()
            if lobby.process.is_alive():
                lobby.process.join(timeout=1.0)
                if lobby.process.is_alive():
                    logger.warning(f"Lobby {lobby_id} process didn't terminate, killing")
                    lobby.process.terminate()
        except Exception as e:
            logger.error(f"Error cleaning up lobby {lobby_id}: {e}")
        
        # Make sure any remaining players are removed from authenticated list
        for player in lobby.players:
            # Find their address in the authenticated_users dict
            for addr, username in list(self.authenticated_users.items()):
                if username == player:
                    logger.info(f"Removing {player} from authenticated users during cleanup")
                    del self.authenticated_users[addr]
        
        del self.lobbies[lobby_id]
        logger.info(f"Removed lobby {lobby_id}")
        
    def _check_waiting_players(self):
        """Check for inactive waiting players and remove them."""
        # Track the last time we received any communication from waiting players
        current_time = time.perf_counter()
        waiting_players_to_remove = []
        
        # Log the current waiting list
        if self.waiting_players:
            logger.debug(f"Current waiting players: {list(self.waiting_players.keys())}")
        
        # Check each waiting player's last activity time
        for username, (_, addr) in self.waiting_players.items():
            # Look up when we last heard from this address
            last_activity = getattr(self, '_last_activity_times', {}).get(addr, 0)
            if last_activity == 0:
                # First time seeing this player, initialize activity time
                if not hasattr(self, '_last_activity_times'):
                    self._last_activity_times = {}
                self._last_activity_times[addr] = current_time
            elif current_time - last_activity > PLAYER_TIMEOUT * 2:
                # More than double the timeout with no activity - player likely disconnected
                logger.warning(f"Waiting player {username} at {addr} inactive for {current_time - last_activity:.1f}s, removing")
                waiting_players_to_remove.append(username)
                
                # Also remove from authenticated users
                if addr in self.authenticated_users:
                    logger.info(f"Removing {username} from authenticated users due to inactivity")
                    del self.authenticated_users[addr]
                
                # Remove from activity tracking
                if addr in self._last_activity_times:
                    del self._last_activity_times[addr]
        
        # Remove inactive waiting players
        for username in waiting_players_to_remove:
            if username in self.waiting_players:
                del self.waiting_players[username]

    def _handle_packet(self, raw: bytes, addr: Tuple[str, int]):
        """Process a packet received on the main socket."""
        try:
            msg = decode(raw)
            
            # Update last activity time for this address
            if not hasattr(self, '_last_activity_times'):
                self._last_activity_times = {}
            self._last_activity_times[addr] = time.perf_counter()
        except ValueError as e:
            logger.error(f"Failed to decode packet from {addr}: {e}")
            return
            
        # Handle different message types
        if msg.type == MessageType.LOGIN:
            self._handle_login(msg, addr)  # type: ignore[arg-type]
        elif msg.type == MessageType.HELLO:
            self._handle_hello(msg, addr)  # type: ignore[attr-defined]
        elif msg.type == MessageType.PULSE:
            self._handle_pulse(msg, addr)  # type: ignore[attr-defined]
        else:
            logger.warning(f"Unexpected message type {msg.type} received on main socket")
    
    def run(self):
        """Main loop for the lobby manager."""
        logger.info("Lobby manager running")
        
        last_check_time = time.perf_counter()
        last_waiting_check_time = time.perf_counter()
        
        while True:
            # Process incoming packets
            try:
                data, addr = self.sock.recvfrom(4096)
                self._handle_packet(data, addr)
            except BlockingIOError:
                # No packets waiting
                pass
                
            # Periodically check lobby status
            now = time.perf_counter()
            if now - last_check_time > 1.0:  # Check every second
                self._check_lobby_status()
                last_check_time = now
                
            # Check for inactive waiting players less frequently
            if now - last_waiting_check_time > 5.0:  # Check every 5 seconds
                self._check_waiting_players()
                last_waiting_check_time = now
                
            # Sleep a tiny bit to avoid 100% CPU
            time.sleep(0.001)


def run_server_main(port: int = 9999):
    logger.info(f"Starting lobby manager on port {port}")
    manager = LobbyManager(port=port)
    manager.run() 