import unittest
import socket
import time
import json
import threading
from unittest.mock import MagicMock, patch
import tempfile
import os
from pathlib import Path
import multiprocessing

# Import modules to test
from protocol import (
    MessageType, Hello, Welcome, Input, State, Login, LoginResult,
    Pulse, GameOver, Denied, decode
)
from server import (
    ServerDB, GameState, PongServer, LobbyManager, PlayerSlot,
    PLAYER_TIMEOUT, LobbyStatus, LobbyInfo
)

class TestProtocol(unittest.TestCase):
    """Test protocol message encoding and decoding"""
    
    def test_hello_encode_decode(self):
        """Test Hello message encoding and decoding"""
        username = "testuser"
        hello = Hello(username=username)
        encoded = hello.encode()
        decoded = decode(encoded)
        
        self.assertEqual(decoded.type, MessageType.HELLO)
        self.assertEqual(decoded.username, username)
    
    def test_welcome_encode_decode(self):
        """Test Welcome message encoding and decoding"""
        player_id = 1
        welcome = Welcome(player_id=player_id)
        encoded = welcome.encode()
        decoded = decode(encoded)
        
        self.assertEqual(decoded.type, MessageType.WELCOME)
        self.assertEqual(decoded.player_id, player_id)
    
    def test_login_encode_decode(self):
        """Test Login message encoding and decoding"""
        username = "testuser"
        password_hash = "abcdef1234567890"
        login = Login(username=username, password_hash=password_hash)
        encoded = login.encode()
        decoded = decode(encoded)
        
        self.assertEqual(decoded.type, MessageType.LOGIN)
        self.assertEqual(decoded.username, username)
        self.assertEqual(decoded.password_hash, password_hash)
    
    def test_state_encode_decode(self):
        """Test State message encoding and decoding"""
        state = State(
            tick=10,
            ball_x=320,
            ball_y=240,
            paddle0_y=100,
            paddle1_y=200,
            score0=2,
            score1=1,
            player0_username="player1",
            player1_username="player2"
        )
        encoded = state.encode()
        decoded = decode(encoded)
        
        self.assertEqual(decoded.type, MessageType.STATE)
        self.assertEqual(decoded.tick, 10)
        self.assertEqual(decoded.ball_x, 320)
        self.assertEqual(decoded.ball_y, 240)
        self.assertEqual(decoded.paddle0_y, 100)
        self.assertEqual(decoded.paddle1_y, 200)
        self.assertEqual(decoded.score0, 2)
        self.assertEqual(decoded.score1, 1)
        self.assertEqual(decoded.player0_username, "player1")
        self.assertEqual(decoded.player1_username, "player2")

