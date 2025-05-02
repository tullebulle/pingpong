from __future__ import annotations

"""UDP-based Pong game client.
Run with: python main.py client <server_ip> [server_port]
"""

import math
import socket
import sys
import threading
import time
from dataclasses import dataclass
from typing import Tuple

import pygame

from protocol import (
    Hello,
    Input,
    MessageType,
    State,
    Welcome,
    decode,
)


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

    def draw(self, state: State, player_id: int, local_paddle_y: float | None = None):
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

        # Draw ball
        pygame.draw.rect(
            self.screen,
            white,
            (state.ball_x, state.ball_y, self.ball_size, self.ball_size),
        )

        # Draw scores at the top center
        score_text = f"{state.score0} : {state.score1}"
        text_surface = self.font.render(score_text, True, white)
        text_rect = text_surface.get_rect(center=(self.width // 2, 20))
        self.screen.blit(text_surface, text_rect)

        # Flip
        pygame.display.flip()
        self.clock.tick(60)


class PongClient:
    def __init__(self, server_addr: Tuple[str, int]):
        self.server_addr = server_addr
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.seq = 0
        self.player_id = -1
        self.state: State | None = None
        self.gui = Gui()

    # ------------- networking helpers ------------- #
    def send(self, msg):
        self.sock.sendto(msg.encode(), self.server_addr)

    def _handle_packet(self, raw):
        try:
            msg = decode(raw)
        except ValueError:
            return
        if msg.type == MessageType.WELCOME:
            self.player_id = msg.player_id  # type: ignore[attr-defined]
            print("Received player id", self.player_id)
        elif msg.type == MessageType.STATE:
            self.state = msg  # type: ignore[assignment]

    # ------------- main loop ------------- #
    def run(self):
        # handshake
        hello = Hello(name="player")
        self.send(hello)

        last_paddle_y = self.gui.height / 2 - 30
        while True:
            # Drain the socket – keep only the newest State
            latest = None
            while True:
                try:
                    raw, _ = self.sock.recvfrom(4096)
                    latest = raw
                except BlockingIOError:
                    break
            if latest:
                self._handle_packet(latest)

            dy = self.gui.poll_input()
            if dy is not None:
                last_paddle_y = max(0, min(self.gui.height - 60, last_paddle_y + dy))
                inp = Input(seq=self.seq, paddle_y=last_paddle_y)
                self.seq += 1
                self.send(inp)

            if self.state:
                self.gui.draw(self.state, self.player_id, local_paddle_y=last_paddle_y)
            else:
                # No state yet: simple waiting screen
                self.gui.screen.fill((0, 0, 0))
                pygame.display.flip()
                self.gui.clock.tick(60)


def run_client_main(server_ip: str, port: int = 9999):
    client = PongClient((server_ip, port))
    client.run() 