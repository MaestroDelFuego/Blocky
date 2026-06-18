# Terrain Generation

## Design Decisions

`TerrainGenerator` is deterministic from seed and world coordinate. It uses
dependency-free math noise so the project can run offline without extra
packages.

## Responsibilities

```text
TerrainGenerator
|-- biome selection
|-- height calculation
|-- terrain layer fill
|-- water fill
`-- simple forest trees
```

## Data Flow

```text
Input source:
  ChunkManager requests ChunkCoord

Processing path:
  generate_chunk -> get_biome/get_height -> fill columns

State modifications:
  returned Chunk receives generated non-air blocks

Event generation:
  no world events; generation is initial state

Rendering updates:
  generated chunk starts render-dirty

Save/load implications:
  saved chunks override procedural generation
```

## Future Expansion Points

Replace math noise with a higher-quality noise function, add caves, ores,
structures, rivers, and biome data tables.

## Known Limitations

Tree leaves do not cross chunk boundaries. Noise is simple and not as smooth as
Perlin/OpenSimplex.
