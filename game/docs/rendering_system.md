# Rendering System

## Design Decisions

Rendering is read-only with respect to world data. `ChunkMesher` builds
face-culled geometry from chunks and neighbor metadata, while `RenderManager`
owns scene graph nodes, UI, and day/night lighting.

## Responsibilities

```text
RenderManager
|-- dirty chunk rebuilds
|-- stale chunk node removal
|-- hotbar text
|-- crosshair
`-- day/night lighting

ChunkMesher
|-- visible face detection
|-- vertex color generation
`-- GeomNode construction
```

## Data Flow

```text
Input source:
  render-dirty chunks and inventory state

Processing path:
  RenderManager -> ChunkMesher -> Panda3D GeomNode

State modifications:
  scene graph nodes change; world chunks do not

Event generation:
  none

Rendering updates:
  dirty chunk nodes are replaced

Save/load implications:
  none; render nodes are disposable client artifacts
```

## Future Expansion Points

Add greedy meshing, texture atlases, transparency sorting, chunk mesh worker
threads, animated water, and richer lighting.

## Known Limitations

The current optimization is face culling rather than full greedy meshing.
