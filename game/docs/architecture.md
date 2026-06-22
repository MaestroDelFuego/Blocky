# Architecture

## Current Stage

The current runnable stage is a complete single-player voxel sandbox prototype.

```text
main.py
  |
  v
GameManager
  |-- BlockRegistry
  |-- SaveManager
  |-- TerrainGenerator
  |-- ChunkManager
  |-- WorldManager
  |-- InventoryManager
  |-- PlayerController
  `-- RenderManager
      `-- ChunkMesher
```

## Design Decisions

`main.py` is intentionally thin. It configures Panda3D and delegates lifecycle
ownership to `GameManager`.

`WorldManager` is the only block mutation authority. Player code emits requests
and rendering code consumes data. This keeps the future dedicated server path
open because canonical world mutation is already separated from client visuals.

Chunks are serializable and store stable integer block IDs. The renderer builds
disposable client meshes from chunk data and never writes world state.

## Responsibilities

```text
AppConfig
  |-- immutable local client startup settings

GameManager
  |-- ShowBase ownership
  |-- client task loop
  |-- system orchestration
  |-- autosave scheduling

WorldManager
  |-- block reads
  |-- block placement/destruction
  |-- world events
  |-- collision/raycast queries

RenderManager
  |-- chunk mesh scene nodes
  |-- hotbar/crosshair UI
  |-- day/night lighting
```

## Data Flow

```text
Input source:
  command line, keyboard, mouse, saved world files

Processing path:
  AppConfig -> GameManager -> systems -> Panda3D task loop

State modifications:
  player transform, chunk maps, dirty flags, save files, scene graph nodes

Event generation:
  WorldManager emits WorldEvent entries for block changes

Rendering updates:
  RenderManager rebuilds dirty chunk meshes and updates UI/lighting

Save/load implications:
  SaveManager writes world metadata, player state, inventory, and dirty chunks
```

## Future Expansion Points

```text
Dedicated server
  |-- owns WorldManager
  |-- owns ChunkManager
  |-- owns InventoryManager
  |-- owns SaveManager
  `-- validates PlayerController action commands

Client
  |-- keeps RenderManager
  |-- keeps local input/UI/audio
  |-- receives world events
  `-- caches server chunk snapshots
```

## Known Limitations

Chunk generation and meshing are synchronous. Blocks use a PNG texture atlas
instead of vertex colors. Face culling is implemented; full greedy meshing is a future
optimization.