class TestServerDB(unittest.TestCase):
    """Test database functionality"""
    
    def setUp(self):
        """Create a temporary database for testing"""
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = Path(self.temp_db.name)
        self.db = ServerDB(self.db_path)
    
    def tearDown(self):
        """Clean up temporary database after tests"""
        os.unlink(self.db_path)
    
    def test_add_user(self):
        """Test adding a new user to the database"""
        username = "newuser"
        password_hash = "hashedpw123"
        
        self.db.add_user(username, password_hash)
        
        # Verify user exists
        self.assertTrue(self.db.verify_user(username, password_hash))
    
    def test_add_duplicate_user(self):
        """Test adding a duplicate user raises ValueError"""
        username = "dupuser"
        password_hash = "hashedpw123"
        
        # First add should succeed
        self.db.add_user(username, password_hash)
        
        # Second add should fail
        with self.assertRaises(ValueError):
            self.db.add_user(username, password_hash)
    
    def test_verify_user_correct_password(self):
        """Test verifying a user with correct credentials"""
        username = "verifyuser"
        password_hash = "hashedpw123"
        
        self.db.add_user(username, password_hash)
        
        self.assertTrue(self.db.verify_user(username, password_hash))
    
    def test_verify_user_wrong_password(self):
        """Test verifying a user with incorrect credentials"""
        username = "verifyuser"
        password_hash = "hashedpw123"
        wrong_hash = "wrongpw456"
        
        self.db.add_user(username, password_hash)
        
        self.assertFalse(self.db.verify_user(username, wrong_hash))
    
    def test_verify_nonexistent_user(self):
        """Test verifying a user that doesn't exist"""
        username = "nonexistent"
        password_hash = "hashedpw123"
        
        self.assertFalse(self.db.verify_user(username, password_hash))
    
    def test_record_game_win(self):
        """Test recording a game win"""
        username = "gameuser"
        password_hash = "hashedpw123"
        
        self.db.add_user(username, password_hash)
        self.db.record_game(username, win=True)
        
        games, wins, losses = self.db.get_stats(username)
        self.assertEqual(games, 1)
        self.assertEqual(wins, 1)
        self.assertEqual(losses, 0)
    
    def test_record_game_loss(self):
        """Test recording a game loss"""
        username = "gameuser"
        password_hash = "hashedpw123"
        
        self.db.add_user(username, password_hash)
        self.db.record_game(username, win=False)
        
        games, wins, losses = self.db.get_stats(username)
        self.assertEqual(games, 1)
        self.assertEqual(wins, 0)
        self.assertEqual(losses, 1)
    
    def test_multiple_games(self):
        """Test recording multiple games"""
        username = "gameuser"
        password_hash = "hashedpw123"
        
        self.db.add_user(username, password_hash)
        self.db.record_game(username, win=True)
        self.db.record_game(username, win=False)
        self.db.record_game(username, win=True)
        
        games, wins, losses = self.db.get_stats(username)
        self.assertEqual(games, 3)
        self.assertEqual(wins, 2)
        self.assertEqual(losses, 1)

class TestGameState(unittest.TestCase):
    """Test game physics and logic"""
    
    def setUp(self):
        """Create a fresh game state for each test"""
        self.game = GameState()
    
    def test_initial_state(self):
        """Test initial game state values"""
        self.assertEqual(self.game.tick, 0)
        self.assertEqual(self.game.ball_x, self.game.W / 2)
        self.assertEqual(self.game.ball_y, self.game.H / 2)
        self.assertEqual(self.game.scores, [0, 0])
        self.assertEqual(len(self.game.paddles), 2)
    
    def test_ball_movement(self):
        """Test ball movement with step"""
        initial_x = self.game.ball_x
        initial_y = self.game.ball_y
        
        # Step forward 0.1 seconds
        self.game.step(0.1)
        
        # Ball should have moved
        self.assertNotEqual(self.game.ball_x, initial_x)
        self.assertNotEqual(self.game.ball_y, initial_y)
    
    def test_ball_top_bounce(self):
        """Test ball bouncing off top edge"""
        # Position ball at top edge
        self.game.ball_x = self.game.W / 2
        self.game.ball_y = 1
        self.game.ball_vy = -100  # Moving upward
        
        # Step forward
        self.game.step(0.1)
        
        # Ball should have bounced (velocity inverted)
        self.assertTrue(self.game.ball_vy > 0)
    
    def test_ball_bottom_bounce(self):
        """Test ball bouncing off bottom edge"""
        # Position ball at bottom edge
        self.game.ball_x = self.game.W / 2
        self.game.ball_y = self.game.H - self.game.BALL_SZ - 1
        self.game.ball_vy = 100  # Moving downward
        
        # Step forward
        self.game.step(0.1)
        
        # Ball should have bounced (velocity inverted)
        self.assertTrue(self.game.ball_vy < 0)
    
    def test_left_paddle_collision(self):
        """Test ball collision with left paddle"""
        # Position ball and paddle for collision
        self.game.paddles[0] = 100
        self.game.ball_x = self.game.PADDLE_W + 2
        self.game.ball_y = 120
        self.game.ball_vx = -100  # Moving left
        
        # Step forward
        self.game.step(0.1)
        
        # Ball should have bounced (velocity inverted)
        self.assertTrue(self.game.ball_vx > 0)
    
    def test_right_paddle_collision(self):
        """Test ball collision with right paddle"""
        # Position ball and paddle for collision
        self.game.paddles[1] = 100
        self.game.ball_x = self.game.W - self.game.PADDLE_W - self.game.BALL_SZ - 2
        self.game.ball_y = 120
        self.game.ball_vx = 100  # Moving right
        
        # Step forward
        self.game.step(0.1)
        
        # Ball should have bounced (velocity inverted)
        self.assertTrue(self.game.ball_vx < 0)
    
    def test_left_score(self):
        """Test scoring when ball goes left"""
        # Position ball just past left edge
        self.game.ball_x = 1
        self.game.ball_vx = -100  # Moving left
        self.game.ball_y = self.game.paddles[0] - 1
        self.game.ball_vy = 0
        initial_score1 = self.game.scores[1]
        
        # Step forward
        self.game.step(0.1)
                
        # Right player should score
        self.assertEqual(self.game.scores[1], initial_score1 + 1)
        # Ball should reset
        self.assertEqual(self.game.ball_x, self.game.W / 2)
        self.assertEqual(self.game.ball_y, self.game.H / 2)
    
    def test_right_score(self):
        """Test scoring when ball goes right"""
        # Position ball just past right edge
        self.game.ball_x = self.game.W + 1  # Changed from self.game.W - 1
        self.game.ball_vx = 100  # Moving right
        self.game.ball_y = self.game.paddles[0] - 1
        self.game.ball_vy = 0
        initial_score0 = self.game.scores[0]
        
        # Step forward
        self.game.step(0.1)
        
        # Left player should score
        self.assertEqual(self.game.scores[0], initial_score0 + 1)
        # Ball should reset
        self.assertEqual(self.game.ball_x, self.game.W / 2)
        self.assertEqual(self.game.ball_y, self.game.H / 2)
    
    def test_reset_ball(self):
        """Test reset_ball function"""
        # Move ball away from center
        self.game.ball_x = 100
        self.game.ball_y = 100
        
        # Reset ball moving right
        self.game.reset_ball(direction=1)
        
        # Check position and direction
        self.assertEqual(self.game.ball_x, self.game.W / 2)
        self.assertEqual(self.game.ball_y, self.game.H / 2)
        self.assertTrue(self.game.ball_vx > 0)
        
        # Reset ball moving left
        self.game.reset_ball(direction=-1)
        
        # Check direction
        self.assertTrue(self.game.ball_vx < 0)

