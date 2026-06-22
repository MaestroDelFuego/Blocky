"""Block texture atlas helpers.

This module keeps the mesh code focused on geometry while centralizing the
atlas layout and asset path used by the block renderer.
"""

from __future__ import annotations

from math import ceil, sqrt
from pathlib import Path

from world.block_registry import BlockRegistry


class BlockTextureAtlas:
    """Describe the shared block texture atlas."""

    def __init__(self, block_registry: BlockRegistry, assets_dir: Path) -> None:
        self.assets_dir = Path(assets_dir)
        self.atlas_path = self.assets_dir / "block_atlas.png"
        self.columns, self.rows = self._grid_size(block_registry)
        self.tile_size = 16
        self.atlas_width = self.columns * self.tile_size
        self.atlas_height = self.rows * self.tile_size
        self.uv_by_id = self._build_uv_map(block_registry)

    def _grid_size(self, block_registry: BlockRegistry) -> tuple[int, int]:
        block_count = sum(1 for block in block_registry.all_blocks() if block.id != BlockRegistry.AIR)
        columns = max(1, ceil(sqrt(block_count)))
        rows = max(1, ceil(block_count / columns))
        return columns, rows

    def _build_uv_map(self, block_registry: BlockRegistry) -> dict[int, tuple[float, float, float, float]]:
        uv_by_id: dict[int, tuple[float, float, float, float]] = {}
        columns, rows = self.columns, self.rows
        texture_index = 0

        for block in block_registry.all_blocks():
            if block.id == BlockRegistry.AIR:
                continue

            column = texture_index % columns
            row = texture_index // columns

            left = column * self.tile_size
            top = row * self.tile_size

            u0 = (left + 0.5) / self.atlas_width
            v0 = (top + 0.5) / self.atlas_height
            u1 = ((left + self.tile_size) - 0.5) / self.atlas_width
            v1 = ((top + self.tile_size) - 0.5) / self.atlas_height

            uv_by_id[block.id] = (u0, v0, u1, v1)
            texture_index += 1

        return uv_by_id

    def get_uv(self, block_id: int) -> tuple[float, float, float, float]:
        return self.uv_by_id[block_id]