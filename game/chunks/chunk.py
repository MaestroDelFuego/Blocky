"""File: chunk.py

Purpose:
    Stores serializable block data for one 16x16x256 world chunk.

Responsibilities:
    * Convert between local and world block coordinates.
    * Store only non-air blocks for memory efficiency.
    * Track dirty state for save and render updates.
    * Serialize chunk payloads using stable block IDs.

Dependencies:
    * dataclasses for chunk coordinate representation.
    * world.block_registry.BlockRegistry for air ID.

Systems that depend on it:
    * ChunkManager owns Chunk instances.
    * WorldManager reads and writes blocks through chunk APIs.
    * RenderManager reads chunk snapshots to build meshes.
    * SaveManager persists modified chunks.

Future multiplayer considerations:
    The to_dict/from_dict shape is intentionally plain JSON-compatible data.
    A future server can transmit equivalent payloads after compression or binary
    encoding without changing world semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from world.block_registry import BlockRegistry


CHUNK_SIZE = 16
CHUNK_HEIGHT = 256


@dataclass(frozen=True, order=True)
class ChunkCoord:
    """Integer chunk coordinate on the horizontal world grid.

    Purpose:
        Identifies one 16x16 column of blocks.

    Responsibilities:
        * Provide a hashable chunk key.
        * Convert world X/Z block coordinates into chunk ownership.

    Lifecycle:
        Created whenever systems address chunks.

    Dependencies:
        Uses dataclasses only.

    Threading considerations:
        Immutable and safe to share.

    Future networking considerations:
        This coordinate is suitable for chunk request and chunk payload headers.
    """

    x: int
    z: int

    @classmethod
    def from_world(cls, x: int, z: int) -> "ChunkCoord":
        """Create a chunk coordinate from world block coordinates.

        Purpose:
            Maps any world X/Z block location to its owning chunk.

        Args:
            x: World block X coordinate.
            z: World block Z coordinate.

        Returns:
            ChunkCoord containing the block.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        return cls(x // CHUNK_SIZE, z // CHUNK_SIZE)


class Chunk:
    """Sparse serializable storage for one chunk column.

    Purpose:
        Holds generated and modified block IDs for a chunk.

    Responsibilities:
        * Store non-air block IDs by local coordinate.
        * Reject out-of-bounds local positions.
        * Report dirty state for rendering and saving.
        * Convert chunk data to and from JSON-compatible dictionaries.

    Lifecycle:
        Created by ChunkManager when a chunk enters simulation range. It may be
        unloaded after serialization when it leaves range.

    Dependencies:
        Depends on ChunkCoord and BlockRegistry IDs.

    Threading considerations:
        Mutated only on the main simulation thread in the current client.
        Future worker threads should generate detached data, then hand it to
        ChunkManager through a queue.

    Future networking considerations:
        Chunk block payloads use stable integer IDs and local coordinates. A
        future server can transmit the same state as snapshots or deltas.
    """

    def __init__(self, coord: ChunkCoord, blocks: dict[tuple[int, int, int], int] | None = None) -> None:
        """Create a chunk.

        Purpose:
            Initializes sparse block storage for a chunk coordinate.

        Args:
            coord: Horizontal chunk coordinate.
            blocks: Optional initial non-air block dictionary.

        Returns:
            None.

        Side Effects:
            Copies initial block data into this chunk.

        Raises:
            ValueError: If any initial coordinate is out of bounds.

        Performance considerations:
            O(n), where n is the number of supplied non-air blocks.
        """

        self.coord = coord
        self.blocks: dict[tuple[int, int, int], int] = {}
        self.dirty_for_render = True
        self.dirty_for_save = False

        for position, block_id in (blocks or {}).items():
            self._validate_local(*position)
            if block_id != BlockRegistry.AIR:
                self.blocks[position] = block_id

    def _validate_local(self, x: int, y: int, z: int) -> None:
        """Validate local chunk coordinates.

        Purpose:
            Prevents corrupt chunk storage from out-of-range positions.

        Args:
            x: Local X coordinate.
            y: Local Y coordinate.
            z: Local Z coordinate.

        Returns:
            None.

        Side Effects:
            None.

        Raises:
            ValueError: If a coordinate is outside chunk bounds.

        Performance considerations:
            O(1).
        """

        if not (0 <= x < CHUNK_SIZE and 0 <= y < CHUNK_HEIGHT and 0 <= z < CHUNK_SIZE):
            raise ValueError(f"Local block coordinate out of bounds: {(x, y, z)}")

    def get_block(self, x: int, y: int, z: int) -> int:
        """Return a block ID from local coordinates.

        Purpose:
            Reads sparse chunk storage with air as the implicit default.

        Args:
            x: Local X coordinate.
            y: Local Y coordinate.
            z: Local Z coordinate.

        Returns:
            Numeric block ID.

        Side Effects:
            None.

        Raises:
            No expected exceptions; out-of-height reads return air.

        Performance considerations:
            O(1).
        """

        if not (0 <= x < CHUNK_SIZE and 0 <= y < CHUNK_HEIGHT and 0 <= z < CHUNK_SIZE):
            return BlockRegistry.AIR
        return self.blocks.get((x, y, z), BlockRegistry.AIR)

    def set_block(self, x: int, y: int, z: int, block_id: int, mark_saved_dirty: bool = True) -> None:
        """Set a block ID at local coordinates.

        Purpose:
            Applies one chunk-local block mutation.

        Args:
            x: Local X coordinate.
            y: Local Y coordinate.
            z: Local Z coordinate.
            block_id: Stable block ID to store.
            mark_saved_dirty: Whether this edit should be persisted.

        Returns:
            None.

        Side Effects:
            Mutates block storage and marks render/save dirty flags.

        Raises:
            ValueError: If the local coordinate is outside chunk bounds.

        Performance considerations:
            O(1).
        """

        self._validate_local(x, y, z)
        key = (x, y, z)
        if block_id == BlockRegistry.AIR:
            self.blocks.pop(key, None)
        else:
            self.blocks[key] = block_id
        self.dirty_for_render = True
        if mark_saved_dirty:
            self.dirty_for_save = True

    def iter_blocks(self) -> Iterable[tuple[tuple[int, int, int], int]]:
        """Iterate non-air local blocks.

        Purpose:
            Allows render and save systems to scan chunk contents.

        Args:
            None.

        Returns:
            Iterable of ((x, y, z), block_id) pairs.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1) to create the view; consumers pay O(n).
        """

        return self.blocks.items()

    def to_dict(self) -> dict[str, object]:
        """Serialize the chunk to JSON-compatible data.

        Purpose:
            Converts sparse block data into a portable save/network shape.

        Args:
            None.

        Returns:
            Dictionary containing chunk coordinate and non-air blocks.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(n), where n is the number of non-air blocks.
        """

        return {
            "coord": {"x": self.coord.x, "z": self.coord.z},
            "blocks": [[x, y, z, block_id] for (x, y, z), block_id in self.blocks.items()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Chunk":
        """Create a chunk from serialized data.

        Purpose:
            Rehydrates chunk state from SaveManager or future network payloads.

        Args:
            data: JSON-compatible chunk dictionary.

        Returns:
            Chunk instance containing the serialized block data.

        Side Effects:
            None.

        Raises:
            KeyError: If required fields are missing.
            ValueError: If serialized coordinates are invalid.

        Performance considerations:
            O(n), where n is serialized block count.
        """

        coord_data = data["coord"]
        assert isinstance(coord_data, dict)
        coord = ChunkCoord(int(coord_data["x"]), int(coord_data["z"]))
        blocks: dict[tuple[int, int, int], int] = {}
        for entry in data.get("blocks", []):
            x, y, z, block_id = entry
            blocks[(int(x), int(y), int(z))] = int(block_id)
        chunk = cls(coord, blocks)
        chunk.dirty_for_render = True
        chunk.dirty_for_save = False
        return chunk