class TestPongServer(unittest.TestCase):
    """Test PongServer functionality"""
    
    def setUp(self):
        """Set up mock server for tests"""
        # Mock socket and pipe connection
        self.mock_socket = MagicMock()
        self.mock_pipe = MagicMock()
        
        # Create a temporary database
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = Path(self.temp_db.name)
        
        # Patch socket creation
        with patch('socket.socket', return_value=self.mock_socket):
            self.server = PongServer(
                host='localhost',
                port=12345,
                db_path=self.db_path,
                pipe_conn=self.mock_pipe,
                lobby_id=1
            )
        
        # Add test users to DB
        self.server.db.add_user("testuser1", "hash1")
        self.server.db.add_user("testuser2", "hash2")
        
        # Mock authenticated users
        self.server.authenticated_users = {
            ('127.0.0.1', 5000): "testuser1",
            ('127.0.0.1', 5001): "testuser2"
        }
    
    def tearDown(self):
        """Clean up after tests"""
        os.unlink(self.db_path)
    
    def test_send_method(self):
        """Test send method"""
        addr = ('127.0.0.1', 5000)
        msg = Hello(username="testuser")
        
        self.server.send(msg, addr)
        
        self.mock_socket.sendto.assert_called_once()
        args, _ = self.mock_socket.sendto.call_args
        self.assertEqual(args[1], addr)
    
    def test_handle_hello_new_player(self):
        """Test handling a Hello message for a new player"""
        addr = ('127.0.0.1', 5000)
        msg = Hello(username="testuser1")
        
        self.server._handle_hello(msg, addr)
        
        # Should assign player to a slot
        self.assertIsNotNone(self.server.slots[0])
        self.assertEqual(self.server.slots[0].username, "testuser1")
        self.assertEqual(self.server.slots[0].addr, addr)
        
        # Should send Welcome message
        self.mock_socket.sendto.assert_called_once()
        args, _ = self.mock_socket.sendto.call_args
        decoded_msg = decode(args[0])
        self.assertEqual(decoded_msg.type, MessageType.WELCOME)
        self.assertEqual(decoded_msg.player_id, 0)
        
        # Should notify parent process
        self.mock_pipe.send.assert_called_once()
    
    def test_handle_hello_second_player_starts_game(self):
        """Test handling a Hello message for second player starts the game"""
        # Add first player
        addr1 = ('127.0.0.1', 5000)
        self.server.slots[0] = PlayerSlot(
            id=0, 
            addr=addr1, 
            username="testuser1", 
            last_pulse_time=time.perf_counter()
        )
        
        # Add second player
        addr2 = ('127.0.0.1', 5001)
        msg = Hello(username="testuser2")
        
        self.server._handle_hello(msg, addr2)
        
        # Should assign second player
        self.assertIsNotNone(self.server.slots[1])
        self.assertEqual(self.server.slots[1].username, "testuser2")
        
        # Game should be running
        self.assertTrue(self.server.game_running)
        
        # Should notify parent process
        self.mock_pipe.send.assert_called()
    
    def test_handle_hello_unauthenticated(self):
        """Test handling a Hello message from unauthenticated user"""
        addr = ('10.0.0.1', 6000)  # Not in authenticated_users
        msg = Hello(username="unknown")
        
        self.server._handle_hello(msg, addr)
        
        # Should send Denied message
        self.mock_socket.sendto.assert_called_once()
        args, _ = self.mock_socket.sendto.call_args
        decoded_msg = decode(args[0])
        self.assertEqual(decoded_msg.type, MessageType.DENIED)
    
    def test_handle_input(self):
        """Test handling an Input message"""
        # Set up player in slot
        addr = ('127.0.0.1', 5000)
        self.server.slots[0] = PlayerSlot(
            id=0, 
            addr=addr, 
            username="testuser1", 
            last_pulse_time=time.perf_counter()
        )
        
        # Send input
        msg = Input(seq=1, paddle_y=150)
        
        self.server._handle_input(msg, addr)
        
        # Paddle position should be updated
        self.assertEqual(self.server.slots[0].paddle_y, 150)
        self.assertEqual(self.server.game.paddles[0], 150)
    
    def test_handle_input_unknown_player(self):
        """Test handling an Input message from unknown player"""
        addr = ('10.0.0.1', 6000)  # Not in slots
        msg = Input(seq=1, paddle_y=150)
        
        self.server._handle_input(msg, addr)
        
        # Should ignore message (paddles unchanged)
        self.assertNotEqual(self.server.game.paddles[0], 150)
    
    def test_check_player_timeouts(self):
        """Test checking for player timeouts"""
        # Add player with old last_pulse_time
        addr = ('127.0.0.1', 5000)
        old_time = time.perf_counter() - PLAYER_TIMEOUT * 3  # Well beyond timeout
        self.server.slots[0] = PlayerSlot(
            id=0, 
            addr=addr, 
            username="testuser1", 
            last_pulse_time=old_time
        )
        
        # Check for timeouts
        self.server._check_player_timeouts(time.perf_counter())
        
        # Player should be disconnected
        self.assertIsNone(self.server.slots[0])
        
        # Should notify parent process
        self.mock_pipe.send.assert_called()

