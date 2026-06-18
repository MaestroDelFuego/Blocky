# Chunk System

## Design Decisions

Chunks are 16x16x256 columns addressed by `ChunkCoord`. Storage is sparse:
only non-air blocks are stored. This keeps memory lower for air-heavy terrain
and makes JSON saves compact enough for this prototype.

## Responsibilities

```text
Chunk
|-- local block storage
|-- dirty render/save flags
`-- JSON-compatible serialization

ChunkManager
|-- load radius tracking
|-- saved chunk loading
|-- procedural fallback generation
`-- dirty chunk saving
```

## Data Flow

```text
Input source:
  player position

Processing path:
  WorldManager.update_streaming -> ChunkManager.update_around

State modifications:
  load new required chunks, unload distant chunks after save

Event generation:
  chunk load flags produce render-dirty chunks

Rendering updates:
  RenderManager rebuilds dirty loaded chunks

Save/load implications:
  SaveManager loads chunk overrides before TerrainGenerator runs
```

## Future Expansion Points

Generation and meshing can be moved to worker queues. Chunk payloads can be
compressed or binary-encoded later without changing the authoritative API.

## Known Limitations

Chunk loading is synchronous. Large load radii can stall the frame.
