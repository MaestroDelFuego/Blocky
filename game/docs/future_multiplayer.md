# Future Multiplayer

## Current Rule

No multiplayer, networking, or server code exists in this project yet.

## Dedicated Server Responsibilities

```text
Dedicated Server
|-- WorldManager authority
|-- ChunkManager authority
|-- SaveManager authority
|-- InventoryManager authority
|-- entity authority
`-- validation of player action requests
```

## Client Responsibilities

```text
Client
|-- rendering
|-- input collection
|-- UI
|-- audio
|-- prediction/interpolation
`-- local cache of server-approved chunks/events
```

## System Transitions

`WorldManager` moves to server authority. Clients send block action requests and
receive accepted `WorldEvent` deltas.

`ChunkManager` becomes server-owned for canonical chunks. Clients cache chunks
received from the server.

`SaveManager` moves to the server. Clients keep only local settings.

`InventoryManager` becomes server-authoritative for counts and validation. The
client renders snapshots.

`RenderManager` stays client-only and consumes snapshots/events.

`PlayerController` becomes a command producer and prediction layer.

## Synchronization Requirements

Chunk payloads need versioning, compression, and checksums. World events need
sequence numbers. Player actions need timestamps or tick IDs.

## Known Limitations

The current single-player save format lacks protocol version fields and should
be migrated before networked worlds are introduced.
