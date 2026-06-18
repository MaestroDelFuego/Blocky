# Block System

## Design Decisions

Blocks have stable integer IDs in `BlockRegistry`. Saves and future network
messages should use IDs, while names are for tools and documentation.

## Responsibilities

```text
BlockDefinition
|-- id/name/display name
|-- collision flags
|-- transparency/liquid flags
`-- render color

BlockRegistry
|-- lookup by ID
|-- lookup by name
`-- stable default catalog
```

## Data Flow

```text
Input source:
  terrain, inventory, world edits

Processing path:
  block ID -> registry metadata

State modifications:
  registry is immutable after startup

Event generation:
  world events carry old/new block IDs

Rendering updates:
  renderer uses color and transparency metadata

Save/load implications:
  chunks serialize numeric block IDs
```

## Future Expansion Points

Add texture atlas coordinates, tool requirements, hardness, drops, light
emission, fluid behavior, and mod-loaded block definitions.

## Known Limitations

Current rendering uses vertex colors instead of texture assets.
