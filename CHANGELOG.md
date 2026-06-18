# Changelog

All generated files and architecture decisions are recorded here so future
maintainers can understand why each system exists.

## 2026-06-18

### Created `game/main.py`

Purpose:
Local Panda3D client entry point.

Dependencies added:
`argparse`, `dataclasses`, `pathlib`, `panda3d.core.loadPrcFileData`, and
`game_manager.GameManager`.

Architectural decisions:
Startup configuration is immutable and applied before `ShowBase` construction.
The file stays client-only so a future dedicated server can use a separate
entry point without importing rendering systems.

### Created `game/game_manager.py`

Purpose:
Top-level Panda3D client lifecycle manager.

Dependencies added:
`direct.showbase.ShowBase.ShowBase` and `panda3d.core.ClockObject`.

Architectural decisions:
`GameManager` owns the client shell and update loop, but does not own canonical
world state. Future block edits must flow through `WorldManager`, and future
rendering code must consume world events rather than modifying chunk data.

### Created `requirements.txt`

Purpose:
Declares the Panda3D runtime dependency needed to run the local client.

Dependencies added:
`panda3d>=1.10.15`.

Architectural decisions:
Runtime dependencies are kept explicit at the project root so setup,
automation, and future packaging scripts all use the same source of truth.

### Created system package directories

Files created:
`game/player/__init__.py`, `game/world/__init__.py`,
`game/chunks/__init__.py`, `game/terrain/__init__.py`,
`game/inventory/__init__.py`, `game/rendering/__init__.py`,
`game/saving/__init__.py`, and `game/assets/.gitkeep`.

Purpose:
Establish the requested project structure and document subsystem boundaries
before implementation begins.

Dependencies added:
None.

Architectural decisions:
Package docstrings state the future ownership rules up front. World mutation
will be centralized in `WorldManager`; rendering will consume snapshots/events;
player code will emit action requests instead of modifying blocks directly.

### Created complete single-player voxel game stack

Files created:
`game/world/block_registry.py`, `game/chunks/chunk.py`,
`game/chunks/chunk_manager.py`, `game/terrain/terrain_generator.py`,
`game/world/world_manager.py`, `game/saving/save_manager.py`,
`game/inventory/inventory_manager.py`, `game/player/player_controller.py`,
`game/rendering/chunk_mesher.py`, and `game/rendering/render_manager.py`.

Purpose:
Implements a playable Panda3D voxel sandbox with first-person movement,
mouse-look, infinite deterministic chunk streaming, terrain biomes, block
placement/destruction, inventory/hotbar, collision, JSON save/load, day/night
lighting, and face-culled chunk meshes.

Dependencies added:
Panda3D scene graph, geometry, lighting, and UI APIs; Python `json`, `math`,
`pathlib`, and `dataclasses`.

Architectural decisions:
All block mutations pass through `WorldManager`. Chunks are serializable and
store stable block IDs. Rendering consumes world state but never mutates it.
Player code emits placement/destruction requests rather than editing chunks.
The save system is local single-player only and should move server-side when a
dedicated server is introduced.
