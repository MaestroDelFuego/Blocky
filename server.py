#!/usr/bin/env python3
"""File: server.py

Purpose:
    Dedicated multiplayer server for voxel sandbox.

Responsibilities:
    * Accept client connections and manage player sessions.
    * Validate and broadcast player state updates.
    * Synchronize world state across all clients.
    * Persist world data.
    * Spawn players at designated spawn point.

Dependencies:
    * asyncio for concurrent connection handling (or threading).
    * socket for TCP networking.
    * json for message serialization.
    * pathlib for project structure.

Systems that depend on it:
    * Clients connect to this server for multiplayer gameplay.
    * SaveManager loads/persists world state.

Future considerations:
    * Authentication and player accounts.
    * Admin commands.
    * Persistence queue for save operations.
    * Load balancing for multiple servers.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from queue import Queue

# Add game directory to path so we can import game modules
sys.path.insert(0, str(Path(__file__).parent / "game"))

from chunks.chunk_manager import ChunkManager
from inventory.inventory_manager import InventoryManager
from saving.save_manager import SaveManager
from terrain.terrain_generator import TerrainGenerator
from world.block_registry import BlockRegistry
from world.world_manager import WorldManager
from networking.protocol import (
    MessageType, LoginSuccessMessage, PlayerJoinMessage, PlayerLeaveMessage,
    PlayerUpdateMessage, PlayerListMessage, Vector3, BlockChangeMessage
)


class ServerPlayer:
    """Represents a connected player on the server."""
    
    def __init__(self, player_id: str, username: str, connection: socket.socket, address: tuple):
        self.player_id = player_id
        self.username = username
        self.connection = connection
        self.address = address
        self.position = Vector3(0.0, 64.0, 0.0)
        self.rotation = (0.0, 0.0)
        self.animation_state = "idle"
        self.last_update = time.time()
        self.inventory = InventoryManager()
    
    def send_message(self, message: str) -> bool:
        """Send JSON message to client.
        
        Returns:
            True if successful, False if connection failed.
        """
        try:
            self.connection.sendall((message + "\n").encode("utf-8"))
            return True
        except Exception as e:
            print(f"Error sending to {self.username}: {e}")
            return False
    
    def __repr__(self) -> str:
        return f"ServerPlayer({self.player_id[:8]}, {self.username}, {self.address})"


class VoxelSandboxServer:
    """Multiplayer server for voxel sandbox."""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 9999, world_path: Path | None = None):
        """Initialize server.
        
        Args:
            host: Server bind address.
            port: Server port.
            world_path: Path to world save directory.
        """
        self.host = host
        self.port = port
        self.world_path = world_path or Path(__file__).parent.parent.parent / "saves" / "server_world"
        self.world_path.mkdir(parents=True, exist_ok=True)
        
        # Server state
        self.running = False
        self.players: dict[str, ServerPlayer] = {}
        self.players_lock = threading.Lock()
        
        # World state
        self.block_registry = BlockRegistry()
        self.save_manager = SaveManager(self.world_path.parent)
        self.terrain_generator = TerrainGenerator(1337, self.block_registry)
        self.chunk_manager = ChunkManager(self.terrain_generator, self.save_manager)
        self.world_manager = WorldManager(self.chunk_manager, self.block_registry)
        
        # Spawn point (center of world)
        self.spawn_position = Vector3(0.0, 64.0, 0.0)
        
        # Server socket
        self.server_socket: socket.socket | None = None
        self.threads: list[threading.Thread] = []
    
    def start(self) -> None:
        """Start the server."""
        self.running = True
        
        # Create server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        
        print(f"🌐 Voxel Sandbox Server started on {self.host}:{self.port}")
        print(f"📁 World save: {self.world_path}")
        
        # Start accept loop
        accept_thread = threading.Thread(target=self._accept_connections, daemon=False)
        accept_thread.start()
        self.threads.append(accept_thread)
        
        # Start heartbeat loop (sends periodic state to all clients)
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=False)
        heartbeat_thread.start()
        self.threads.append(heartbeat_thread)
        
        # Keep server running
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def _accept_connections(self) -> None:
        """Accept incoming client connections."""
        while self.running:
            try:
                client_socket, address = self.server_socket.accept()
                print(f"📍 New connection from {address}")
                
                # Handle client in background thread
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, address),
                    daemon=True
                )
                client_thread.start()
            except Exception as e:
                if self.running:
                    print(f"Error accepting connection: {e}")
    
    def _handle_client(self, client_socket: socket.socket, address: tuple) -> None:
        """Handle a single client connection."""
        player: ServerPlayer | None = None
        
        try:
            client_socket.settimeout(5.0)
            
            # Wait for login message
            data = client_socket.recv(4096).decode("utf-8")
            if not data:
                return
            
            message = json.loads(data.strip())
            if message.get("type") != MessageType.LOGIN:
                print(f"First message from {address} was not LOGIN")
                return
            
            username = message.get("username", "Player")
            player_id = str(uuid.uuid4())[:8]
            
            # Create server player
            player = ServerPlayer(player_id, username, client_socket, address)
            with self.players_lock:
                self.players[player_id] = player
            
            print(f"✅ {username} ({player_id}) logged in from {address}")
            
            # Send login success
            login_success = LoginSuccessMessage(player_id, self.spawn_position)
            player.send_message(login_success.to_json())
            
            # Notify other players about join
            join_msg = PlayerJoinMessage(player_id, username, self.spawn_position)
            self._broadcast(join_msg.to_json(), exclude_player=player_id)
            
            # Send list of existing players to new player
            existing_players = []
            with self.players_lock:
                for p_id, p in self.players.items():
                    if p_id != player_id:
                        existing_players.append({
                            "player_id": p_id,
                            "username": p.username,
                            "position": p.position.to_dict(),
                            "rotation": p.rotation,
                            "animation": p.animation_state
                        })
            if existing_players:
                player_list = PlayerListMessage(existing_players)
                player.send_message(player_list.to_json())
            
            # Listen for messages from this client
            while self.running:
                client_socket.settimeout(30.0)
                data = client_socket.recv(4096).decode("utf-8")
                
                if not data:
                    break
                
                for line in data.strip().split("\n"):
                    if line:
                        try:
                            msg = json.loads(line)
                            self._handle_client_message(player, msg)
                        except json.JSONDecodeError:
                            print(f"Invalid JSON from {player}: {line}")
        
        except socket.timeout:
            if player:
                print(f"⏱ {player.username} timed out")
        except Exception as e:
            if player:
                print(f"❌ Error handling {player.username}: {e}")
            else:
                print(f"❌ Error handling client {address}: {e}")
        
        finally:
            try:
                client_socket.close()
            except:
                pass
            
            if player:
                with self.players_lock:
                    if player.player_id in self.players:
                        del self.players[player.player_id]
                
                print(f"👋 {player.username} ({player.player_id}) disconnected")
                
                # Notify other players
                leave_msg = PlayerLeaveMessage(player.player_id)
                self._broadcast(leave_msg.to_json())
    
    def _handle_client_message(self, player: ServerPlayer, message: dict[str, Any]) -> None:
        """Process a message from a client."""
        msg_type = message.get("type")
        
        if msg_type == MessageType.PLAYER_UPDATE:
            # Update player state and broadcast to others
            player.position = Vector3.from_dict(message["position"])
            player.rotation = tuple(message["rotation"])
            player.animation_state = message.get("animation_state", "idle")
            player.last_update = time.time()
            
            # Broadcast position to other players
            update_msg = PlayerUpdateMessage(
                player.player_id,
                player.position,
                player.rotation,
                animation_state=player.animation_state
            )
            self._broadcast(update_msg.to_json(), exclude_player=player.player_id)
        
        elif msg_type == MessageType.BLOCK_CHANGE:
            # Validate and broadcast block change
            position = tuple(message["position"])
            old_block = message["old_block"]
            new_block = message["new_block"]
            
            # TODO: Validate that player is near block, inventory has required items, etc.
            # For now, just broadcast the change
            
            change_msg = BlockChangeMessage(position, old_block, new_block, player.player_id)
            self._broadcast(change_msg.to_json())
    
    def _broadcast(self, message: str, exclude_player: str | None = None) -> None:
        """Send message to all connected players.
        
        Args:
            message: JSON message to broadcast.
            exclude_player: Player ID to exclude (or None for all).
        """
        dead_players = []
        with self.players_lock:
            for player_id, player in self.players.items():
                if exclude_player and player_id == exclude_player:
                    continue
                if not player.send_message(message):
                    dead_players.append(player_id)
        
        # Remove dead connections
        with self.players_lock:
            for player_id in dead_players:
                if player_id in self.players:
                    print(f"Removing dead connection: {self.players[player_id]}")
                    del self.players[player_id]
    
    def _heartbeat_loop(self) -> None:
        """Periodically send state updates to clients."""
        while self.running:
            time.sleep(0.5)  # Send updates 2x per second
            
            # Broadcast current state of all players to all clients
            with self.players_lock:
                for player_id, player in list(self.players.items()):
                    msg = PlayerUpdateMessage(
                        player_id,
                        player.position,
                        player.rotation,
                        animation_state=player.animation_state
                    )
                    self._broadcast(msg.to_json(), exclude_player=player_id)
    
    def stop(self) -> None:
        """Stop the server."""
        print("Stopping server...")
        self.running = False
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        # Wait for threads
        for thread in self.threads:
            thread.join(timeout=2.0)
        
        print("Server stopped")


if __name__ == "__main__":
    # Run server
    server = VoxelSandboxServer(host="0.0.0.0", port=9999)
    server.start()
