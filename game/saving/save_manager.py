"""File: save_manager.py

Purpose:
    Persists world metadata and modified chunks to local JSON files.

Responsibilities:
    * Store world seed and player state.
    * Save dirty chunks using serializable chunk dictionaries.
    * Load chunk overrides before procedural generation is used.
    * Keep save data plain enough for future migration and network tooling.

Dependencies:
    * json for offline persistence.
    * pathlib for save directory paths.
    * chunks.chunk for Chunk serialization.

Systems that depend on it:
    * ChunkManager asks for saved chunk overrides.
    * WorldManager marks edited chunks dirty.
    * GameManager calls periodic and shutdown saves.

Future multiplayer considerations:
    A dedicated server should own this system. The client may keep local
    settings, but authoritative world and inventory saves must move server-side.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chunks.chunk import Chunk, ChunkCoord


class SaveManager:
    """JSON save/load coordinator for the single-player world.

    Purpose:
        Provides persistence without leaking file I/O into world logic.

    Responsibilities:
        * Create save directories.
        * Save and load world metadata.
        * Save and load individual chunks.
        * Save and load player snapshots.

    Lifecycle:
        Constructed once by GameManager and used until shutdown.

    Dependencies:
        Depends on pathlib, json, and Chunk serialization.

    Threading considerations:
        Current saves are synchronous and should be called at low frequency.
        Future background saves must copy chunk data before worker-thread I/O.

    Future networking considerations:
        This system moves to the server for authoritative multiplayer. The
        serialization format is intentionally simple so it can be converted into
        binary chunk packets later.
    """

    def __init__(self, save_root: Path, world_name: str = "default_world") -> None:
        """Create the save manager.

        Purpose:
            Initializes save paths and ensures directories exist.

        Args:
            save_root: Base directory for all saves.
            world_name: Name of the active single-player world.

        Returns:
            None.

        Side Effects:
            Creates save directories on disk.

        Raises:
            OSError: If directories cannot be created.

        Performance considerations:
            O(1) directory creation.
        """

        self.save_root = Path(save_root)
        self.world_name = world_name
        self.world_dir = self.save_root / world_name
        self.chunk_dir = self.world_dir / "chunks"
        self.ignore_saved_chunks = False
        self.terrain_version = 2
        self.chunk_dir.mkdir(parents=True, exist_ok=True)

    def load_metadata(self, default_seed: int) -> dict[str, Any]:
        """Load world metadata.

        Purpose:
            Reads world-level settings such as seed and time of day.

        Args:
            default_seed: Seed used when no metadata exists.

        Returns:
            Metadata dictionary.

        Side Effects:
            None.

        Raises:
            json.JSONDecodeError: If the metadata file is corrupt.

        Performance considerations:
            O(n), where n is metadata file size.
        """

        path = self.world_dir / "world.json"
        if not path.exists():
            return {"seed": default_seed, "time_of_day": 0.25}
        return json.loads(path.read_text(encoding="utf-8"))

    def save_metadata(self, metadata: dict[str, Any]) -> None:
        """Save world metadata.

        Purpose:
            Persists seed, time-of-day, and future world settings.

        Args:
            metadata: JSON-compatible world metadata.

        Returns:
            None.

        Side Effects:
            Writes world.json.

        Raises:
            OSError: If the file cannot be written.

        Performance considerations:
            O(n), where n is serialized metadata size.
        """

        (self.world_dir / "world.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def chunk_path(self, coord: ChunkCoord) -> Path:
        """Return the save path for one chunk.

        Purpose:
            Centralizes chunk filename rules.

        Args:
            coord: Chunk coordinate.

        Returns:
            Path to the chunk JSON file.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        return self.chunk_dir / f"chunk_{coord.x}_{coord.z}.json"

    def load_chunk(self, coord: ChunkCoord) -> Chunk | None:
        """Load a saved chunk override.

        Purpose:
            Restores previously modified chunk state.

        Args:
            coord: Chunk coordinate to load.

        Returns:
            Chunk if a saved file exists, otherwise None.

        Side Effects:
            Reads from disk.

        Raises:
            json.JSONDecodeError: If the chunk file is corrupt.
            ValueError: If serialized block coordinates are invalid.

        Performance considerations:
            O(n), where n is serialized block count.
        """

        path = self.chunk_path(coord)
        if self.ignore_saved_chunks:
            return None
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("terrain_version", 1)) < self.terrain_version:
            return None
        return Chunk.from_dict(data)

    def save_chunk(self, chunk: Chunk) -> None:
        """Save a chunk.

        Purpose:
            Persists all non-air blocks for a modified chunk.

        Args:
            chunk: Chunk to save.

        Returns:
            None.

        Side Effects:
            Writes a chunk JSON file and clears the chunk save-dirty flag.

        Raises:
            OSError: If the file cannot be written.

        Performance considerations:
            O(n), where n is the number of non-air blocks.
        """

        data = chunk.to_dict()
        data["terrain_version"] = self.terrain_version
        self.chunk_path(chunk.coord).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        chunk.dirty_for_save = False

    def load_player(self) -> dict[str, Any] | None:
        """Load player state.

        Purpose:
            Restores position, camera rotation, and hotbar selection.

        Args:
            None.

        Returns:
            Player state dictionary or None if no state is saved.

        Side Effects:
            Reads player.json when present.

        Raises:
            json.JSONDecodeError: If player.json is corrupt.

        Performance considerations:
            O(n), where n is player file size.
        """

        path = self.world_dir / "player.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_player(self, player_state: dict[str, Any]) -> None:
        """Save player state.

        Purpose:
            Persists local player snapshot for single-player continuity.

        Args:
            player_state: JSON-compatible player state.

        Returns:
            None.

        Side Effects:
            Writes player.json.

        Raises:
            OSError: If the file cannot be written.

        Performance considerations:
            O(n), where n is serialized player state size.
        """

        (self.world_dir / "player.json").write_text(json.dumps(player_state, indent=2), encoding="utf-8")
