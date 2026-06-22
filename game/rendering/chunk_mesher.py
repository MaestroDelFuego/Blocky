"""File: chunk_mesher.py
...
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
    def __init__(self, block_registry: BlockRegistry, world_manager: WorldManager) -> None:
        self.blocks = block_registry
        self.world = world_manager

    def build(self, chunk: Chunk) -> dict[int, GeomNode]:
        fmt = GeomVertexFormat.getV3c4t2()
        base_x = chunk.coord.x * CHUNK_SIZE
        base_z = chunk.coord.z * CHUNK_SIZE

        blocks = self.blocks
        world_get_block = self.world.get_block
        air = BlockRegistry.AIR

        # ---- Snapshot chunk into a local dict; avoids touching chunk internals ----
        local = {}
        y_min = y_max = None
        for (lx, y, lz), block_id in chunk.iter_blocks():
            if block_id == air:
                continue
            local[(lx, y, lz)] = block_id
            if y_min is None or y < y_min:
                y_min = y
            if y_max is None or y > y_max:
                y_max = y

        if not local:
            return {}

        buckets: dict[int, dict[str, object]] = {}

        def get_bucket(block_id: int) -> dict[str, object]:
            bucket = buckets.get(block_id)
            if bucket is None:
                data = GeomVertexData(f"chunk-{chunk.coord.x}-{chunk.coord.z}-{block_id}", fmt, Geom.UHStatic)
                bucket = {
                    "data": data,
                    "vertex": GeomVertexWriter(data, "vertex"),
                    "color": GeomVertexWriter(data, "color"),
                    "texcoord": GeomVertexWriter(data, "texcoord"),
                    "triangles": GeomTriangles(Geom.UHStatic),
                    "vertex_count": 0,
                }
                buckets[block_id] = bucket
            return bucket

        def get_local(x, y, z):
            if 0 <= x < CHUNK_SIZE and 0 <= z < CHUNK_SIZE:
                return local.get((x, y, z), air)
            return world_get_block(base_x + x, y, base_z + z)

        def face_visible(x, y, z, block_id, transparent_block, normal):
            # WATER SPECIAL CASE: only render top surface
            if block_id == BlockRegistry.WATER:
                return normal == (0, 1, 0)

            nx, ny, nz = x + normal[0], y + normal[1], z + normal[2]
            neighbor_id = get_local(nx, ny, nz)

            if neighbor_id == air:
                return True

            neighbor = blocks.get(neighbor_id)
            if neighbor and not neighbor.transparent and not transparent_block:
                return False

            return True

        # Per-normal: which two axes vary across the face plane (u, v), and how
        # (depth, u, v) maps back to actual (x, y, z), plus the winding-correct
        # corner template using lo/hi placeholders matching FACE_DEFINITIONS.
        def x_coord(depth, u, v):
            return depth, u, v

        def y_coord(depth, u, v):
            return u, depth, v

        def z_coord(depth, u, v):
            return u, v, depth

        def x_corners(xf, u0, u1, v0, v1, positive):
            if positive:
                return ((xf, u0, v0), (xf, u1, v0), (xf, u1, v1), (xf, u0, v1))
            return ((xf, u0, v1), (xf, u1, v1), (xf, u1, v0), (xf, u0, v0))

        def y_corners(yf, u0, u1, v0, v1, positive):
            return ((u0, yf, v0), (u1, yf, v0), (u1, yf, v1), (u0, yf, v1))

        def z_corners(zf, u0, u1, v0, v1, positive):
            if positive:
                return ((u1, v0, zf), (u1, v1, zf), (u0, v1, zf), (u0, v0, zf))
            return ((u0, v0, zf), (u0, v1, zf), (u1, v1, zf), (u1, v0, zf))

        face_plans = {
            (1, 0, 0): (range(0, CHUNK_SIZE), range(y_min, y_max + 1), range(0, CHUNK_SIZE), x_coord, x_corners, True),
            (-1, 0, 0): (range(0, CHUNK_SIZE), range(y_min, y_max + 1), range(0, CHUNK_SIZE), x_coord, x_corners, False),
            (0, 1, 0): (range(y_min, y_max + 1), range(0, CHUNK_SIZE), range(0, CHUNK_SIZE), y_coord, y_corners, True),
            (0, -1, 0): (range(y_min, y_max + 1), range(0, CHUNK_SIZE), range(0, CHUNK_SIZE), y_coord, y_corners, False),
            (0, 0, 1): (range(0, CHUNK_SIZE), range(0, CHUNK_SIZE), range(y_min, y_max + 1), z_coord, z_corners, True),
            (0, 0, -1): (range(0, CHUNK_SIZE), range(0, CHUNK_SIZE), range(y_min, y_max + 1), z_coord, z_corners, False),
        }

        for normal, _unused_corners in FACE_DEFINITIONS:
            depth_range, u_range, v_range, coord_fn, corner_fn, positive = face_plans[normal]
            brightness = self._face_brightness(normal)
            u_list = list(u_range)
            v_list = list(v_range)
            u_count = len(u_list)
            v_count = len(v_list)

            for depth in depth_range:
                mask = [[None] * v_count for _ in range(u_count)]
                any_visible = False

                for ui, u in enumerate(u_list):
                    for vi, v in enumerate(v_list):
                        x, y, z = coord_fn(depth, u, v)
                        block_id = local.get((x, y, z), air)
                        if block_id == air:
                            continue
                        block = blocks.get(block_id)
                        if not block:
                            continue
                        if not face_visible(x, y, z, block_id, block.transparent, normal):
                            continue
                        mask[ui][vi] = block_id
                        any_visible = True

                if not any_visible:
                    continue

                done = [[False] * v_count for _ in range(u_count)]
                for ui in range(u_count):
                    for vi in range(v_count):
                        if done[ui][vi] or mask[ui][vi] is None:
                            continue
                        key = mask[ui][vi]

                        w = 1
                        while vi + w < v_count and not done[ui][vi + w] and mask[ui][vi + w] == key:
                            w += 1

                        h = 1
                        growing = True
                        while ui + h < u_count and growing:
                            for k in range(w):
                                if done[ui + h][vi + k] or mask[ui + h][vi + k] != key:
                                    growing = False
                                    break
                            if growing:
                                h += 1

                        for du in range(h):
                            for dv in range(w):
                                done[ui + du][vi + dv] = True

                        u0, u1 = u_list[ui], u_list[ui + h - 1] + 1
                        v0, v1 = v_list[vi], v_list[vi + w - 1] + 1
                        depth_face = depth + 1 if positive else depth
                        texcoords = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))

                        block = blocks.get(key)
                        r = block.color[0] * brightness
                        g = block.color[1] * brightness
                        b = block.color[2] * brightness
                        a = block.color[3]

                        bucket = get_bucket(key)
                        vertex = bucket["vertex"]
                        color = bucket["color"]
                        texcoord = bucket["texcoord"]
                        triangles = bucket["triangles"]
                        vertex_count = int(bucket["vertex_count"])

                        for (cx, cy, cz), (tu, tv) in zip(corner_fn(depth_face, u0, u1, v0, v1, positive), texcoords):
                            vertex.addData3(base_x + cx, base_z + cz, cy)
                            color.addData4(r, g, b, a)
                            texcoord.addData2(tu, tv)

                        triangles.addVertices(vertex_count, vertex_count + 1, vertex_count + 2)
                        triangles.addVertices(vertex_count, vertex_count + 2, vertex_count + 3)
                        bucket["vertex_count"] = vertex_count + 4

        nodes: dict[int, GeomNode] = {}
        for block_id, bucket in buckets.items():
            vertex_count = int(bucket["vertex_count"])
            if not vertex_count:
                continue
            data = bucket["data"]
            triangles = bucket["triangles"]
            geom = Geom(data)
            geom.addPrimitive(triangles)
            node = GeomNode(f"chunk-{chunk.coord.x}-{chunk.coord.z}-{block_id}")
            node.addGeom(geom)
            nodes[block_id] = node
        return nodes

    def _face_brightness(self, normal: tuple[int, int, int]) -> float:
        if normal == (0, 1, 0):
            return 1.0
        if normal == (0, -1, 0):
            return 0.48
        if normal[0] != 0:
            return 0.74
        return 0.62