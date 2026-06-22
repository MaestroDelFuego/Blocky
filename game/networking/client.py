"""File: client.py

Purpose:
    Client-side networking for multiplayer connection.

Responsibilities:
    * Maintain persistent connection to multiplayer server.
    * Send player state updates at regular intervals.
    * Receive and queue server events (other players, block changes).
    * Handle reconnection logic.

Dependencies:
    * socket for TCP communication.
    * threading for background connection handling.
    * queue for thread-safe message passing.
    * networking.protocol for message types.

Systems that depend on it:
    * GameManager creates NetworkClient on multiplayer startup.
    * PlayerController sends state updates to NetworkClient.
    * RenderManager receives remote player data from NetworkClient.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from queue import Queue
from typing import Any, Callable

from networking.protocol import (
    MessageType, LoginMessage, PlayerUpdateMessage, LoginSuccessMessage,
    PlayerJoinMessage, PlayerLeaveMessage, BlockChangeMessage, Vector3
)


class NetworkClient:
    """Client-side connection to multiplayer server."""
    
    def __init__(self, server_host: str = "localhost", server_port: int = 9999):
        """Initialize network client.
        
        Args:
            server_host: Server address (default: localhost).
            server_port: Server port (default: 9999).
        """
        self.server_host = server_host
        self.server_port = server_port
        self.socket: socket.socket | None = None
        self.player_id: str | None = None
        self.username: str | None = None
        self.connected = False
        self.is_running = False
        self.thread: threading.Thread | None = None
        
        # Message queues for thread-safe communication
        self.incoming_queue: Queue[dict[str, Any]] = Queue()
        self.outgoing_queue: Queue[str] = Queue()
        
        # Remote player state cache: {player_id: {username, position, rotation, animation}}
        self.remote_players: dict[str, dict[str, Any]] = {}
        
        # Callbacks
        self.on_login_success: Callable[[str, Vector3], None] | None = None
        self.on_player_join: Callable[[str, str, Vector3], None] | None = None
        self.on_player_leave: Callable[[str], None] | None = None
        self.on_player_update: Callable[[str, Vector3, tuple, str], None] | None = None
        self.on_block_change: Callable[[tuple, int, int], None] | None = None
        
    def connect(self, username: str) -> bool:
        """Attempt to connect to server and login.
        
        Args:
            username: Player name for login.
            
        Returns:
            True if connection started, False if failed.
        """
        self.username = username
        self.is_running = True
        
        # Start background connection thread
        self.thread = threading.Thread(target=self._connection_loop, daemon=True)
        self.thread.start()
        
        return True
    
    def _connection_loop(self) -> None:
        """Background thread: maintain connection and handle messages."""
        max_reconnect_delay = 30.0
        reconnect_delay = 1.0
        
        while self.is_running:
            try:
                if not self.connected:
                    self._connect_to_server()
                    if self.connected:
                        self._login()
                        reconnect_delay = 1.0
                
                # Process outgoing queue
                while not self.outgoing_queue.empty():
                    try:
                        message = self.outgoing_queue.get_nowait()
                        self.socket.sendall((message + "\n").encode("utf-8"))
                    except Exception as e:
                        print(f"Error sending message: {e}")
                        self.connected = False
                
                # Receive messages (with timeout so we can check outgoing queue)
                if self.connected:
                    self.socket.settimeout(0.5)
                    try:
                        data = self.socket.recv(4096).decode("utf-8")
                        if not data:
                            self.connected = False
                            continue
                        
                        # Handle potentially multiple messages in one recv
                        for line in data.strip().split("\n"):
                            if line:
                                try:
                                    message = json.loads(line)
                                    self.incoming_queue.put(message)
                                except json.JSONDecodeError:
                                    print(f"Invalid JSON received: {line}")
                    except socket.timeout:
                        pass  # Expected, just check outgoing queue
                    except Exception as e:
                        print(f"Connection error: {e}")
                        self.connected = False
            
            except Exception as e:
                print(f"Connection loop error: {e}")
                self.connected = False
                if self.is_running:
                    time.sleep(min(reconnect_delay, max_reconnect_delay))
                    reconnect_delay *= 2
    
    def _connect_to_server(self) -> None:
        """Establish TCP connection to server."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.server_host, self.server_port))
            self.connected = True
            print(f"Connected to server at {self.server_host}:{self.server_port}")
        except Exception as e:
            print(f"Failed to connect to server: {e}")
            self.connected = False
    
    def _login(self) -> None:
        """Send login message to server."""
        login_msg = LoginMessage(self.username or "Player")
        self.outgoing_queue.put(login_msg.to_json())
    
    def send_player_update(self, position: tuple, rotation: tuple, animation: str = "idle") -> None:
        """Send current player state to server.
        
        Args:
            position: (x, y, z) world position.
            rotation: (pitch, yaw) in radians.
            animation: Current animation state (idle/walking/jumping/falling).
        """
        if not self.connected or not self.player_id:
            return
        
        msg = PlayerUpdateMessage(
            self.player_id,
            Vector3(float(position[0]), float(position[1]), float(position[2])),
            rotation,
            animation_state=animation
        )
        self.outgoing_queue.put(msg.to_json())
    
    def send_block_change(self, position: tuple, old_block: int, new_block: int) -> None:
        """Notify server of block change.
        
        Args:
            position: (x, y, z) block position.
            old_block: Previous block ID.
            new_block: New block ID.
        """
        if not self.connected or not self.player_id:
            return
        
        msg = BlockChangeMessage(position, old_block, new_block, self.player_id)
        self.outgoing_queue.put(msg.to_json())
    
    def process_messages(self) -> None:
        """Process all pending messages from server.
        
        Should be called from main game loop to trigger callbacks.
        """
        while not self.incoming_queue.empty():
            try:
                message = self.incoming_queue.get_nowait()
                self._handle_message(message)
            except Exception as e:
                print(f"Error processing message: {e}")
    
    def _handle_message(self, message: dict[str, Any]) -> None:
        """Handle incoming message from server."""
        msg_type = message.get("type")
        
        if msg_type == MessageType.LOGIN_SUCCESS:
            self.player_id = message["player_id"]
            spawn_pos = Vector3.from_dict(message["spawn_pos"])
            if self.on_login_success:
                self.on_login_success(self.player_id, spawn_pos)
        
        elif msg_type == MessageType.PLAYER_JOIN:
            player_id = message["player_id"]
            username = message["username"]
            pos = Vector3.from_dict(message["position"])
            self.remote_players[player_id] = {
                "username": username,
                "position": pos,
                "rotation": (0.0, 0.0),
                "animation": "idle"
            }
            if self.on_player_join:
                self.on_player_join(player_id, username, pos)
        
        elif msg_type == MessageType.PLAYER_LEAVE:
            player_id = message["player_id"]
            if player_id in self.remote_players:
                del self.remote_players[player_id]
            if self.on_player_leave:
                self.on_player_leave(player_id)
        
        elif msg_type == MessageType.PLAYER_UPDATE:
            player_id = message["player_id"]
            pos = Vector3.from_dict(message["position"])
            rotation = tuple(message["rotation"])
            animation = message.get("animation_state", "idle")
            
            if player_id in self.remote_players:
                self.remote_players[player_id]["position"] = pos
                self.remote_players[player_id]["rotation"] = rotation
                self.remote_players[player_id]["animation"] = animation
            
            if self.on_player_update:
                self.on_player_update(player_id, pos, rotation, animation)
        
        elif msg_type == MessageType.PLAYER_LIST:
            # Receive list of existing players when joining
            players = message.get("players", [])
            for player_info in players:
                player_id = player_info["player_id"]
                username = player_info["username"]
                pos = Vector3.from_dict(player_info["position"])
                self.remote_players[player_id] = {
                    "username": username,
                    "position": pos,
                    "rotation": tuple(player_info.get("rotation", [0.0, 0.0])),
                    "animation": player_info.get("animation", "idle")
                }
                # Trigger join callback for each player in the list
                if self.on_player_join:
                    self.on_player_join(player_id, username, pos)
        
        elif msg_type == MessageType.BLOCK_CHANGE:
            position = tuple(message["position"])
            old_block = message["old_block"]
            new_block = message["new_block"]
            if self.on_block_change:
                self.on_block_change(position, old_block, new_block)
    
    def disconnect(self) -> None:
        """Disconnect from server."""
        self.is_running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        self.connected = False
        if self.thread:
            self.thread.join(timeout=2.0)
        print("Disconnected from server")