# More tests for LobbyManager, integration tests, etc. would follow

# --------------------- LobbyManager Tests ---------------------
class TestLobbyManager(unittest.TestCase):
    """Test the LobbyManager functionality"""
    
    def setUp(self):
        """Set up mock manager for tests"""
        # Mock socket
        self.mock_socket = MagicMock()
        
        # Create a temporary database
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = Path(self.temp_db.name)
        
        # Patch socket creation
        with patch('socket.socket', return_value=self.mock_socket):
            self.manager = LobbyManager(
                host='localhost',
                port=9999,
                db_path=self.db_path
            )
        
        # Add test users to DB
        self.manager.db.add_user("testuser1", "hash1")
        self.manager.db.add_user("testuser2", "hash2")
    
    def tearDown(self):
        """Clean up after tests"""
        os.unlink(self.db_path)
        
        # Clean up any test lobbies
        for lobby_id in list(self.manager.lobbies.keys()):
            self.manager._cleanup_lobby(lobby_id)
    
    def test_match_players(self):
        """Test matching players creates a lobby"""
        # Mock the _create_new_lobby method to avoid actual process creation
        with patch.object(self.manager, '_create_new_lobby', return_value=1) as mock_create:
            # Add first player to waiting list
            self.manager.waiting_players["testuser1"] = ("testuser1", ('127.0.0.1', 5000))
            
            # Create a dummy lobby so the code doesn't fail when accessing it
            from server import LobbyInfo
            mock_process = MagicMock()
            mock_pipe = MagicMock()
            self.manager.lobbies[1] = LobbyInfo(
                lobby_id=1,
                port=10001,
                process=mock_process,
                players=["testuser1"],
                creation_time=time.perf_counter(),
                status=LobbyStatus.WAITING,
                pipe_conn=mock_pipe
            )
            
            # Try to match second player
            self.manager._match_players("testuser2", ('127.0.0.1', 5001))
            
            # Should call _create_new_lobby
            mock_create.assert_called_once()
            
            # Should remove player from waiting list
            self.assertNotIn("testuser1", self.manager.waiting_players)
    
    def test_find_available_port(self):
        """Test finding an available port"""
        # Mock socket binding to simulate port availability
        with patch('socket.socket') as mock_socket_class:
            mock_socket_instance = MagicMock()
            mock_socket_class.return_value = mock_socket_instance
            
            # First call binds successfully
            port = self.manager._find_available_port()
            
            # Port should be in range
            self.assertTrue(port >= 10000 and port <= 20000)
            
            # Socket methods should be called
            mock_socket_instance.bind.assert_called_once()
            mock_socket_instance.close.assert_called_once()
    
    def test_cleanup_lobby(self):
        """Test cleaning up a lobby"""
        # Create a mock lobby
        mock_process = MagicMock()
        mock_pipe = MagicMock()
        
        # Create LobbyInfo directly from imported class
        from server import LobbyInfo
        
        # Add a test lobby
        self.manager.lobbies[1] = LobbyInfo(
            lobby_id=1,
            port=10001,
            process=mock_process,
            players=["testuser1", "testuser2"],
            creation_time=time.perf_counter(),
            status=LobbyStatus.COMPLETED,
            pipe_conn=mock_pipe
        )
        
        # Add users to authenticated_users
        self.manager.authenticated_users[('127.0.0.1', 5000)] = "testuser1"
        self.manager.authenticated_users[('127.0.0.1', 5001)] = "testuser2"
        
        # Call cleanup
        self.manager._cleanup_lobby(1)
        
        # Verify lobby was removed
        self.assertNotIn(1, self.manager.lobbies)
        
        # Verify shutdown message was sent
        mock_pipe.send.assert_called_once()
        
        # Verify process was terminated or joined
        mock_process.join.assert_called_once()

