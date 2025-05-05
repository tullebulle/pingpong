# Pong

A real-time multiplayer Pong game implementation using UDP networking. This project demonstrates networking concepts in distributed systems including client-server architecture, state synchronization, and reliable communication over unreliable protocols.

![Pong Game](pong.png)

## Features

- **Real-time Multiplayer** - Play against others over the network with low-latency gameplay
- **User Authentication** - Create accounts, login, and track your game statistics
- **Matchmaking System** - Automatically pair with other waiting players
- **Client-side Prediction** - Smooth gameplay even under varying network conditions
- **Authoritative Server** - Prevent cheating with server-side physics verification
- **Scalable Architecture** - Support for multiple concurrent games through dynamic lobby creation

## Requirements

- Python 3.8 or higher
- Pygame library
- Network connectivity (UDP port access)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/udp-pong.git
   cd udp-pong
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Running the Server

Launch the server with optional port configuration (default is 9999)

```bash
python main.py server --port 9999
```

The server will initialize the database and begin listening for client connections. The first time it runs, it will create a new database file to store user accounts and statistics.

### Running the Client

Connect to a server by specifying its IP address and port. You can add as many clients as you want!

```bash
python main.py client <server_ip> --port 9999
```

For local testing, use `127.0.0.1` as the server IP address.

## Gameplay

1. **Login/Registration** - When you first launch the client, you'll be prompted to enter a username and password. If the account doesn't exist, it will be created automatically.

2. **Matchmaking** - After logging in, you'll be placed in the matchmaking queue until another player connects.

3. **Controls**:
   - **Up Arrow**: Move paddle up
   - **Down Arrow**: Move paddle down
   - **ESC**: Exit the game

4. **Scoring** - Score points by getting the ball past your opponent's paddle. The first player to reach 10 points wins the match.

## Architecture

The game uses a client-server architecture with:

- **UDP Protocol** - For low-latency communication essential for real-time gameplay
- **Authoritative Server** - Central server validates all game physics and state
- **Client-side Prediction** - Clients predict movement to hide network latency
- **Lobby System** - Separate game instances for each match, allowing multiple concurrent games
- **SQLite Database** - Persistent storage for user accounts and statistics

## Project Structure

udp-pong/

├── main.py # Entry point for both client and server

├── client.py # Client implementation with Pygame UI

├── server.py # Server and lobby management

├── protocol.py # Network protocol definitions

├── requirements.txt # Dependencies

└── test_pong.py # Test suite


## Troubleshooting

- **Connection Issues**: Ensure UDP ports are not blocked by firewalls
- **Display Problems**: Verify Pygame is correctly installed with `pip show pygame`
- **Lag/Stuttering**: Check your network connection and try reducing background network usage

## Development

Run the test suite to verify functionality:

```bash
python -m unittest test_pong.py
```

## Configuration

Game settings can be modified in `config.py`.

### Database Configuration

Database settings:
- `DB_FILENAME`: Name of the SQLite database file
- `DB_BUSY_TIMEOUT`: How long SQLite waits for a locked database before timing out (ms)
- `DB_MAX_RETRIES`: Maximum number of retry attempts for locked database operations
- `DB_RETRY_DELAY`: Initial delay between retries (with exponential backoff)

### Server Configuration

Server network settings:
- `SERVER_HOST`: IP address the server binds to (0.0.0.0 for all interfaces)
- `SERVER_PORT`: Port number for the main server
- `PLAYER_TIMEOUT`: Time in seconds before considering a player disconnected
- `LOBBY_PORT_RANGE`: Range of ports to use for game lobbies
- `MAX_LOBBIES`: Maximum number of concurrent game lobbies
- `MAX_PACKETS_PER_FRAME`: Maximum number of packets to process per frame
- `UDP_BUFFER_SIZE`: Size of UDP receive buffer in bytes
- `LOBBY_CLEANUP_TIMEOUT`: Seconds after game completion before cleaning up lobby
- `LOBBY_STATUS_CHECK_INTERVAL`: How often to check lobby status (seconds)
- `WAITING_PLAYER_CHECK_INTERVAL`: How often to check for inactive waiting players (seconds)

### Game Physics Configuration

Game mechanics settings:
- `GAME_WIDTH`: Width of the game area in pixels
- `GAME_HEIGHT`: Height of the game area in pixels
- `PADDLE_WIDTH`: Width of player paddles in pixels
- `PADDLE_HEIGHT`: Height of player paddles in pixels
- `BALL_SIZE`: Size of the ball in pixels
- `PADDLE_MARGIN`: Distance of paddles from the edge of the screen
- `BALL_SPEED`: Initial speed of the ball in pixels per second
- `TICK_RATE`: Number of physics updates per second
- `SCORE_LIMIT`: Score needed to win the game
- `GAME_START_DELAY`: Seconds between connecting players and starting game
- `COUNTDOWN_DURATION`: Seconds for countdown before ball starts moving

### Client Configuration

Client-side settings:
- `CLIENT_TARGET_FPS`: Target frames per second for client rendering
- `AUTH_RETRY_INTERVAL`: Seconds between authentication retry attempts
- `HELLO_RETRY_INTERVAL`: Seconds between HELLO message retry attempts
- `HEARTBEAT_INTERVAL`: Seconds between heartbeat messages
- `CLIENT_SERVER_TIMEOUT`: Seconds before considering server unresponsive
- `CLIENT_SERVER_WARNING`: Seconds of unresponsiveness to trigger warning
- `MESSAGE_DISPLAY_TIME`: Seconds to display status messages

### UI Configuration

User interface settings:
- `UI_DEFAULT_FONT_SIZE`: Default font size for UI elements
- `UI_LARGE_FONT_SIZE`: Larger font size for important UI elements
- `UI_GAME_OVER_DISPLAY_TIME`: Seconds to display game over message
- `UI_PADDLE_SPEED`: Movement speed of paddles in pixels per frame


## Testing

The project includes several test files to verify functionality of different components.

### Running Unit Tests

Run the basic unit tests with:

```bash
python -m unittest test_pong.py
```

This will test the core functionality including protocol message encoding/decoding, game physics calculations, and basic client-server communication patterns.

### Testing Database Concurrency

To test the database concurrency handling that ensures multiple game processes can simultaneously access the database without conflicts:

```bash
python db_concurrency_test.py
```

This test simulates multiple game lobby processes accessing the same user records simultaneously. It creates a dedicated test database, spawns 5 worker processes that each perform 50 database operations (creating users, recording game outcomes, checking stats), and verifies data integrity after completion. This test is particularly important to run after making any modifications to the database access code or changing concurrency parameters in `config.py`.