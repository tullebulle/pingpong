"""
Configuration parameters for Pong game server and client
"""

# Server configuration
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 9999
PLAYER_TIMEOUT = 3.0  # seconds before considering a player disconnected
LOBBY_PORT_RANGE = (10000, 20000)  # Range of ports to use for game lobbies
MAX_LOBBIES = 50  # Maximum number of concurrent game lobbies
MAX_PACKETS_PER_FRAME = 30  # Maximum number of packets to process per frame
UDP_BUFFER_SIZE = 4096  # Size of UDP receive buffer
LOBBY_CLEANUP_TIMEOUT = 60  # Seconds after game completion before cleaning up lobby
LOBBY_STATUS_CHECK_INTERVAL = 1.0  # How often to check lobby status (seconds)
WAITING_PLAYER_CHECK_INTERVAL = 5.0  # How often to check for inactive waiting players (seconds)

# Database configuration
DB_FILENAME = "server.db"
DB_BUSY_TIMEOUT = 5000  # Milliseconds to wait if database is locked
DB_MAX_RETRIES = 5      # Maximum number of retries for locked database
DB_RETRY_DELAY = 0.1    # Initial delay between retries (exponential backoff applied)

# Game physics configuration
GAME_WIDTH = 640
GAME_HEIGHT = 480
PADDLE_WIDTH = 10
PADDLE_HEIGHT = 60
BALL_SIZE = 10
PADDLE_MARGIN = 0  # x-offset of paddles from edge
BALL_SPEED = 300.0  # px/s (initial)
TICK_RATE = 60  # physics updates per second
SCORE_LIMIT = 10  # score to win the game
GAME_START_DELAY = 2.0  # seconds between connecting players and starting game
COUNTDOWN_DURATION = 0.0  # seconds for countdown before ball starts moving

# Client configuration
CLIENT_TARGET_FPS = 60  # target frames per second for client
AUTH_RETRY_INTERVAL = 2.0  # seconds between authentication retries
HELLO_RETRY_INTERVAL = 1.0  # seconds between HELLO message retries
HEARTBEAT_INTERVAL = 2.0  # seconds between heartbeat messages
CLIENT_SERVER_TIMEOUT = 8.0  # seconds before considering server unresponsive
CLIENT_SERVER_WARNING = 5.0  # seconds of unresponsiveness to trigger warning
MESSAGE_DISPLAY_TIME = 1.0  # seconds to display status messages

# UI configuration
UI_DEFAULT_FONT_SIZE = 36
UI_LARGE_FONT_SIZE = 48
UI_GAME_OVER_DISPLAY_TIME = 2.0  # seconds to display game over message
UI_PADDLE_SPEED = 5  # pixels per frame 