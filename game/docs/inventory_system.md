# Inventory System

## Design Decisions

The prototype uses a creative-style hotbar with high stack counts so all block
types can be tested immediately. Inventory is still separate from world logic:
the selected block ID is supplied to `PlayerController`, which asks
`WorldManager` to place it.

## Responsibilities

```text
InventoryManager
|-- hotbar slots
|-- selected index
|-- selected block ID
`-- save/load dictionary
```

## Data Flow

```text
Input source:
  number keys and mouse wheel

Processing path:
  PlayerController binding -> InventoryManager.select/scroll

State modifications:
  selected hotbar index changes

Event generation:
  none yet

Rendering updates:
  RenderManager reads selection for hotbar text

Save/load implications:
  inventory snapshot is embedded in player.json
```

## Future Expansion Points

Add survival counts, item definitions, tools, crafting, stack validation, and
server-authoritative inventory deltas.

## Known Limitations

No item consumption or crafting exists yet.
