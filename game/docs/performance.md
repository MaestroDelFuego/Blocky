# Performance

## Current Costs

```text
Chunk generation:
  O(16 * 16 * terrain_height)

Chunk loading window:
  O(radius^2) chunks checked per streaming update

Mesh generation:
  O(non_air_blocks * 6 faces)

Collision query:
  O(block cells overlapped by player AABB)

Raycast:
  O(max_distance / step)

Save dirty chunks:
  O(dirty_chunks * non_air_blocks_per_chunk)
```

## Design Decisions

Sparse chunk storage reduces memory in air-heavy worlds. Face culling avoids
rendering faces hidden by neighboring opaque blocks. Render rebuilds only happen
for chunks marked dirty.

## Memory Complexity

Loaded world memory is roughly:

```text
O(loaded_chunks * non_air_blocks_per_chunk)
```

Render memory is roughly:

```text
O(visible_faces)
```

## Future Expansion Points

Move chunk generation and mesh generation to worker queues, add greedy meshing,
compress chunk storage, batch saves, and reduce streaming checks to only when
the player crosses chunk boundaries.

## Known Limitations

Generation and meshing are synchronous. Face culling is good enough for a
prototype but less efficient than greedy meshing.