# --------------------- Integration Tests ---------------------
class TestIntegration(unittest.TestCase):
    """Integration tests between components"""
    
    def setUp(self):
        """Set up for integration tests"""
        # Create temp DB
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = Path(self.temp_db.name)
        
        # Create server DB with test users
        self.db = ServerDB(self.db_path)
        self.db.add_user("testuser1", "hash1")
        self.db.add_user("testuser2", "hash2")
        
        # Set up mocks
        self.server_socket = MagicMock()
        self.pipe_parent, self.pipe_child = multiprocessing.Pipe()
    
    def tearDown(self):
        """Clean up after tests"""
        os.unlink(self.db_path)
        self.pipe_parent.close()
        self.pipe_child.close()
    
    def test_server_db_integration(self):
        """Test integration between Server and DB"""
        with patch('socket.socket', return_value=self.server_socket):
            server = PongServer(
                host='localhost',
                port=12345,
                db_path=self.db_path,
                pipe_conn=self.pipe_child,
                lobby_id=1
            )
            
            # Patch the update_authenticated_users method to prevent hanging
            with patch.object(server, 'update_authenticated_users'):
                # Test login with valid user
                login_msg = Login(username="testuser1", password_hash="hash1")
                server._handle_login(login_msg, ('127.0.0.1', 5000))
                
                # Verify response
                self.server_socket.sendto.assert_called_once()
                args, _ = self.server_socket.sendto.call_args
                decoded_msg = decode(args[0])
                self.assertEqual(decoded_msg.type, MessageType.LOGIN_RESULT)
                self.assertTrue(decoded_msg.success)
    
    def test_server_pipe_communication(self):
        """Test communication between server and parent process"""
        with patch('socket.socket', return_value=self.server_socket):
            server = PongServer(
                host='localhost',
                port=12345,
                db_path=self.db_path,
                pipe_conn=self.pipe_child,
                lobby_id=1
            )
            
            # Create player slot
            server.slots[0] = PlayerSlot(
                id=0,
                addr=('127.0.0.1', 5000),
                username="testuser1",
                last_pulse_time=time.perf_counter()
            )
            
            # Test player disconnect sends message to parent
            server._handle_player_disconnect(0, server.slots[0])
            
            # Check if message was received on parent pipe
            self.assertTrue(self.pipe_parent.poll(1.0))
            msg = self.pipe_parent.recv()
            self.assertEqual(msg.get('type'), 'player_disconnected')
            self.assertEqual(msg.get('username'), 'testuser1')
    
    def test_game_state_server_integration(self):
        """Test integration between GameState and PongServer"""
        with patch('socket.socket', return_value=self.server_socket):
            server = PongServer(
                host='localhost',
                port=12345,
                db_path=self.db_path,
                pipe_conn=self.pipe_child,
                lobby_id=1
            )
            
            # Add players to slots
            server.slots[0] = PlayerSlot(
                id=0,
                addr=('127.0.0.1', 5000),
                username="testuser1",
                last_pulse_time=time.perf_counter()
            )
            server.slots[1] = PlayerSlot(
                id=1,
                addr=('127.0.0.1', 5001),
                username="testuser2",
                last_pulse_time=time.perf_counter()
            )
            
            # Start game
            server.game_running = True
            
            # Update game state
            now = time.perf_counter()
            next_tick = now
            server._update_game_state(now, next_tick, 1/60)
            
            # Should broadcast state
            self.assertEqual(self.server_socket.sendto.call_count, 2)  # Once for each player

