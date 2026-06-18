# Player System

## Design Decisions

`PlayerController` owns local input, camera, movement, collision checks, and
block action requests. It does not mutate chunks directly.

## Responsibilities

```text
PlayerController
|-- WASD movement
|-- mouse-look camera
|-- jump/gravity
|-- AABB collision checks
|-- block raycast actions
`-- player state serialization
```

## Data Flow

```text
Input source:
  keyboard and mouse

Processing path:
  Panda3D events -> PlayerController -> WorldManager action request

State modifications:
  local player transform changes; world changes only through WorldManager

Event generation:
  WorldManager emits block events after accepted actions

Rendering updates:
  camera transform follows player; dirty chunk meshes update after edits

Save/load implications:
  player position, yaw, pitch, and inventory are saved in player.json
```

## Future Expansion Points

Add swimming, flying, sprint stamina, configurable controls, entity collision,
and multiplayer prediction/correction.

## Known Limitations

Collision is simple axis-separated AABB collision.
