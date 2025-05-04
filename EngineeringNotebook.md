# UDP Pong Game - Engineering Notebook

## Project Overview
For our final porejct, we implemented a multiplayer `Pong' game. Users can create accounts and play against other users selected from a queue of users currently waiting to play. The project includes user authentication, matchmaking, game lobbies, and a real-time physics simulation for the Pong game itself.

### Client-Server Communication
In the communication between the server and the clients, there is a tradeoff between ensuring every message gets received correctly and making sure messages get received quickly. In most usecases we considered in class, it was crucial that each message is sent in full with a confirmation of receipt being returned. The message rate was reasonably low and it was acceptable if the time between sending a message and the receiver fully receiving the message was on the scale of tenths of seconds. Here, however, in the context of the game, the requirements are different. Game-relevant communication between the server and the players needs to be fast -- on the scale of hundreths of seconds -- but the consequences of singular messages getting lost or messages arriving slgihtly out of order are not too high.

To make the communication in our game work efficiently and satisfy the described demand, we are using the UDP communication protocol -- instead of TCP as seen in class. This communication protocol is very common in the usecase of online games. UDP (User Datagram Protocol) consists of a client-server architecture where the server is authoritative about the game state, and clients connect to the singular server.

Since our Pong game is being player in real-time, we need to optimize for a minimal delay between player input and the visual feedback. Unlike TCP, which establishes a formal connection between sender and receiver through a three-way handshake, UDP simply sends packets without any prior setup or confirmation. In TCP, as we saw in our socket programming examples in class, the client and server must first synchronize sequence numbers and acknowledge each other before any actual data can be transmitted -- a process that typically takes three round trips and adds noticeable delay. UDP, however, operates more like dropping a letter in a mailbox -- the sender dispatches the packet and moves on without waiting for confirmation that the connection is established. This "fire-and-forget" approach means that when a player f.e. presses "up" on their keyboard, the input is immediately sent to the server without waiting for any connection formalities, resulting in more responsive gameplay. While this introduces the possibility that some packets might get lost in transit, the regularly timed game state updates ensure that any temporary inconsistencies are quickly corrected in subsequent frames -- making this tradeoff desirable for our real-time gaming application. Thus, UDP's connectionless nature eliminates the overhead of connection establishment, acknowledgments, and flow control.

When considering the specific mechanics of our implementation, we can observe how the game naturally accommodates packet loss in several ways. For instance, if a player's paddle movement input packet is lost during transmission, the resulting momentary discrepancy is quickly remedied when the next input packet arrives a fraction of a second later -- the player might notice a slight hiccup in responsiveness, but the overall gameplay continues uninterrupted. Similarly, if the server's state update packet containing ball position is lost en route to a client, the subsequent update (arriving approximately 16 milliseconds later at 60 updates per second) will correct any visual inconsistencies without meaningful gameplay impact. This inherent resilience is further enhanced by our authoritative server architecture, where the server maintains the "ground truth" of the game state, ensuring that temporary client-side deviations due to packet loss are quickly resolved. We improved this natural tolerance by implementing our tick-based game loop in `server.py`, where each frame represents a discrete advancement of game state, allowing the system to maintain consistency even when individual updates are missed. This stands in stark contrast to TCP, which would delay all subsequent updates until a lost packet is retransmitted -- creating noticeable freezes in the fast-paced gameplay environment where immediate, albeit occasionally imperfect, information is far preferable to delayed perfect information.

However, we still need some methods in place to ensure reliability of the communication protocol, for example when a player disconnects. Instead of TCP's one-size-fits-all reliability approach, we use UDP since it allows us to implement reliability mechanisms particularly for our project that address the messaging reliability needs, hopefully without compromising real-time performance. We implemented the following custom reliability mechanisms:

1. **Heartbeat System**: 
   The `Pulse` message type in `protocol.py` functions as a lightweight heartbeat. Clients automatically send pulse messages every 2 seconds to indicate their active status, while the server maintains a `last_pulse_time` for each connected player. THe server's `_check_player_timeouts` method detects disconnections when no messages are received for `PLAYER_TIMEOUT` for 5 seconds. This system achieves connection state monitoring.

2. **Input Sequencing**:
   The client assigns incrementing sequence numbers to each `Input` message (in `client.py`). The server can detect out-of-order packets by examining these sequence numbers. This allows handling of network jitter where packets arrive in a different order than sent. The server processes each input as it arrives, maintaining game flow.

3. **Client-Side Prediction**:
   The players see immediate feedback from their inputs through a prediction system in `draw()` method of `Gui` class. When a player presses a movement key, the client immediately moves their paddle locally, so while the client sends the input to the server it doesn't wait for confirmation. When server state updates arrive, any discrepancy between predicted and actual positions is reconciled. This creates responsive gameplay despite network latency by allowing local rendering ahead of server confirmation

4. **Authoritative Server Model**:
   The server in the `PongServer` class maintains the definitive game state. All physics calculations are performed server-side, and with regular state broadcasts (via `broadcast_state` method) we ensure that clients eventually converge to the correct state. This prevents cheating and ensures fair gameplay while accommodating packet loss.

5. **Automatic Reconnection**:
   Client stores authentication credentials to attempt automatic reconnection. When receiving a "authentication required" message, the client automatically re-authenticates without input from the user being needed. This maintains gameplay sessions despite temporary network interruptions.

6. **Message Validation**:
   All received messages are validated in the `decode()` function within `protocol.py`. Invalid or malformed packets are safely discarded with error logging. Protocol version checking ensures compatibility between client and server

# Until here I have worked through it so far - going to continue soon.


7. **Compact Message Design**:
   - Messages are designed to be small to avoid UDP fragmentation issues
   - JSON serialization ensures human-readable protocol while maintaining reasonable size
   - This reduces the chance of packet loss due to size constraints

8. **Timeout Detection**:
   - Both client and server implement timeout detection
   - Client's `_check_server_timeout` method detects when server becomes unresponsive
   - Server's `_check_player_timeouts` identifies disconnected clients

9. **Game Loop with Fixed Timestep**:
   - Server implements a tick-based game simulation with fixed time steps
   - This creates deterministic behavior regardless of packet arrival timing
   - Consistent game state updates allow clients to easily reconcile any discrepancies

These reliability mechanisms work together to create a system that maintains the low-latency benefits of UDP while addressing its inherent reliability challenges. By selectively implementing reliability features tailored to our specific needs, we've achieved responsive gameplay without sacrificing competitive fairness.

### Comparison with TCP

TCP would have introduced several problems for our real-time game:

1. **Head-of-Line Blocking**: When a TCP packet is lost, all subsequent packets are held until the lost packet is retransmitted and received—even if newer data has arrived and would be more useful to the application. This can cause noticeable "stuttering" in games.

2. **Congestion Control**: TCP's congestion control algorithms can significantly reduce throughput after packet loss, which might be overly aggressive for game networking where maintaining a steady stream of updates is preferable.

3. **Connection Overhead**: The three-way handshake for establishing connections and connection state maintenance add latency that's unnecessary for fast-paced games.

### Other Considered Alternatives

1. **WebSockets**: While providing a convenient API and working over standard HTTP ports, WebSockets operate over TCP, inheriting all its limitations for real-time games.

2. **QUIC**: This modern protocol offers many of UDP's benefits with built-in reliability mechanisms, but at the time of development, it lacked widespread library support and would have added implementation complexity.

3. **Custom Raw Sockets**: These would have offered maximum control but would introduce cross-platform compatibility issues and potential security concerns.

### Implementation Challenges with UDP

Choosing UDP required us to address several challenges:

1. **Implementing Reliability**: We built our own message types (Hello, Pulse, Input, State) to ensure critical information is properly processed.

2. **Connection State Management**: Without TCP's built-in connection management, we implemented a timeout system where clients send regular heartbeats (Pulse messages) to indicate they're still connected.

3. **Packet Size Limitations**: UDP packets might be dropped if they exceed the network's MTU (Maximum Transmission Unit). We designed our protocol with compact messages to avoid fragmentation.

4. **NAT Traversal**: UDP can face challenges with NAT traversal in home networks. Our server-based architecture avoids this problem by having clients initiate all connections.

Overall, the benefits of UDP's low latency and lightweight nature outweighed the additional complexity required to implement custom reliability mechanisms, making it the ideal choice for our real-time Pong game.

## System Components and Implementation

### 1. Network Protocol (protocol.py)
**Challenge:** Designing a reliable communication protocol over unreliable UDP

**Implementation:**
- Created a JSON-based message protocol with a version system for backward compatibility
- Defined various message types (Hello, Pulse, Welcome, Input, State, etc.) using Python dataclasses
- Implemented message encoding/decoding with error handling for malformed packets
- Added heartbeat (Pulse) messages to maintain connection state and detect disconnections

### 2. Server Architecture (server.py)
**Challenge:** Handling multiple concurrent games and clients efficiently

**Implementation:**
- Used a multi-process architecture with a central lobby manager process
- Implemented a lobby system that creates separate game instances for pairs of players
- Designed a timeout system to detect and handle disconnected players
- Created a port allocation system for dynamically assigning game lobbies to different ports

### 3. Game Physics Simulation
**Challenge:** Creating a deterministic physics model that works over a network

**Implementation:**
- Developed a simple but effective physics engine for ball movement and collisions
- Used a fixed timestep simulation to ensure consistent behavior
- Added slight randomization to ball velocity after paddle collisions for gameplay variety
- Implemented authoritative server-side physics with client-side prediction for responsive UI

### 4. User Authentication System
**Challenge:** Securely authenticating users and maintaining persistence

**Implementation:**
- Created a SQLite database to store user credentials and game statistics
- Used password hashing for secure authentication
- Implemented session management to maintain authenticated state during gameplay
- Added statistics tracking for wins, losses, and total games played

### 5. Client Implementation (client.py)
**Challenge:** Creating a responsive UI that handles network latency

**Implementation:**
- Used Pygame for rendering and input handling
- Implemented client-side prediction to hide network latency
- Created input buffering to smooth out player control
- Added timeout detection to handle server disconnections
- Designed UI components for login, gameplay, and displaying player information

### 6. Lobby and Matchmaking System
**Challenge:** Pairing players together efficiently and managing game lifecycle

**Implementation:**
- Created a matchmaking queue to pair waiting players
- Implemented a lobby status system (WAITING, ACTIVE, COMPLETED)
- Designed a process monitoring system to clean up completed games
- Added redirect functionality to move players from the main server to game lobbies

## Technical Challenges and Solutions

### Network Reliability
Despite using UDP, which doesn't guarantee packet delivery, we implemented:
- Regular heartbeat messages to detect disconnections
- Input sequence numbers to handle packet loss and out-of-order delivery
- Server-side authority with client prediction for smooth gameplay

### Scalability
The server architecture was designed for scalability:
- Separate processes for each game to distribute CPU load
- Dynamic port allocation for game instances
- Resource cleanup for completed games to prevent memory leaks

### Security
Security measures implemented:
- Password hashing using standard cryptographic functions
- Input validation to prevent malformed packets
- Timeouts to prevent resource exhaustion

## Future Improvements
- Add spectator mode for watching ongoing games
- Implement NAT traversal techniques for better connectivity
- Add tournament functionality
- Enhance game physics with more realistic paddle physics and spin
- Improve UI with animations and sound effects