# --------------------- Client-Server Communication Tests ---------------------
class TestClientServerCommunication(unittest.TestCase):
    """Test client-server communication protocol"""
    
    def setUp(self):
        """Set up for client-server tests"""
        # Create temp DB
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = Path(self.temp_db.name)
        
        # Set up server with mock socket
        self.server_socket = MagicMock()
        with patch('socket.socket', return_value=self.server_socket):
            self.server = PongServer(
                host='localhost',
                port=12345,
                db_path=self.db_path
            )
        
        # Add test user
        self.server.db.add_user("testuser", "hash123")
        
        # Set up client with mock socket
        self.client_socket = MagicMock()
        # We would typically set up a client here
    
    def tearDown(self):
        """Clean up after tests"""
        os.unlink(self.db_path)
    
    def test_login_protocol(self):
        """Test login protocol exchange"""
        # Simulate client sending login
        addr = ('127.0.0.1', 5000)
        login_msg = Login(username="testuser", password_hash="hash123")
        
        # Handle the login
        self.server._handle_login(login_msg, addr)
        
        # Server should send LoginResult
        self.server_socket.sendto.assert_called_once()
        args, _ = self.server_socket.sendto.call_args
        decoded_msg = decode(args[0])
        self.assertEqual(decoded_msg.type, MessageType.LOGIN_RESULT)
        self.assertTrue(decoded_msg.success)
    
    def test_hello_welcome_protocol(self):
        """Test Hello-Welcome protocol exchange"""
        # Add user to authenticated list
        addr = ('127.0.0.1', 5000)
        self.server.authenticated_users[addr] = "testuser"
        
        # Simulate client sending Hello
        hello_msg = Hello(username="testuser")
        
        # Handle the Hello
        self.server._handle_hello(hello_msg, addr)
        
        # Server should send Welcome
        self.server_socket.sendto.assert_called_once()
        args, _ = self.server_socket.sendto.call_args
        decoded_msg = decode(args[0])
        self.assertEqual(decoded_msg.type, MessageType.WELCOME)
        
        # Player should be assigned a slot
        self.assertIsNotNone(self.server.slots[decoded_msg.player_id])
        self.assertEqual(self.server.slots[decoded_msg.player_id].username, "testuser")
    
    def test_input_state_protocol(self):
        """Test Input-State protocol exchange"""
        # Add user to slots
        addr = ('127.0.0.1', 5000)
        self.server.slots[0] = PlayerSlot(
            id=0,
            addr=addr,
            username="testuser",
            last_pulse_time=time.perf_counter()
        )
        
        # Enable game
        self.server.game_running = True
        
        # Simulate input message
        input_msg = Input(seq=1, paddle_y=150)
        
        # Handle input
        self.server._handle_input(input_msg, addr)
        
        # Paddle position should be updated
        self.assertEqual(self.server.game.paddles[0], 150)
        
        # Broadcast state (manually trigger since we're not in game loop)
        self.server.broadcast_state()
        
        # State should be sent to the player
        self.server_socket.sendto.assert_called_once()
        args, _ = self.server_socket.sendto.call_args
        decoded_msg = decode(args[0])
        self.assertEqual(decoded_msg.type, MessageType.STATE)
        self.assertEqual(decoded_msg.paddle0_y, 150)

