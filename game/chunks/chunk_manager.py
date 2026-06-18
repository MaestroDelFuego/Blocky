"""File: chunk_manager.py

Purpose:
    Loads, generates, unloads, and saves chunks around the player.

Responsibilities:
    * Keep a radius of chunks loaded around a focus point.
    * Load saved chunks before generating new procedural chunks.
    * Unload distant chunks after saving dirty data.
    * Provide chunk lookup for WorldManager and RenderManager.

Dependencies:
    * chunks.chunk for Chunk and coordinate types.
    * terrain.terrain_generator for procedural chunk creation.
    * saving.save_manager for persistence.

Systems that depend on it:
    * WorldManager uses ChunkManager for block access.
    * RenderManager scans loaded chunks.
    * GameManager ticks loading and unloading through WorldManager.

Future multiplayer considerations:
    The dedicated server will own authoritative chunk loading. Clients may keep
    a cache of received chunks, but should not decide canonical chunk contents.
"""

from __future__ import annotations

from chunks.chunk import CHUNK_SIZE, Chunk, ChunkCoord
from saving.save_manager import SaveManager
from terrain.terrain_generator import TerrainGenerator


class ChunkManager:
    """Manager for loaded chunk lifetime.

    Purpose:
        Maintains the active chunk set for a single-player world.

    Responsibilities:
        * Resolve world coordinates to chunks.
        * Load or generate chunks on demand.
        * Save dirty chunks before unloading.
        * Track which chunks have changed for rendering.

    Lifecycle:
        Constructed once by GameManager and owned by WorldManager.

    Dependencies:
        Depends on TerrainGenerator and SaveManager.

    Threading considerations:
        Current loading is synchronous. Future background generation must return
        completed Chunk objects through a main-thread queue before insertion.

    Future networking considerations:
        Server-owned chunk streaming can reuse coordinates and serialization but
        replace local generation with network receive queues on clients.
    """

    def __init__(self, terrain_generator: TerrainGenerator, save_manager: SaveManager, load_radius: int = 3) -> None:
        """Create the chunk manager.

        Purpose:
            Stores dependencies and initializes the loaded chunk map.

        Args:
            terrain_generator: Procedural terrain source.
            save_manager: Persistence system.
            load_radius: Radius in chunks to keep around the player.

        Returns:
            None.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        self.terrain_generator = terrain_generator
        self.save_manager = save_manager
        self.load_radius = load_radius
        self.loaded: dict[ChunkCoord, Chunk] = {}
        self.pending_loads: list[ChunkCoord] = []
        self.max_loads_per_update = 1
        self.max_unloads_per_update = 2

    def update_around(self, world_x: float, world_z: float) -> list[Chunk]:
        """Load and unload chunks around a world position.

        Purpose:
            Keeps the active world window centered near the player.

        Args:
            world_x: Focus X position.
            world_z: Focus Z position.

        Returns:
            List of chunks newly loaded this call.

        Side Effects:
            Loads/generates chunks and unloads distant chunks.

        Raises:
            OSError: If saving dirty chunks fails.

        Performance considerations:
            O(r^2 + u), where r is load radius and u is loaded chunk count.
        """

        center = ChunkCoord.from_world(int(world_x), int(world_z))
        required = {
            ChunkCoord(center.x + dx, center.z + dz)
            for dx in range(-self.load_radius, self.load_radius + 1)
            for dz in range(-self.load_radius, self.load_radius + 1)
        }

        loaded_now = []
        pending = {coord for coord in self.pending_loads if coord in required and coord not in self.loaded}
        missing = required - set(self.loaded) - pending
        self.pending_loads = [coord for coord in self.pending_loads if coord in pending]
        self.pending_loads.extend(
            sorted(
                missing,
                key=lambda coord: (abs(coord.x - center.x) + abs(coord.z - center.z), coord.x, coord.z),
            )
        )

        for _ in range(min(self.max_loads_per_update, len(self.pending_loads))):
            coord = self.pending_loads.pop(0)
            if coord not in self.loaded and coord in required:
                loaded_now.append(self.load_chunk(coord))

        unloaded = 0
        for coord in sorted(
            [coord for coord in self.loaded if coord not in required],
            key=lambda coord: abs(coord.x - center.x) + abs(coord.z - center.z),
            reverse=True,
        ):
            if unloaded >= self.max_unloads_per_update:
                break
            if coord not in required:
                self.unload_chunk(coord)
                unloaded += 1

        return loaded_now

    def load_chunk(self, coord: ChunkCoord) -> Chunk:
        """Load or generate one chunk.

        Purpose:
            Ensures a chunk is available for simulation and rendering.

        Args:
            coord: Chunk coordinate to load.

        Returns:
            Loaded Chunk.

        Side Effects:
            Reads saves or generates terrain, then stores the chunk in memory.

        Raises:
            json.JSONDecodeError: If saved chunk data is corrupt.

        Performance considerations:
            O(n) for saved chunk size or procedural terrain generation cost.
        """

        saved = self.save_manager.load_chunk(coord)
        chunk = saved if saved is not None else self.terrain_generator.generate_chunk(coord)
        self.loaded[coord] = chunk
        return chunk

    def unload_chunk(self, coord: ChunkCoord) -> None:
        """Unload one chunk.

        Purpose:
            Removes a distant chunk after persisting edits.

        Args:
            coord: Chunk coordinate to unload.

        Returns:
            None.

        Side Effects:
            May write chunk data to disk and removes the chunk from memory.

        Raises:
            OSError: If saving fails.

        Performance considerations:
            O(n) if the chunk is dirty, otherwise O(1).
        """

        chunk = self.loaded.pop(coord, None)
        if chunk is not None and chunk.dirty_for_save:
            self.save_manager.save_chunk(chunk)

    def get_chunk(self, coord: ChunkCoord) -> Chunk | None:
        """Return a loaded chunk by coordinate.

        Purpose:
            Provides safe access to the loaded chunk map.

        Args:
            coord: Chunk coordinate.

        Returns:
            Chunk or None if not loaded.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        return self.loaded.get(coord)

    def get_chunk_at_block(self, x: int, z: int) -> Chunk | None:
        """Return the loaded chunk containing a world block coordinate.

        Purpose:
            Converts world block coordinates to a loaded chunk lookup.

        Args:
            x: World block X coordinate.
            z: World block Z coordinate.

        Returns:
            Chunk or None if not loaded.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        return self.get_chunk(ChunkCoord.from_world(x, z))

    def local_coords(self, x: int, y: int, z: int) -> tuple[int, int, int]:
        """Convert world block coordinates to local chunk coordinates.

        Purpose:
            Normalizes block access for negative and positive world positions.

        Args:
            x: World block X coordinate.
            y: World block Y coordinate.
            z: World block Z coordinate.

        Returns:
            Local coordinate tuple.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        return x % CHUNK_SIZE, y, z % CHUNK_SIZE

    def dirty_render_chunks(self) -> list[Chunk]:
        """Return chunks needing mesh rebuilds.

        Purpose:
            Lets RenderManager rebuild only changed chunks.

        Args:
            None.

        Returns:
            List of render-dirty chunks.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(n), where n is loaded chunk count.
        """

        return [chunk for chunk in self.loaded.values() if chunk.dirty_for_render]

    def save_all(self) -> None:
        """Save all dirty chunks.

        Purpose:
            Flushes world edits before shutdown or periodic autosave.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Writes dirty chunks to disk.

        Raises:
            OSError: If any chunk file cannot be written.

        Performance considerations:
            O(d * n), where d is dirty chunk count and n is average chunk size.
        """

        for chunk in self.loaded.values():
            if chunk.dirty_for_save:
                self.save_manager.save_chunk(chunk)
