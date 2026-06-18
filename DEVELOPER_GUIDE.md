# Developer Guide

## Project Overview

This project is a Minecraft-inspired voxel sandbox built with Python and
Panda3D. It includes first-person movement, mouse look, procedural chunked
terrain, block placement and destruction, a creative hotbar, collision, local
JSON saving, day/night lighting, and face-culled chunk meshes.

No multiplayer, networking, or server code exists yet. The systems are shaped
so a future dedicated server can own world, chunk, inventory, entity, and save
authority while the client keeps rendering, input, UI, and audio.

## Folder Structure

```text
game/
|-- main.py
|-- game_manager.py
|-- docs/
|-- player/       first-person movement, mouse look, block action requests
|-- world/        block registry, world authority, world events
|-- chunks/       chunk storage, serialization, streaming
|-- terrain/      deterministic terrain and biome generation
|-- inventory/    inventory slots and hotbar selection
|-- rendering/    chunk meshing, scene graph, lighting, UI
|-- saving/       JSON world/chunk/player persistence
`-- assets/       future textures, sounds, fonts, and models
```

The current renderer uses vertex colors, so the game runs without texture
assets.

## Installing Dependencies

```powershell
py -m pip install -r requirements.txt
```

## Running The Game

Smoke test without entering the interactive render loop:

```powershell
py game\main.py --smoke-test
```

Run the playable client:

```powershell
py game\main.py
```

Controls:

```text
W/A/S/D      move
Arrow keys   move
Mouse        look
Space        jump
Shift        sprint
Left click   destroy targeted block
Right click  place selected block
1-8 / wheel  select hotbar slot
F5 / F6      decrease / increase render distance
F7 / F8      decrease / increase FOV
F9           toggle camera-relative / world-axis movement
Esc          open / close settings menu
```

## Startup Flow

```text
Command line
  |
  v
main.parse_args()
  |
  v
AppConfig
  |
  v
apply_engine_config()
  |
  v
GameManager
  |
  |-- BlockRegistry
  |-- SaveManager
  |-- TerrainGenerator
  |-- ChunkManager
  |-- WorldManager
  |-- InventoryManager
  |-- PlayerController
  `-- RenderManager
```

## World Generation Flow

```text
Player position
  |
  v
WorldManager.update_streaming()
  |
  v
ChunkManager computes required ChunkCoord values
  |
  v
SaveManager loads saved chunk override if present
  |
  v
TerrainGenerator creates deterministic chunk data if no save exists
  |
  v
RenderManager rebuilds render-dirty chunk meshes
```

## Rendering Flow

```text
Loaded or changed chunk
  |
  v
RenderManager.rebuild_dirty_chunks()
  |
  v
ChunkMesher reads WorldManager and BlockRegistry
  |
  v
Panda3D GeomNode replaces old chunk node
```

Rendering must never modify world data.

## Save/Load Flow

```text
WorldManager changes chunk through set_block()
  |
  v
Chunk dirty_for_save = True
  |
  v
GameManager autosave or close()
  |
  v
SaveManager writes world.json, player.json, and dirty chunk JSON files
```

## How To Add New Blocks

Add new block definitions in `game/world/block_registry.py`. Append new numeric
IDs instead of reusing or reordering existing IDs. Define name, display name,
solidity, transparency, liquid state, and color. Update terrain, inventory, and
documentation when the block becomes usable.

## How To Add New Biomes

Add biome selection and height/surface rules in
`game/terrain/terrain_generator.py`. Biomes must be deterministic from seed and
world coordinate. Keep decoration rules chunk-safe or add cross-chunk
decoration scheduling.

## How To Add New Inventory Items

Add item stacks or a future item registry in `game/inventory`. Player input
should continue to create action requests. Inventory and world authority decide
whether the action is valid.

## Future Multiplayer Integration Guide

Client-side systems:
Rendering, input, camera, UI, audio, prediction, interpolation, and a cache of
server-approved chunks.

Server-side systems:
World authority, inventory authority, chunk authority, entity authority, save
authority, and validation of player actions.

Synchronization requirements:
Chunks must serialize into deterministic payloads, world edits must be emitted
as sequenced events, and player actions must be represented separately from
world logic.
