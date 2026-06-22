"""File: protocol.py

Purpose:
    Defines serializable message types and protocol constants for multiplayer.

Responsibilities:
    * Define message format for client-server communication.
    * Provide serialization/deserialization helpers.
    * Document protocol versioning and compatibility.

Dependencies:
    * json for message serialization.
    * dataclasses for type safety.

Systems that depend on it:
    * networking.client for sending/receiving messages.
    * server.py for processing messages.

Future considerations:
    * Compression for position/state updates.
    * Binary serialization for performance.
    * Protocol versioning with backwards compatibility.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any


PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class Vector3:
    """3D position or velocity vector."""
    x: float
    y: float
    z: float
    
    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}
    
    @staticmethod
    def from_dict(data: dict[str, float]) -> Vector3:
        return Vector3(data["x"], data["y"], data["z"])


# Message Type Constants
class MessageType:
    # Connection messages
    LOGIN = "login"
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    
    # Player state messages
    PLAYER_UPDATE = "player_update"
    PLAYER_JOIN = "player_join"
    PLAYER_LEAVE = "player_leave"
    PLAYER_LIST = "player_list"
    
    # World interaction messages
    BLOCK_CHANGE = "block_change"
    BLOCK_CHANGES = "block_changes"
    
    # Chat/messaging
    CHAT = "chat"
    
    # Chunk data
    CHUNK_DATA = "chunk_data"
    CHUNK_REQUEST = "chunk_request"
    
    # Ping/keep-alive
    PING = "ping"
    PONG = "pong"


@dataclass
class LoginMessage:
    """Client login request."""
    username: str
    protocol_version: int = PROTOCOL_VERSION
    
    def to_json(self) -> str:
        return json.dumps({
            "type": MessageType.LOGIN,
            "username": self.username,
            "protocol_version": self.protocol_version
        })
    
    @staticmethod
    def from_json(data: str) -> LoginMessage:
        obj = json.loads(data)
        return LoginMessage(obj["username"], obj.get("protocol_version", 1))


@dataclass
class LoginSuccessMessage:
    """Server confirms successful login."""
    player_id: str
    spawn_pos: Vector3
    
    def to_json(self) -> str:
        return json.dumps({
            "type": MessageType.LOGIN_SUCCESS,
            "player_id": self.player_id,
            "spawn_pos": self.spawn_pos.to_dict()
        })
    
    @staticmethod
    def from_json(data: str) -> LoginSuccessMessage:
        obj = json.loads(data)
        return LoginSuccessMessage(
            obj["player_id"],
            Vector3.from_dict(obj["spawn_pos"])
        )


@dataclass
class PlayerUpdateMessage:
    """Periodic player state sync (position, rotation, animation)."""
    player_id: str
    position: Vector3
    rotation: tuple[float, float]  # (pitch, yaw) in radians
    velocity: Vector3 | None = None
    animation_state: str = "idle"  # idle, walking, jumping, falling
    
    def to_json(self) -> str:
        data = {
            "type": MessageType.PLAYER_UPDATE,
            "player_id": self.player_id,
            "position": self.position.to_dict(),
            "rotation": self.rotation,
            "animation_state": self.animation_state
        }
        if self.velocity:
            data["velocity"] = self.velocity.to_dict()
        return json.dumps(data)
    
    @staticmethod
    def from_json(data: str) -> PlayerUpdateMessage:
        obj = json.loads(data)
        return PlayerUpdateMessage(
            obj["player_id"],
            Vector3.from_dict(obj["position"]),
            tuple(obj["rotation"]),
            Vector3.from_dict(obj["velocity"]) if "velocity" in obj else None,
            obj.get("animation_state", "idle")
        )


@dataclass
class PlayerJoinMessage:
    """Notify other players that someone joined."""
    player_id: str
    username: str
    position: Vector3
    
    def to_json(self) -> str:
        return json.dumps({
            "type": MessageType.PLAYER_JOIN,
            "player_id": self.player_id,
            "username": self.username,
            "position": self.position.to_dict()
        })
    
    @staticmethod
    def from_json(data: str) -> PlayerJoinMessage:
        obj = json.loads(data)
        return PlayerJoinMessage(
            obj["player_id"],
            obj["username"],
            Vector3.from_dict(obj["position"])
        )


@dataclass
class PlayerLeaveMessage:
    """Notify other players that someone left."""
    player_id: str
    
    def to_json(self) -> str:
        return json.dumps({
            "type": MessageType.PLAYER_LEAVE,
            "player_id": self.player_id
        })
    
    @staticmethod
    def from_json(data: str) -> PlayerLeaveMessage:
        obj = json.loads(data)
        return PlayerLeaveMessage(obj["player_id"])


@dataclass
class PlayerListMessage:
    """Server sends list of all connected players."""
    players: list[dict[str, Any]]  # [{player_id, username, position}, ...]
    
    def to_json(self) -> str:
        return json.dumps({
            "type": MessageType.PLAYER_LIST,
            "players": self.players
        })
    
    @staticmethod
    def from_json(data: str) -> PlayerListMessage:
        obj = json.loads(data)
        return PlayerListMessage(obj["players"])


@dataclass
class BlockChangeMessage:
    """Notify about a single block change."""
    position: tuple[int, int, int]  # (x, y, z)
    old_block: int
    new_block: int
    player_id: str | None = None
    
    def to_json(self) -> str:
        data = {
            "type": MessageType.BLOCK_CHANGE,
            "position": self.position,
            "old_block": self.old_block,
            "new_block": self.new_block
        }
        if self.player_id:
            data["player_id"] = self.player_id
        return json.dumps(data)
    
    @staticmethod
    def from_json(data: str) -> BlockChangeMessage:
        obj = json.loads(data)
        return BlockChangeMessage(
            tuple(obj["position"]),
            obj["old_block"],
            obj["new_block"],
            obj.get("player_id")
        )


@dataclass
class BlockChangesMessage:
    """Batch multiple block changes (efficient for chunk updates)."""
    changes: list[dict[str, Any]]  # [{position, old_block, new_block}, ...]
    
    def to_json(self) -> str:
        return json.dumps({
            "type": MessageType.BLOCK_CHANGES,
            "changes": self.changes
        })
    
    @staticmethod
    def from_json(data: str) -> BlockChangesMessage:
        obj = json.loads(data)
        return BlockChangesMessage(obj["changes"])


def parse_message(raw_data: str) -> dict[str, Any]:
    """Parse a raw JSON message and return its type and content."""
    try:
        obj = json.loads(raw_data)
        return obj
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON message: {e}")
