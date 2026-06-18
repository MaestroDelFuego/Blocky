"""File: world_manager.py

Purpose:
    Central authority for all world state reads, edits, and events.

Responsibilities:
    * Route all block placement and destruction through one API.
    * Own event-based world updates for render and save systems.
    * Delegate chunk lifetime to ChunkManager.
    * Provide collision and raycast queries without exposing direct mutation.

Dependencies:
    * chunks.chunk for coordinates and height constants.
    * chunks.chunk_manager for chunk lifetime.
    * world.block_registry for block metadata.

Systems that depend on it:
    * PlayerController sends block action requests here.
    * RenderManager reads chunks and consumes world events.
    * SaveManager receives dirty chunk data through ChunkManager.

Future multiplayer considerations:
    This is the class that becomes server-authoritative. Clients should later
    send action requests, and the server should emit accepted world events.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from chunks.chunk import CHUNK_HEIGHT, ChunkCoord
from chunks.chunk_manager import ChunkManager
from world.block_registry import BlockRegistry


@dataclass(frozen=True)
class WorldEvent:
    """Serializable description of a world change.

    Purpose:
        Reports world changes without allowing subscribers to mutate state.

    Responsibilities:
        * Name the event type.
        * Include world position and block IDs involved.
        * Identify the affected chunk for rendering and saving.

    Lifecycle:
        Created by WorldManager when state changes, consumed by client systems.

    Dependencies:
        Uses dataclasses and ChunkCoord.

    Threading considerations:
        Immutable and safe to pass through future queues.

    Future networking considerations:
        This shape can become a world delta packet after validation and version
        fields are added.
    """

    event_type: str
    position: tuple[int, int, int]
    old_block: int
    new_block: int
    chunk: ChunkCoord


class WorldManager:
    """Authoritative world facade for single-player.

    Purpose:
        Provides the only public API for block modification.

    Responsibilities:
        * Load/unload chunks around the player.
        * Read block IDs and metadata.
        * Place and destroy blocks through event-producing methods.
        * Serve collision and raycast queries to player code.

    Lifecycle:
        Constructed once by GameManager after ChunkManager and BlockRegistry.

    Dependencies:
        Depends on ChunkManager and BlockRegistry.

    Threading considerations:
        Mutated on the main thread. Future server or worker queues should feed
        actions into this manager instead of mutating chunks directly.

    Future networking considerations:
        This class is intentionally server-shaped. Later, the server will own
        this manager and clients will receive WorldEvent streams.
    """

    def __init__(self, chunk_manager: ChunkManager, block_registry: BlockRegistry) -> None:
        """Create the world manager.

        Purpose:
            Stores dependencies and initializes the world event queue.

        Args:
            chunk_manager: Loaded chunk lifetime manager.
            block_registry: Block metadata registry.

        Returns:
            None.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        self.chunk_manager = chunk_manager
        self.blocks = block_registry
        self.events: list[WorldEvent] = []

    def update_streaming(self, position: tuple[float, float, float]) -> None:
        """Update chunk loading around a position.

        Purpose:
            Keeps chunks loaded near the player.

        Args:
            position: World-space player position.

        Returns:
            None.

        Side Effects:
            Loads, generates, saves, and unloads chunks through ChunkManager.

        Raises:
            OSError: If unloading dirty chunks fails to save.

        Performance considerations:
            O(r^2 + n), where r is load radius and n is loaded chunk count.
        """

        self.chunk_manager.update_around(position[0], position[2])

    def get_block(self, x: int, y: int, z: int) -> int:
        """Return the block ID at a world coordinate.

        Purpose:
            Provides safe world reads without exposing chunks directly.

        Args:
            x: World block X coordinate.
            y: World block Y coordinate.
            z: World block Z coordinate.

        Returns:
            Block ID, or air if outside loaded world/height bounds.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        if y < 0 or y >= CHUNK_HEIGHT:
            return BlockRegistry.AIR
        chunk = self.chunk_manager.get_chunk_at_block(x, z)
        if chunk is None:
            return BlockRegistry.AIR
        lx, ly, lz = self.chunk_manager.local_coords(x, y, z)
        return chunk.get_block(lx, ly, lz)

    def set_block(self, x: int, y: int, z: int, block_id: int) -> bool:
        """Set a block through authoritative world mutation.

        Purpose:
            Centralizes all block placement and destruction.

        Args:
            x: World block X coordinate.
            y: World block Y coordinate.
            z: World block Z coordinate.
            block_id: New stable block ID.

        Returns:
            True if the block changed, otherwise False.

        Side Effects:
            Mutates one chunk, marks render/save dirty, and emits a WorldEvent.

        Raises:
            No expected exceptions for loaded chunks; invalid heights return
            False instead.

        Performance considerations:
            O(1), plus neighboring chunk dirty marking.
        """

        if y < 0 or y >= CHUNK_HEIGHT:
            return False
        chunk = self.chunk_manager.get_chunk_at_block(x, z)
        if chunk is None:
            return False
        old_block = self.get_block(x, y, z)
        if old_block == block_id:
            return False

        lx, ly, lz = self.chunk_manager.local_coords(x, y, z)
        chunk.set_block(lx, ly, lz, block_id)
        coord = ChunkCoord.from_world(x, z)
        self._mark_neighbor_boundaries_dirty(x, z)
        self.events.append(WorldEvent("block_changed", (x, y, z), old_block, block_id, coord))
        return True

    def place_block(self, position: tuple[int, int, int], block_id: int) -> bool:
        """Place a block if the target is replaceable.

        Purpose:
            Handles player placement requests without giving player code chunk
            mutation access.

        Args:
            position: World block coordinate.
            block_id: Block ID to place.

        Returns:
            True if placement succeeded.

        Side Effects:
            May mutate world state and emit events through set_block().

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        x, y, z = position
        current = self.blocks.get(self.get_block(x, y, z))
        if current.solid and not current.liquid:
            return False
        return self.set_block(x, y, z, block_id)

    def destroy_block(self, position: tuple[int, int, int]) -> bool:
        """Destroy a non-air block.

        Purpose:
            Handles player destruction requests through central authority.

        Args:
            position: World block coordinate.

        Returns:
            True if destruction succeeded.

        Side Effects:
            May replace a block with air and emit events.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        x, y, z = position
        if self.get_block(x, y, z) == BlockRegistry.AIR:
            return False
        return self.set_block(x, y, z, BlockRegistry.AIR)

    def consume_events(self) -> list[WorldEvent]:
        """Return and clear pending world events.

        Purpose:
            Provides event-based updates to render and future networking layers.

        Args:
            None.

        Returns:
            List of pending WorldEvent objects.

        Side Effects:
            Clears the internal event queue.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(n), where n is pending event count.
        """

        events = self.events
        self.events = []
        return events

    def raycast(
        self,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
        max_distance: float = 6.0,
        step: float = 0.1,
    ) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
        """Find the first solid block along a ray.

        Purpose:
            Supports block placement and destruction targeting.

        Args:
            origin: World-space ray start.
            direction: Normalized direction vector.
            max_distance: Maximum ray distance in blocks.
            step: Distance between samples.

        Returns:
            Tuple of hit block position and adjacent placement position, or None.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(max_distance / step).
        """

        last_empty = (math.floor(origin[0]), math.floor(origin[1]), math.floor(origin[2]))
        distance = 0.0
        while distance <= max_distance:
            x = math.floor(origin[0] + direction[0] * distance)
            y = math.floor(origin[1] + direction[1] * distance)
            z = math.floor(origin[2] + direction[2] * distance)
            block = self.blocks.get(self.get_block(x, y, z))
            if block.solid:
                return (x, y, z), last_empty
            last_empty = (x, y, z)
            distance += step
        return None

    def collides_aabb(self, minimum: tuple[float, float, float], maximum: tuple[float, float, float]) -> bool:
        """Return whether an AABB intersects solid blocks.

        Purpose:
            Provides collision detection for the player controller.

        Args:
            minimum: Minimum world-space AABB corner.
            maximum: Maximum world-space AABB corner.

        Returns:
            True if any solid block intersects the box.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(v), where v is the number of block cells overlapped by the AABB.
        """

        min_x, min_y, min_z = (math.floor(value) for value in minimum)
        max_x, max_y, max_z = (math.floor(value) for value in maximum)
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                for z in range(min_z, max_z + 1):
                    if self.blocks.get(self.get_block(x, y, z)).solid:
                        return True
        return False

    def surface_y(self, x: int, z: int) -> int | None:
        """Return the top solid terrain Y at a loaded column."""

        for y in range(CHUNK_HEIGHT - 1, -1, -1):
            block = self.blocks.get(self.get_block(x, y, z))
            if block.solid:
                return y
        return None

    def safe_spawn_near(self, x: float, z: float, search_radius: int = 12) -> tuple[float, float, float]:
        """Find a safe standing position near a world X/Z point."""

        origin_x = math.floor(x)
        origin_z = math.floor(z)
        best: tuple[int, int, int] | None = None
        best_distance = float("inf")
        for radius in range(search_radius + 1):
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if max(abs(dx), abs(dz)) != radius:
                        continue
                    check_x = origin_x + dx
                    check_z = origin_z + dz
                    surface = self.surface_y(check_x, check_z)
                    if surface is None:
                        continue
                    foot_y = surface + 1
                    if self.get_block(check_x, foot_y, check_z) != BlockRegistry.AIR:
                        continue
                    if self.get_block(check_x, foot_y + 1, check_z) != BlockRegistry.AIR:
                        continue
                    distance = dx * dx + dz * dz
                    if distance < best_distance:
                        best = (check_x, foot_y, check_z)
                        best_distance = distance
            if best is not None:
                return (best[0] + 0.5, float(best[1]), best[2] + 0.5)
        return (origin_x + 0.5, 90.0, origin_z + 0.5)

    def _mark_neighbor_boundaries_dirty(self, x: int, z: int) -> None:
        """Mark adjacent chunks dirty when editing a boundary block.

        Purpose:
            Ensures face culling is rebuilt across chunk boundaries.

        Args:
            x: Edited world block X coordinate.
            z: Edited world block Z coordinate.

        Returns:
            None.

        Side Effects:
            May set dirty_for_render on neighboring chunks.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        for nx, nz in ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1)):
            neighbor = self.chunk_manager.get_chunk_at_block(nx, nz)
            if neighbor is not None:
                neighbor.dirty_for_render = True
