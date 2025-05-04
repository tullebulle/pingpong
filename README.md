# UDP Pong

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

## License

This project is licensed under the MIT License - see the LICENSE file for details.