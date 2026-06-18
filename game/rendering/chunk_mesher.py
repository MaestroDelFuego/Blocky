"""File: chunk_mesher.py

Purpose:
    Builds face-culled Panda3D geometry for voxel chunks.

Responsibilities:
    * Inspect chunk block data without modifying it.
    * Skip hidden faces between opaque blocks.
    * Emit colored vertex geometry for visible block faces.
    * Keep mesh generation independent from scene graph ownership.

Dependencies:
    * panda3d.core geometry classes.
    * chunks.chunk for chunk constants and data.
    * world.block_registry for render/culling metadata.
    * world.world_manager for neighboring block reads.

Systems that depend on it:
    * RenderManager uses ChunkMesher to rebuild dirty chunk nodes.

Future multiplayer considerations:
    This remains client-only. It consumes chunk snapshots/events and never owns
    authoritative block data.
"""

from __future__ import annotations

from panda3d.core import Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat, GeomVertexWriter

from chunks.chunk import CHUNK_SIZE, Chunk
from world.block_registry import BlockRegistry
from world.world_manager import WorldManager


FACE_DEFINITIONS = (
    ((1, 0, 0), ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))),
    ((-1, 0, 0), ((0, 0, 1), (0, 1, 1), (0, 1, 0), (0, 0, 0))),
    ((0, 1, 0), ((0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1))),
    ((0, -1, 0), ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1))),
    ((0, 0, 1), ((1, 0, 1), (1, 1, 1), (0, 1, 1), (0, 0, 1))),
    ((0, 0, -1), ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0))),
)


class ChunkMesher:
    """Builds render geometry from chunk data.

    Purpose:
        Converts block IDs into visible mesh faces.

    Responsibilities:
        * Read world block neighbors for face culling.
        * Generate Panda3D GeomNode instances.
        * Apply per-block colors and simple face brightness.

    Lifecycle:
        Constructed once by RenderManager and reused for dirty chunks.

    Dependencies:
        Depends on BlockRegistry and WorldManager read APIs.

    Threading considerations:
        Currently runs on the main thread. Future worker mesh building should
        operate on immutable chunk snapshots, not live Chunk objects.

    Future networking considerations:
        Meshes are client artifacts and must never be serialized as world state.
    """

    def __init__(self, block_registry: BlockRegistry, world_manager: WorldManager) -> None:
        """Create a chunk mesher.

        Purpose:
            Stores registry and world references used for culling.

        Args:
            block_registry: Block metadata registry.
            world_manager: Read-only world access facade.

        Returns:
            None.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        self.blocks = block_registry
        self.world = world_manager

    def build(self, chunk: Chunk) -> GeomNode:
        """Build a GeomNode for one chunk.

        Purpose:
            Generates visible voxel faces for rendering.

        Args:
            chunk: Chunk to mesh.

        Returns:
            Panda3D GeomNode.

        Side Effects:
            None. The chunk is read but not mutated.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(b * f), where b is non-air block count and f is six faces.
        """

        fmt = GeomVertexFormat.getV3c4()
        data = GeomVertexData(f"chunk-{chunk.coord.x}-{chunk.coord.z}", fmt, Geom.UHStatic)
        vertex = GeomVertexWriter(data, "vertex")
        color = GeomVertexWriter(data, "color")
        triangles = GeomTriangles(Geom.UHStatic)
        vertex_count = 0

        base_x = chunk.coord.x * CHUNK_SIZE
        base_z = chunk.coord.z * CHUNK_SIZE

        for (local_x, y, local_z), block_id in chunk.iter_blocks():
            block = self.blocks.get(block_id)
            if block_id == BlockRegistry.AIR:
                continue
            world_x = base_x + local_x
            world_z = base_z + local_z
            for normal, corners in FACE_DEFINITIONS:
                neighbor_id = self.world.get_block(world_x + normal[0], y + normal[1], world_z + normal[2])
                neighbor = self.blocks.get(neighbor_id)
                if neighbor_id != BlockRegistry.AIR and not neighbor.transparent and not block.transparent:
                    continue
                brightness = self._face_brightness(normal)
                face_color = (
                    block.color[0] * brightness,
                    block.color[1] * brightness,
                    block.color[2] * brightness,
                    block.color[3],
                )
                for corner in corners:
                    # Game simulation uses Y as height; Panda3D uses Z as height.
                    vertex.addData3(world_x + corner[0], world_z + corner[2], y + corner[1])
                    color.addData4(*face_color)
                triangles.addVertices(vertex_count, vertex_count + 1, vertex_count + 2)
                triangles.addVertices(vertex_count, vertex_count + 2, vertex_count + 3)
                vertex_count += 4

        geom = Geom(data)
        geom.addPrimitive(triangles)
        node = GeomNode(f"chunk-{chunk.coord.x}-{chunk.coord.z}")
        if vertex_count:
            node.addGeom(geom)
        return node

    def _face_brightness(self, normal: tuple[int, int, int]) -> float:
        """Return simple brightness for a face normal.

        Purpose:
            Adds readable depth without a texture pack.

        Args:
            normal: Integer face normal.

        Returns:
            Brightness multiplier.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        if normal == (0, 1, 0):
            return 1.0
        if normal == (0, -1, 0):
            return 0.48
        if normal[0] != 0:
            return 0.74
        return 0.62