# --------------------- Edge Case Tests ---------------------
class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""
    
    def setUp(self):
        """Set up for edge case tests"""
        # Create temp DB
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = Path(self.temp_db.name)
        
        # Create mocks
        self.socket_mock = MagicMock()
        self.pipe_mock = MagicMock()
    
    def tearDown(self):
        """Clean up after tests"""
        os.unlink(self.db_path)
    
    def test_handle_player_timeout(self):
        """Test handling player timeouts"""
        with patch('socket.socket', return_value=self.socket_mock):
            server = PongServer(
                host='localhost',
                port=12345,
                db_path=self.db_path,
                pipe_conn=self.pipe_mock
            )
            
            # Add two players with first player about to timeout
            current_time = time.perf_counter()
            server.slots[0] = PlayerSlot(
                id=0,
                addr=('127.0.0.1', 5000),
                username="timeout_user",
                last_pulse_time=current_time - PLAYER_TIMEOUT * 3  # Way past timeout
            )
            server.slots[1] = PlayerSlot(
                id=1,
                addr=('127.0.0.1', 5001),
                username="active_user",
                last_pulse_time=current_time
            )
            
            # Set game running
            server.game_running = True
            
            # Check timeouts
            server._check_player_timeouts(current_time)
            
            # First player should be removed
            self.assertIsNone(server.slots[0])
            
            # Second player should get GameOver message
            self.socket_mock.sendto.assert_called_once()
            args, _ = self.socket_mock.sendto.call_args
            decoded_msg = decode(args[0])
            self.assertEqual(decoded_msg.type, MessageType.GAME_OVER)
            self.assertEqual(decoded_msg.reason, "opponent_disconnected")
    
    def test_handle_invalid_packets(self):
        """Test handling invalid packets"""
        with patch('socket.socket', return_value=self.socket_mock):
            server = PongServer(
                host='localhost',
                port=12345,
                db_path=self.db_path
            )
            
            # Try handling malformed packet
            malformed_data = b"not valid json"
            addr = ('127.0.0.1', 5000)
            
            # Should not raise exception
            server.handle_packet(malformed_data, addr)
            
            # No messages should be sent
            self.socket_mock.sendto.assert_not_called()
    
    def test_duplicate_hello_request(self):
        """Test handling duplicate Hello requests"""
        with patch('socket.socket', return_value=self.socket_mock):
            server = PongServer(
                host='localhost',
                port=12345,
                db_path=self.db_path
            )
            
            # Add user to authenticated list
            addr = ('127.0.0.1', 5000)
            server.authenticated_users[addr] = "testuser"
            
            # Add player to slot
            server.slots[0] = PlayerSlot(
                id=0,
                addr=addr,
                username="testuser",
                last_pulse_time=time.perf_counter()
            )
            
            # Simulate Hello message from same user
            hello_msg = Hello(username="testuser")
            
            # Handle Hello
            server._handle_hello(hello_msg, addr)
            
            # Should not send another Welcome (ignore duplicate)
            self.socket_mock.sendto.assert_not_called()
            
            # Should not change slot
            self.assertEqual(server.slots[0].addr, addr)
            self.assertEqual(server.slots[0].username, "testuser")

