"""File: terrain_generator.py

Purpose:
    Generates deterministic seed-based terrain and biomes.

Responsibilities:
    * Produce repeatable terrain from world coordinates.
    * Select plains, forest, desert, and mountain biomes.
    * Fill chunk block data using registry block IDs.
    * Add simple trees, water, stone, dirt, grass, and sand.

Dependencies:
    * math for deterministic procedural noise.
    * chunks.chunk for chunk constants and storage.
    * world.block_registry for block IDs.

Systems that depend on it:
    * ChunkManager requests generated chunks.
    * WorldManager relies on deterministic generation before applying saves.

Future multiplayer considerations:
    Terrain generation must remain deterministic between client and future
    server. A server-authoritative model can send chunk payloads while clients
    optionally generate previews from the same seed.
"""

from __future__ import annotations

import math

from chunks.chunk import CHUNK_SIZE, Chunk, ChunkCoord
from world.block_registry import BlockRegistry


class TerrainGenerator:
    """Deterministic terrain generator for chunk columns.

    Purpose:
        Converts a world seed and chunk coordinate into block data.

    Responsibilities:
        * Generate height and biome values from coordinate noise.
        * Fill chunk storage with terrain layers.
        * Place deterministic trees in forest biomes.

    Lifecycle:
        Constructed once by GameManager and shared with ChunkManager.

    Dependencies:
        Depends on BlockRegistry for stable block IDs and Chunk for storage.

    Threading considerations:
        Stateless after construction except for immutable seed and registry
        references, so generation can later move to workers.

    Future networking considerations:
        Seed and generator version must be part of world metadata. A future
        server can transmit generated chunks or validate client preview chunks.
    """

    SEA_LEVEL = 62

    def __init__(self, seed: int, block_registry: BlockRegistry) -> None:
        """Create a terrain generator.

        Purpose:
            Stores the deterministic seed and block registry.

        Args:
            seed: Integer world seed.
            block_registry: Registry that defines block IDs.

        Returns:
            None.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        self.seed = seed
        self.blocks = block_registry

    def generate_chunk(self, coord: ChunkCoord) -> Chunk:
        """Generate one chunk.

        Purpose:
            Creates deterministic block storage for a chunk coordinate.

        Args:
            coord: Chunk coordinate to generate.

        Returns:
            Generated Chunk.

        Side Effects:
            None outside the returned chunk.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(CHUNK_SIZE * CHUNK_SIZE * terrain_height). Terrain height is
            bounded by world height and usually below 100.
        """

        chunk = Chunk(coord)
        for local_x in range(CHUNK_SIZE):
            for local_z in range(CHUNK_SIZE):
                world_x = coord.x * CHUNK_SIZE + local_x
                world_z = coord.z * CHUNK_SIZE + local_z
                biome = self.get_biome(world_x, world_z)
                height = self.get_height(world_x, world_z, biome)
                self._fill_column(chunk, local_x, local_z, world_x, world_z, height, biome)
                if biome == "forest" and self._tree_roll(world_x, world_z):
                    self._place_tree(chunk, local_x, height + 1, local_z)

        chunk.dirty_for_render = True
        chunk.dirty_for_save = False
        return chunk

    def get_biome(self, x: int, z: int) -> str:
        """Return the biome at a world coordinate.

        Purpose:
            Selects a coarse biome from deterministic low-frequency noise.

        Args:
            x: World block X coordinate.
            z: World block Z coordinate.

        Returns:
            One of plains, forest, desert, or mountain.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        value = self._noise(x * 0.006, z * 0.006)
        if value < -0.28:
            return "desert"
        if value < 0.18:
            return "plains"
        if value < 0.55:
            return "forest"
        return "mountain"

    def get_height(self, x: int, z: int, biome: str | None = None) -> int:
        """Return terrain height at a world coordinate.

        Purpose:
            Computes the top solid or surface block Y coordinate.

        Args:
            x: World block X coordinate.
            z: World block Z coordinate.
            biome: Optional precomputed biome name.

        Returns:
            Integer surface height.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        biome = biome or self.get_biome(x, z)
        base = 66
        continent = self._octave_noise(x, z, 0.006, 3)
        rolling = self._octave_noise(x + 400, z - 400, 0.026, 4)
        detail = self._octave_noise(x - 900, z + 900, 0.080, 2)
        if biome == "desert":
            height = base - 3 + continent * 4 + rolling * 3 + detail
        elif biome == "mountain":
            ridges = abs(self._octave_noise(x - 500, z + 500, 0.014, 4))
            height = base + 9 + continent * 7 + rolling * 10 + ridges * 30
        elif biome == "forest":
            height = base + 1 + continent * 5 + rolling * 5 + detail * 2
        else:
            height = base + continent * 5 + rolling * 4 + detail
        return max(48, min(140, int(height)))

    def _fill_column(self, chunk: Chunk, x: int, z: int, world_x: int, world_z: int, height: int, biome: str) -> None:
        """Fill one terrain column.

        Purpose:
            Writes stone, dirt/sand, surface, and water blocks into a chunk.

        Args:
            chunk: Chunk being generated.
            x: Local X coordinate.
            z: Local Z coordinate.
            height: Surface height.
            biome: Biome name for surface selection.

        Returns:
            None.

        Side Effects:
            Mutates the generated chunk without marking it save-dirty.

        Raises:
            ValueError: If local coordinates are invalid.

        Performance considerations:
            O(height).
        """

        surface = BlockRegistry.SAND if biome == "desert" or height <= self.SEA_LEVEL + 1 else BlockRegistry.GRASS
        subsurface = BlockRegistry.SAND if biome == "desert" else BlockRegistry.DIRT
        for y in range(height + 1):
            if y == 0:
                block_id = BlockRegistry.STONE
            elif y < height - 5:
                block_id = BlockRegistry.STONE

                # ONLY compute ore noise in valid height range
                if 6 < y < 54:
                    ore_roll = self._hash_noise(
                        world_x * 17 + y * 3,
                        world_z * 17 - y * 5
                    )

                    if ore_roll > 0.965:
                        block_id = BlockRegistry.COAL_ORE

                    elif ore_roll < -0.975:
                        block_id = BlockRegistry.IRON_ORE
            elif y < height:
                block_id = subsurface
            else:
                block_id = surface
                if biome == "mountain" and height > 96:
                    block_id = BlockRegistry.SNOW
                elif height <= self.SEA_LEVEL + 1 and biome != "desert":
                    block_id = BlockRegistry.CLAY
            chunk.set_block(x, y, z, block_id, mark_saved_dirty=False)

        if height < self.SEA_LEVEL:
            for y in range(height + 1, self.SEA_LEVEL + 1):
                chunk.set_block(x, y, z, BlockRegistry.WATER, mark_saved_dirty=False)
        elif biome == "desert" and height > self.SEA_LEVEL + 1 and self._hash_noise(world_x * 9, world_z * 9) > 0.982:
            cactus_height = 2 + int(abs(self._hash_noise(world_x * 13, world_z * 13)) * 3)
            for cactus_y in range(height + 1, min(height + 1 + cactus_height, 245)):
                chunk.set_block(x, cactus_y, z, BlockRegistry.CACTUS, mark_saved_dirty=False)

    def _place_tree(self, chunk: Chunk, x: int, y: int, z: int) -> None:
        """Place a simple tree inside the chunk.

        Purpose:
            Adds deterministic forest decoration.

        Args:
            chunk: Chunk being generated.
            x: Local X coordinate.
            y: Trunk base Y coordinate.
            z: Local Z coordinate.

        Returns:
            None.

        Side Effects:
            Mutates generated chunk data.

        Raises:
            No expected exceptions; out-of-chunk leaves are skipped.

        Performance considerations:
            O(1), bounded tree size.
        """

        if not (2 <= x <= CHUNK_SIZE - 3 and 2 <= z <= CHUNK_SIZE - 3 and y < 245):
            return
        for trunk_y in range(y, y + 5):
            chunk.set_block(x, trunk_y, z, BlockRegistry.WOOD, mark_saved_dirty=False)
        for leaf_x in range(x - 2, x + 3):
            for leaf_y in range(y + 3, y + 7):
                for leaf_z in range(z - 2, z + 3):
                    distance = abs(leaf_x - x) + abs(leaf_z - z) + max(0, leaf_y - (y + 4))
                    if distance <= 4:
                        chunk.set_block(leaf_x, leaf_y, leaf_z, BlockRegistry.LEAVES, mark_saved_dirty=False)

    def _tree_roll(self, x: int, z: int) -> bool:
        """Return whether a tree should spawn at a world column.

        Purpose:
            Keeps forest decoration deterministic and sparse.

        Args:
            x: World block X coordinate.
            z: World block Z coordinate.

        Returns:
            True when a tree should be placed.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        value = self._hash_noise(x, z)
        return value > 0.965

    def _octave_noise(self, x: int, z: int, scale: float, octaves: int) -> float:
        """Return layered deterministic value noise.

        Purpose:
            Produces smoother terrain than a single noise sample.

        Args:
            x: World block X coordinate.
            z: World block Z coordinate.
            scale: Frequency multiplier.
            octaves: Number of noise layers.

        Returns:
            Value roughly in the -1..1 range.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(octaves).
        """

        total = 0.0
        amplitude = 1.0
        frequency = scale
        max_value = 0.0
        for _ in range(octaves):
            total += self._noise(x * frequency, z * frequency) * amplitude
            max_value += amplitude
            amplitude *= 0.5
            frequency *= 2.0
        return total / max_value

    def _noise(self, x: float, z: float) -> float:
        """Return deterministic pseudo-noise for a coordinate.

        Purpose:
            Provides dependency-free procedural variation.

        Args:
            x: Scaled X coordinate.
            z: Scaled Z coordinate.

        Returns:
            Floating-point value in the -1..1 range.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        x0 = math.floor(x)
        z0 = math.floor(z)
        tx = self._smoothstep(x - x0)
        tz = self._smoothstep(z - z0)
        a = self._hash_noise(x0, z0)
        b = self._hash_noise(x0 + 1, z0)
        c = self._hash_noise(x0, z0 + 1)
        d = self._hash_noise(x0 + 1, z0 + 1)
        top = self._lerp(a, b, tx)
        bottom = self._lerp(c, d, tx)
        return self._lerp(top, bottom, tz)

    def _hash_noise(self, x: int, z: int) -> float:
        """Return deterministic grid noise for one integer coordinate."""

        value = math.sin(x * 127.1 + z * 311.7 + self.seed * 74.7) * 43758.5453
        return (value - math.floor(value)) * 2.0 - 1.0

    def _smoothstep(self, value: float) -> float:
        """Smooth interpolation curve for value noise."""

        return value * value * (3.0 - 2.0 * value)

    def _lerp(self, a: float, b: float, t: float) -> float:
        """Linearly interpolate between two noise samples."""

        return a + (b - a) * t
