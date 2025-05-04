from __future__ import annotations

"""UDP-based Pong game client.
Run with: python main.py client <server_ip> [server_port]
"""

import math
import socket
import sys
import threading
import time
import logging
import re
from dataclasses import dataclass
from typing import Tuple, Optional

import pygame
import hashlib
from copy import copy

from protocol import (
    Hello,
    Input,
    Login,
    LoginResult,
    MessageType,
    Pulse,
    State,
    Welcome,
    decode,
)

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [CLIENT] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('pong_client')

class Gui:
    """Handles rendering and input using pygame."""

    def __init__(self, width: int = 640, height: int = 480):
        pygame.init()
        self.width = width
        self.height = height
        self.paddle_height = 60 # height of the paddle
        self.paddle_width = 10 # width of the paddle
        self.ball_size = 10 # size of the ball
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption("UDP Pong")
        self.clock = pygame.time.Clock()
        pygame.font.init()
        self.font = pygame.font.Font(None, 36)
        self.username_font = pygame.font.Font(None, 48)  # Create font once
        self.cached_usernames = {}  # Cache for rotated username surfaces
        self.last_left_username = None
        self.last_right_username = None

    def _get_rotated_username_surface(self, username: str, is_left: bool) -> pygame.Surface:
        """Get a cached rotated username surface or create a new one."""
        cache_key = (username, is_left)
        if cache_key in self.cached_usernames:
            return self.cached_usernames[cache_key]
        
        # Create new surface if not in cache
        username_surface = self.username_font.render(username, True, (128, 128, 128))
        rotated_surface = pygame.transform.rotate(username_surface, 90 if is_left else -90)
        self.cached_usernames[cache_key] = rotated_surface
        return rotated_surface

    def poll_input(self) -> float | None:
        """Return new paddle y position based on user input, or None if unchanged."""
        dy = 0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP]:
            dy = -5
        elif keys[pygame.K_DOWN]:
            dy = 5
        if dy == 0:
            return None
        return dy

    def draw(self, state: State, player_id: int, local_paddle_y: float | None = None, left_username: str | None = None, right_username: str | None = None):
        white = (255, 255, 255)
        black = (0, 0, 0)
        self.screen.fill(black)

        # Derive paddle positions with optional local override (prediction) without
        # mutating the authoritative State instance.
        paddle0_y = state.paddle0_y
        paddle1_y = state.paddle1_y
        if local_paddle_y is not None:
            if player_id == 0:
                paddle0_y = local_paddle_y
            elif player_id == 1:
                paddle1_y = local_paddle_y

        # Draw paddles
        pygame.draw.rect(self.screen, white, (0, paddle0_y, 10, 60))
        pygame.draw.rect(
            self.screen,
            white,
            (self.width - 10, paddle1_y, 10, 60),
        )

        # Draw scores at the top center
        score_text = f"{state.score0} : {state.score1}"
        text_surface = self.font.render(score_text, True, white)
        text_rect = text_surface.get_rect(center=(self.width // 2, 20))
        self.screen.blit(text_surface, text_rect)

        # Draw usernames if available
        if left_username:
            # Only create/get surface if username changed
            if left_username != self.last_left_username:
                self.last_left_username = left_username
            
            # Get cached surface and draw it
            rotated_surface = self._get_rotated_username_surface(left_username, True)
            username_rect = rotated_surface.get_rect(midleft=(20, self.height // 2))
            self.screen.blit(rotated_surface, username_rect)

        if right_username:
            # Only create/get surface if username changed
            if right_username != self.last_right_username:
                self.last_right_username = right_username
            
            # Get cached surface and draw it
            rotated_surface = self._get_rotated_username_surface(right_username, False)
            username_rect = rotated_surface.get_rect(midright=(self.width - 20, self.height // 2))
            self.screen.blit(rotated_surface, username_rect)

        # Draw ball
        pygame.draw.rect(
            self.screen,
            white,
            (state.ball_x, state.ball_y, self.ball_size, self.ball_size),
        )

        # Flip
        pygame.display.flip()
        self.clock.tick(60)

    # ------------------ login helpers ------------------ #
    def _text_input_loop(self, prompt: str, is_password: bool = False) -> str:
        """Display a text input field and return the entered string."""
        text = ""
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        return text
                    elif event.key == pygame.K_BACKSPACE:
                        text = text[:-1]
                    elif event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit(0)
                    else:
                        if event.unicode and event.key < 256:
                            text += event.unicode

            # draw prompt
            self.screen.fill((0, 0, 0))
            rendered_prompt = self.font.render(prompt, True, (255, 255, 255))
            self.screen.blit(rendered_prompt, (20, self.height // 3))

            display_text = "*" * len(text) if is_password else text
            rendered_text = self.font.render(display_text, True, (255, 255, 255))
            self.screen.blit(rendered_text, (20, self.height // 3 + 40))

            pygame.display.flip()
            self.clock.tick(30)

    def login_screen(self) -> str:
        """Handle login / account creation. Returns authenticated username."""
        while True:
            username = self._text_input_loop("Enter username:")
            password = self._text_input_loop("Enter password:", is_password=True)

            # Return credentials to be validated by server
            return username, password

    def _show_message(self, text: str, pause: float = 1.0):
        self.screen.fill((0, 0, 0))
        rendered = self.font.render(text, True, (255, 255, 255))
        rect = rendered.get_rect(center=(self.width // 2, self.height // 2))
        self.screen.blit(rendered, rect)
        pygame.display.flip()
        pygame.time.delay(int(pause * 1000))

    def show_game_over(self, reason: str) -> None:
        """Show game over screen and wait for keypress to exit."""
        self.screen.fill((0, 0, 0))
        
        # Main message
        rendered = self.font.render("Game Over", True, (255, 255, 255))
        rect = rendered.get_rect(center=(self.width // 2, self.height // 3))
        self.screen.blit(rendered, rect)
        
        # Reason
        if reason == "opponent_disconnected":
            msg = "Your opponent has disconnected"
        else:
            msg = reason
            
        rendered = self.font.render(msg, True, (255, 255, 255))
        rect = rendered.get_rect(center=(self.width // 2, self.height // 2))
        self.screen.blit(rendered, rect)
        
        # Exit prompt
        rendered = self.font.render("Press any key to exit", True, (200, 200, 200))
        rect = rendered.get_rect(center=(self.width // 2, self.height * 2 // 3))
        self.screen.blit(rendered, rect)
        
        pygame.display.flip()
        
        # Wait for keypress or quit
        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    waiting = False
                elif event.type == pygame.KEYDOWN:
                    waiting = False
        
        pygame.quit()
        sys.exit(0)

    def show_waiting_for_opponent(self):
        """Show a message indicating the player is waiting for an opponent."""
        self.screen.fill((0, 0, 0))
        
        # Main message
        rendered = self.font.render("Waiting for an opponent...", True, (255, 255, 255))
        rect = rendered.get_rect(center=(self.width // 2, self.height // 2))
        self.screen.blit(rendered, rect)
        
        # Draw a simple animation to show activity
        t = time.time() * 2  # Animation speed
        dots = "." * (1 + int(t % 3))
        rendered = self.font.render(dots, True, (255, 255, 255))
        rect = rendered.get_rect(center=(self.width // 2, self.height // 2 + 40))
        self.screen.blit(rendered, rect)
        
        pygame.display.flip()
        self.clock.tick(10)  # Lower framerate while waiting


class PongClient:
    def __init__(self, server_addr: Tuple[str, int], gui: Gui):
        logger.info(f"Initializing client connecting to {server_addr}")
        self.server_addr = server_addr
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        logger.debug("Created non-blocking UDP socket")
        self.seq = 0
        self.player_id = -1
        self.state: State | None = None
        self.gui = gui
        self.username = None  # Will be set after authentication
        self.password_hash = None  # Store hashed password for reconnection attempts
        self.authenticated = False
        self.last_auth_attempt = time.perf_counter()
        self.last_hello_attempt = time.perf_counter()
        self.hello_sent = False  # Track if HELLO was sent
        self.waiting_for_opponent = False  # Flag indicating if we're waiting for matchmaking
        # Initialize with current time to avoid immediate timeout
        current_time = time.perf_counter()
        self.pulse_to_server_time = current_time
        self.pulse_from_server_time = current_time
        self.opponent_username = None  # Track opponent's username
        
        # Lobby info
        self.lobby_id = -1
        self.in_lobby = False
        self.lobby_server_addr = None
        
        # Grace period detection
        self.grace_period = True  # Assume we start in grace period
        self.last_ball_pos = None  # Track last ball position
        self.physics_started = False  # Flag to track when physics actually starts
        
        logger.debug("Client initialized with default state")

    # ------------- networking helpers ------------- #
    def send(self, msg):
        """Send a message to the current server (either main or lobby)."""
        target_addr = self.lobby_server_addr if self.in_lobby else self.server_addr
        logger.debug(f"Sending {msg.__class__.__name__} packet to {'lobby' if self.in_lobby else 'main'} server at {target_addr}")
        try:
            self.sock.sendto(msg.encode(), target_addr)
            self.pulse_to_server_time = time.perf_counter()
        except Exception as e:
            logger.error(f"Failed to send {msg.__class__.__name__} packet: {e}")

    def _recv_packets(self):
        """Process all available packets in the UDP receive buffer."""
        latest = None
        count = 0
        while count < 30:  # Process at most 30 packets per frame to prevent indefinite loops
            try:
                raw, addr = self.sock.recvfrom(4096)
                latest = raw
                logger.debug(f"Received data from {addr} in main loop")
                self._handle_packet(latest)
                count += 1
            except BlockingIOError:
                break
            except Exception as e:
                logger.error(f"Error receiving packet: {e}")
                break
        return count > 0  # Return True if at least one packet was received

    def _handle_redirect(self, reason: str) -> bool:
        """Handle server redirect messages.
        Returns True if redirect was handled, False otherwise."""
        # Parse redirect message format: "redirect:port:lobby_id"
        redirect_match = re.match(r"redirect:(\d+):(\d+)", reason)
        if redirect_match:
            port_str, lobby_id_str = redirect_match.groups()
            try:
                new_port = int(port_str)
                new_lobby_id = int(lobby_id_str)
                
                # Store lobby information
                host = self.server_addr[0]  # Same host, different port
                self.lobby_server_addr = (host, new_port)
                self.lobby_id = new_lobby_id
                self.in_lobby = True
                self.player_id = -1  # Reset player ID for new lobby
                self.state = None    # Reset game state
                self.hello_sent = False  # Need to send HELLO to new lobby
                
                logger.info(f"Redirecting to lobby {new_lobby_id} at {host}:{new_port}")
                self.gui._show_message(f"Joining game lobby {new_lobby_id}...", pause=0.5)
                
                # Send HELLO to the new lobby immediately
                logger.info(f"Sending HELLO to lobby with username {self.username}")
                hello = Hello(username=self.username)
                self.send(hello)
                self.hello_sent = True
                self.last_hello_attempt = time.perf_counter()
                
                return True
            except ValueError:
                logger.error(f"Invalid redirect format: {reason}")
                return False
        
        # Handle waiting_for_opponent message
        if reason == "waiting_for_opponent":
            logger.info("Waiting for opponent. In matchmaking queue.")
            self.waiting_for_opponent = True
            return True
            
        return False  # Not a redirect message

    def _handle_packet(self, raw):
        try:
            msg = decode(raw)
            logger.info(f"Received packet: {msg.__class__.__name__} (type={msg.type})")
            # ALWAYS update pulse time for ANY packet from server
            self.pulse_from_server_time = time.perf_counter()
            logger.debug(f"Updated pulse_from_server_time to {self.pulse_from_server_time}")
        except ValueError as e:
            logger.error(f"Failed to decode packet: {e}")
            return
        
        if msg.type == MessageType.WELCOME:
            self.player_id = msg.player_id  # type: ignore[attr-defined]
            logger.info(f"Assigned player_id={self.player_id}")
            # Reset hello state once WELCOME is received
            self.hello_sent = False
            self.waiting_for_opponent = False
            logger.debug("Reset hello_sent flag")
            
            # Also reset grace period detection
            self.grace_period = True
            self.last_ball_pos = None
            self.physics_started = False

        elif msg.type == MessageType.STATE:
            logger.debug(f"Received STATE update: ball=({msg.ball_x:.1f},{msg.ball_y:.1f}), " +  # type: ignore[attr-defined]
                         f"scores={msg.score0}-{msg.score1}")  # type: ignore[attr-defined]
            
            # Detect grace period end by tracking when ball actually moves
            current_pos = (msg.ball_x, msg.ball_y)  # type: ignore[attr-defined]
            
            if self.last_ball_pos is None:
                # First state packet, just record position
                self.last_ball_pos = current_pos
            elif self.grace_period and self.last_ball_pos != current_pos:
                # Ball position changed - physics has started
                logger.info(f"Detected physics start: ball moved from {self.last_ball_pos} to {current_pos}")
                self.grace_period = False
                self.physics_started = True
            
            # Update last ball position
            self.last_ball_pos = current_pos
                
            # Update state
            self.state = msg  # type: ignore[assignment]
            
            # Update opponent's username from state message
            if self.player_id == 0:
                self.opponent_username = msg.player1_username  # type: ignore[attr-defined]
            else:
                self.opponent_username = msg.player0_username  # type: ignore[attr-defined]
            
            if self.opponent_username:
                logger.debug(f"Updated opponent username to: {self.opponent_username}")
            
        elif msg.type == MessageType.DENIED:
            # Check if this is a redirect message
            if hasattr(msg, 'reason'):
                if self._handle_redirect(msg.reason):
                    return
            
            # If not a redirect, show error and exit
            reason = getattr(msg, 'reason', 'duplicate user')
            logger.warning(f"Received DENIED message: {reason}")
            
            # Special case: If server asks for re-authentication, try to re-login instead of exiting
            if reason == "authentication required" and self.username and self.password_hash:
                logger.info(f"Re-authentication required. Attempting to reconnect...")
                self.gui._show_message("Session expired. Reconnecting...", pause=0.5)
                
                # Reset state
                self.authenticated = False
                self.player_id = -1
                self.opponent_username = None
                logger.debug("Reset authentication state")
                
                # Re-authenticate
                login_msg = Login(username=self.username, password_hash=self.password_hash)
                self.send(login_msg)
                self.last_auth_attempt = time.perf_counter()
                logger.info("Sent re-authentication request")
                return
            
            # For other denial reasons, exit the game
            self.gui._show_message(f"Login denied: {reason}", pause=2)
            logger.error(f"Login denied: {reason}")
            pygame.quit()
            sys.exit(1)

        elif msg.type == MessageType.LOGIN_RESULT:
            # This is now handled in handle_auth() during the authentication phase
            # Only handle it here if we're in the main loop (re-authentication scenario)
            if not self.authenticated and msg.success:  # type: ignore[attr-defined]
                logger.info(f"Re-authentication successful")
                self.authenticated = True
                
                # Send HELLO immediately after re-authentication
                hello = Hello(username=self.username)
                self.send(hello)
                self.hello_sent = True
                self.last_hello_attempt = time.perf_counter()
                logger.debug("Sent HELLO after re-authentication")
                
        elif msg.type == MessageType.GAME_OVER:
            # Handle game over (opponent disconnected, etc.)
            logger.info(f"Game over: {msg.reason}")  # type: ignore[attr-defined]
            self.gui.show_game_over(msg.reason)  # type: ignore[attr-defined]
            self.opponent_username = None  # Reset opponent username on game over


    def handle_auth(self):
        """Handle authentication and return False when completed to exit the loop."""
        logger.debug("In handle_auth() loop")
        # Process events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                logger.info("Quit event received during auth")
                pygame.quit()
                sys.exit(0)
        
        # Already authenticated in a previous iteration?
        if self.authenticated:
            logger.debug("Already authenticated, exiting auth loop")
            return False  # Exit the authentication loop
        
        # Drain network to process responses
        packets_received = 0
        while packets_received < 10:
            try:
                raw, addr = self.sock.recvfrom(4096)
                try:
                    msg = decode(raw)
                    logger.info(f"Auth: Received {msg.__class__.__name__} packet from {addr}")
                    
                    # Handle authentication-related messages directly here
                    if msg.type == MessageType.LOGIN_RESULT:
                        if msg.success:  # type: ignore[attr-defined]
                            logger.info(f"Login successful: {msg.message}")  # type: ignore[attr-defined]
                            self.gui._show_message(f"Login successful: {msg.message}", pause=0.5)  # type: ignore[attr-defined]
                            self.authenticated = True
                            logger.debug("Set authenticated=True")
                           
                            # Send HELLO immediately after authentication
                            logger.info(f"Sending HELLO immediately after auth with username {self.username}")
                            hello = Hello(username=self.username)
                            self.send(hello)
                            self.hello_sent = True
                            self.last_hello_attempt = time.perf_counter()
                            logger.debug(f"Set hello_sent=True, last_hello_attempt={self.last_hello_attempt}")
                            
                            # Exit the auth loop on success
                            return False
                        else:
                            logger.error(f"Login failed: {msg.message}")  # type: ignore[attr-defined]
                            self.gui._show_message(f"Login failed: {msg.message}", pause=2.0)  # type: ignore[attr-defined]
                            
                            # Retry or exit
                            if "Error:" in msg.message:  # type: ignore[attr-defined]
                                # Server error, likely a critical issue
                                logger.error(f"Critical server error: {msg.message}")  # type: ignore[attr-defined]
                                pygame.quit()
                                sys.exit(1)
                            
                            # For other errors, we'll retry with a new login
                            self.last_auth_attempt = time.perf_counter() - 3.0  # Force retry soon
                    else:
                        # Let the regular handler take care of other messages
                        self._handle_packet(raw)
                except ValueError as e:
                    logger.error(f"Failed to decode packet during auth: {e}")
                
                packets_received += 1
            except BlockingIOError:
                break
            except Exception as e:
                logger.error(f"Error receiving packet during auth: {e}")
                break
            
        # Display "connecting" screen
        self.gui.screen.fill((0, 0, 0))
        wait_msg = self.gui.font.render("Connecting to server...", True, (255, 255, 255))
        rect = wait_msg.get_rect(center=(self.gui.width // 2, self.gui.height // 2))
        self.gui.screen.blit(wait_msg, rect)
        
        # Retry login periodically
        if time.perf_counter() - self.last_auth_attempt > 2.0 and self.username and self.password_hash:
            logger.info(f"Retrying LOGIN with username {self.username}")
            login_msg = Login(username=self.username, password_hash=self.password_hash)
            self.send(login_msg)
            self.last_auth_attempt = time.perf_counter()
            logger.debug(f"Updated last_auth_attempt={self.last_auth_attempt}")
        
        pygame.display.flip()
        self.gui.clock.tick(30)
        
        # Continue authentication loop
        return True

    def _send_heartbeat(self):
        """Send periodic heartbeat messages to keep connection alive."""
        time_since_pulse = time.perf_counter() - self.pulse_to_server_time
        if time_since_pulse > 2.0:
            # If we're authenticated but not in a lobby, or we're in a lobby but not yet assigned a player ID,
            # send a HELLO to help with reconnection
            if self.authenticated and (not self.in_lobby or self.player_id == -1):
                # It's been longer than normal between messages, try sending HELLO instead of PULSE
                logger.info(f"Sending HELLO as heartbeat (username={self.username})")
                hello = Hello(username=self.username)
                self.send(hello)
                self.hello_sent = True
                self.last_hello_attempt = time.perf_counter()
            else:
                # Normal pulse
                pulse = Pulse(username=self.username)
                self.send(pulse)
                logger.info(f"Sending PULSE to keep connection alive")
            
            self.pulse_to_server_time = time.perf_counter()
    
    def _check_server_timeout(self):
        """Check if server has been unresponsive for too long."""
        elapsed = time.perf_counter() - self.pulse_from_server_time
        
        # Different thresholds based on connection state
        if elapsed > 8.0:
            # Hard timeout - exit the game
            logger.error(f"Server not responding for {elapsed:.1f} seconds, quitting")
            self.gui.show_game_over("Server not responding... shutting down")
            time.sleep(2)
            pygame.quit()
            sys.exit(1)
        elif elapsed > 5.0 and self.authenticated:
            # Try resetting connection to main server
            logger.warning(f"Server unresponsive for {elapsed:.1f} seconds, attempting reconnection")
            
            # Reset lobby state if we were in one
            if self.in_lobby:
                logger.info("Resetting lobby connection and reconnecting to main server")
                self.in_lobby = False
                self.lobby_server_addr = None
                self.player_id = -1
                self.state = None
                self.waiting_for_opponent = False
                
                # Send HELLO to main server to try reconnecting
                hello = Hello(username=self.username)
                self.send(hello)
                self.hello_sent = True
                self.last_hello_attempt = time.perf_counter()
                
                # Reset timeout counter to give reconnection a chance
                self.pulse_from_server_time = time.perf_counter() - 2.0  # Give 6 more seconds
                
                # Show a message to the user
                self.gui._show_message("Connection issue, attempting to reconnect...", pause=1.0)
            
    def _handle_waiting_for_player_id(self):
        """Handle state when waiting for server to assign a player ID."""
        # Retry HELLO if needed
        if self.authenticated and self.player_id == -1 and self.username:
            time_since_hello = time.perf_counter() - self.last_hello_attempt
            logger.debug(f"Time since last HELLO: {time_since_hello:.1f}s")
            if time_since_hello > 1.0:
                logger.info(f"Retrying HELLO with username {self.username}")
                hello = Hello(username=self.username)
                self.send(hello)
                self.last_hello_attempt = time.perf_counter()
                logger.debug(f"Updated last_hello_attempt={self.last_hello_attempt}")
        
        # Draw waiting screen
        self.gui.screen.fill((0, 0, 0))
        
        # Different message depending on connection state
        if self.in_lobby:
            wait_msg = self.gui.font.render("Waiting for game to assign a player ID...", True, (255, 255, 255))
        else:
            wait_msg = self.gui.font.render("Connecting to game server...", True, (255, 255, 255))
        
        rect = wait_msg.get_rect(center=(self.gui.width // 2, self.gui.height // 2))
        self.gui.screen.blit(wait_msg, rect)
        self._handle_events()
        pygame.display.flip()
        self.gui.clock.tick(60)
    
    def _handle_waiting_for_opponent(self):
        """Handle state when waiting for another player to join."""
        # Draw waiting screen
        self.gui.show_waiting_for_opponent()
        self._handle_events()
    
    def _handle_active_game(self, last_paddle_y):
        """Handle state when game is active with both players."""
        logger.debug(f"Have game state, handling input and rendering")
        dy = self.gui.poll_input()
        if dy is not None:
            logger.debug(f"Input detected, dy={dy}")
            last_paddle_y = max(0, min(self.gui.height - 60, last_paddle_y + dy))
            inp = Input(seq=self.seq, paddle_y=last_paddle_y)
            self.seq += 1
            self.send(inp)
            logger.debug(f"Sent INPUT seq={self.seq-1}, paddle_y={last_paddle_y}")
        
        # Determine which username goes on which side
        if self.player_id == 0:
            left_username = self.username
            right_username = self.opponent_username
        else:
            left_username = self.opponent_username
            right_username = self.username
        
        # Create a modified state for rendering during grace period
        render_state = self.state
        if self.grace_period and not self.physics_started:
            # During grace period, create a copy of state with centered ball
            render_state = copy(self.state)
            # Center the ball exactly
            render_state.ball_x = self.gui.width / 2 - self.gui.ball_size / 2
            render_state.ball_y = self.gui.height / 2 - self.gui.ball_size / 2
        
        logger.debug(f"DRAWING GAME. Grace period: {self.grace_period}")
        self.gui.draw(render_state, self.player_id, local_paddle_y=last_paddle_y, 
                     left_username=left_username, right_username=right_username)
        return last_paddle_y
    
    def _handle_events(self):
        """Process pygame events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                logger.info("Quit event received")
                pygame.quit()
                sys.exit(0)
    
    # ------------- main loop ------------- #
    def run(self):
        # Authentication state
        waiting_auth = True
        logger.info("Starting authentication process")
        
        # Before handshake, need to authenticate
        while waiting_auth:
            waiting_auth = self.handle_auth()
        
        logger.info("Authentication successful, entering main game loop")
        # Update server pulse time on successful auth to prevent immediate timeout
        self.pulse_from_server_time = time.perf_counter()
        logger.debug(f"Updated pulse_from_server_time={self.pulse_from_server_time}")
        
        # Now that we're connected and authenticated, start the main game loop
        last_paddle_y = self.gui.height / 2 - 30
        
        # Main game loop with consistent frame timing
        target_fps = 60
        frame_time_target = 1.0 / target_fps
        
        try:
            while True:
                loop_start = time.perf_counter()
                
                # Network handling
                packets_received = self._recv_packets()
                
                self._check_server_timeout()
                self._send_heartbeat()
                
                # State handling
                if self.state:
                    # Active game state
                    last_paddle_y = self._handle_active_game(last_paddle_y)
                else:
                    # Waiting state
                    if self.waiting_for_opponent: #WAITING IN LOBBY
                        # Still in matchmaking
                        self._handle_waiting_for_opponent()
                    elif self.player_id == -1: #WAITING FOR PLAYER ID ASSIGNMENT
                        # Waiting for player ID assignment
                        self._handle_waiting_for_player_id()
                    else:
                        # Waiting for game to start
                        self._handle_waiting_for_opponent()
                
                # Calculate how much time to sleep to maintain target framerate
                elapsed = time.perf_counter() - loop_start
                sleep_time = max(0, frame_time_target - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
                # Log frame time
                frame_time = time.perf_counter() - loop_start
                    
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.gui.show_game_over(f"Client error: {str(e)}")
            time.sleep(2)
            pygame.quit()
            sys.exit(1)

    def _hash_password(self, password: str) -> str:
        """Hash a password using SHA-256 before sending it over the network."""
        return hashlib.sha256(password.encode()).hexdigest()


def run_client_main(server_ip: str, port: int = 9999):
    logger.info(f"Starting client connecting to {server_ip}:{port}")
    gui = Gui()
    client = PongClient((server_ip, port), gui=gui)
    
    # Get login credentials
    username, password = gui.login_screen()
    logger.info(f"User entered credentials for username: {username}")
    
    # Hash the password before sending
    password_hash = client._hash_password(password)
    logger.debug("Password hashed for security")
    
    # Send login request
    login_msg = Login(username=username, password_hash=password_hash)
    client.username = username  # Store username for later use
    client.password_hash = password_hash  # Store password hash for reconnection attempts
    client.last_auth_attempt = time.perf_counter()  # Track login retries

    client.send(login_msg)
    logger.info(f"Initial LOGIN sent with username {username}")
    
    # Give server a moment to process initial login
    gui._show_message("Authenticating with server...", pause=0.5)
    
    client.run()