# --------------------- Authentication Tests ---------------------
class TestAuthentication(unittest.TestCase):
    """Test authentication flow"""
    
    def setUp(self):
        """Set up for authentication tests"""
        # Create temp DB
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = Path(self.temp_db.name)
        
        # Set up server with mock socket
        self.socket_mock = MagicMock()
        with patch('socket.socket', return_value=self.socket_mock):
            self.server = PongServer(
                host='localhost',
                port=12345,
                db_path=self.db_path
            )
    
    def tearDown(self):
        """Clean up after tests"""
        os.unlink(self.db_path)
    
    def test_login_flow(self):
        """Test complete login flow"""
        # Add user to database
        self.server.db.add_user("loginuser", "correcthash")
        
        # Test with correct credentials
        addr = ('127.0.0.1', 5000)
        login_msg = Login(username="loginuser", password_hash="correcthash")
        
        # Process login
        self.server._handle_login(login_msg, addr)
        
        # Should get success response
        args, _ = self.socket_mock.sendto.call_args_list[0]
        decoded_msg = decode(args[0])
        self.assertEqual(decoded_msg.type, MessageType.LOGIN_RESULT)
        self.assertTrue(decoded_msg.success)
        
        # Reset mock for next test
        self.socket_mock.reset_mock()
        
        # Test with incorrect password
        login_msg = Login(username="loginuser", password_hash="wronghash")
        self.server._handle_login(login_msg, addr)
        
        # Should get failure response
        args, _ = self.socket_mock.sendto.call_args_list[0]
        decoded_msg = decode(args[0])
        self.assertEqual(decoded_msg.type, MessageType.LOGIN_RESULT)
        self.assertFalse(decoded_msg.success)
    
    def test_hello_without_authentication(self):
        """Test Hello without prior authentication"""
        addr = ('127.0.0.1', 5000)
        hello_msg = Hello(username="unauthuser")
        
        # Handle Hello without authentication
        self.server._handle_hello(hello_msg, addr)
        
        # Should get denied response
        self.socket_mock.sendto.assert_called_once()
        args, _ = self.socket_mock.sendto.call_args
        decoded_msg = decode(args[0])
        self.assertEqual(decoded_msg.type, MessageType.DENIED)
        self.assertEqual(decoded_msg.reason, "authentication required")
    
    def test_auto_account_creation(self):
        """Test automatic account creation for new users"""
        addr = ('127.0.0.1', 5000)
        new_username = "newuser"
        new_hash = "newhash123"
        
        # Ensure user doesn't exist
        self.assertFalse(self.server.db.verify_user(new_username, new_hash))
        
        # Login with new user
        login_msg = Login(username=new_username, password_hash=new_hash)
        self.server._handle_login(login_msg, addr)
        
        # Should get success response for new account
        args, _ = self.socket_mock.sendto.call_args
        decoded_msg = decode(args[0])
        self.assertEqual(decoded_msg.type, MessageType.LOGIN_RESULT)
        self.assertTrue(decoded_msg.success)
        
        # User should now exist
        self.assertTrue(self.server.db.verify_user(new_username, new_hash))



