# Save System

## Design Decisions

Saves use plain JSON to keep the format inspectable during early development.
Chunks serialize as coordinate plus non-air local block entries.

## Responsibilities

```text
SaveManager
|-- world metadata
|-- chunk JSON files
|-- player state
`-- inventory snapshot inside player state
```

## Data Flow

```text
Input source:
  dirty chunks, player transform, inventory state, time of day

Processing path:
  GameManager.save_game -> SaveManager

State modifications:
  files in saves/default_world are written

Event generation:
  none

Rendering updates:
  none

Save/load implications:
  saved chunks override procedural chunks on future loads
```

## Future Expansion Points

Add version fields, migrations, compression, atomic writes, backup rotation,
and background save queues.

## Known Limitations

Saves are synchronous and can stall if many dirty chunks are flushed at once.
