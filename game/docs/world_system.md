# World System

## Design Decisions

`WorldManager` is the central authority for block state. Player, rendering, and
save systems do not mutate chunks directly. This mirrors the future dedicated
server shape: clients submit actions, authority validates, and events describe
accepted changes.

## Responsibilities

```text
WorldManager
|-- read block IDs
|-- place blocks
|-- destroy blocks
|-- emit WorldEvent records
|-- perform raycasts
`-- answer collision queries
```

## Data Flow

```text
Input source:
  PlayerController mouse action

Processing path:
  PlayerController -> WorldManager.place_block/destroy_block -> ChunkManager -> Chunk

State modifications:
  Chunk sparse block dictionary changes only inside WorldManager calls

Event generation:
  WorldManager appends WorldEvent("block_changed", ...)

Rendering updates:
  changed chunk and neighboring boundary chunks are marked render-dirty

Save/load implications:
  changed chunk is marked save-dirty and later flushed by SaveManager
```

## Future Expansion Points

Add validation rules for reach distance, protected areas, liquids, tools, and
inventory costs. In multiplayer, move this manager to the server process.

## Known Limitations

World events are currently consumed locally and not retained in a replay log.
Raycast uses fixed step sampling rather than a grid DDA algorithm.
