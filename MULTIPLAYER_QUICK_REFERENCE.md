# Multiplayer Quick Reference

## Launching

### Server
```bash
python launch_multiplayer.py --server [--host 0.0.0.0] [--port 9999]
```

### Client
```bash
python launch_multiplayer.py [--host localhost] [--port 9999] [--username Player]
```

## Key Classes & Methods

### Server (`server.py`)

```python
# Start server
server = VoxelSandboxServer(host="0.0.0.0", port=9999)
server.start()

# Server receives player updates and broadcasts to others
# Server validates block changes before broadcasting
```

### Client (`game/networking/client.py`)

```python
# Create client
client = NetworkClient(server_host="localhost", server_port=9999)

# Connect
client.connect(username="Player")

# Send updates
client.send_player_update(position=(x, y, z), rotation=(pitch, yaw), animation="walking")
client.send_block_change(position=(x, y, z), old_block=1, new_block=2)

# Process incoming messages
client.process_messages()

# Set callbacks
client.on_login_success = lambda player_id, spawn: ...
client.on_player_join = lambda id, name, pos: ...
client.on_player_update = lambda id, pos, rot, anim: ...

# Disconnect
client.disconnect()
```

### GameManager Integration

```python
# Initialize with multiplayer
game = GameManager(
    project_root=Path(__file__),
    app_config=config,
    multiplayer=True,
    server_host="localhost",
    server_port=9999,
    username="Player"
)

# Network client automatically:
# - Connects in background thread
# - Sends position updates 5x/sec
# - Handles incoming events
# - Updates remote player rendering
```

### RenderManager Multiplayer

```python
# Add remote player when they join
render_manager.add_remote_player(player_id, username)

# Update remote player position/rotation
render_manager.update_remote_player(player_id, position=(x,y,z), rotation=(pitch,yaw), animation="walking")

# Remove player when they leave
render_manager.remove_remote_player(player_id)
```

## Protocol Messages

### Login
```json
// Client → Server
{
  "type": "login",
  "username": "Alice",
  "protocol_version": 1
}

// Server → Client
{
  "type": "login_success",
  "player_id": "a1b2c3d4",
  "spawn_pos": {"x": 0, "y": 64, "z": 0}
}
```

### Player Update (5x per second)
```json
// Client → Server
{
  "type": "player_update",
  "player_id": "a1b2c3d4",
  "position": {"x": 10.5, "y": 65.0, "z": 5.2},
  "rotation": [0.1, 1.57],
  "animation_state": "walking"
}

// Server broadcasts to other clients
```

### Player Join
```json
// Server → All Other Clients
{
  "type": "player_join",
  "player_id": "b5c6d7e8",
  "username": "Bob",
  "position": {"x": 0, "y": 64, "z": 0}
}
```

### Block Change
```json
// Client → Server
{
  "type": "block_change",
  "position": [100, 64, 100],
  "old_block": 1,
  "new_block": 2,
  "player_id": "a1b2c3d4"
}

// Server broadcasts to all clients
```

## Callbacks

### GameManager Multiplayer Callbacks

```python
# When login succeeds
def _on_network_login_success(self, player_id, spawn_pos):
    print(f"Logged in as {player_id} at {spawn_pos}")

# When another player joins
def _on_remote_player_join(self, player_id, username, position):
    self.render_manager.add_remote_player(player_id, username)

# When another player's position updates
def _on_remote_player_update(self, player_id, position, rotation, animation):
    self.render_manager.update_remote_player(player_id, position, rotation, animation)

# When another player leaves
def _on_remote_player_leave(self, player_id):
    self.render_manager.remove_remote_player(player_id)

# When another player breaks/places a block
def _on_remote_block_change(self, position, old_block, new_block):
    self.world_manager.set_block_direct(position, new_block)
```

## Customization

### Add Custom Message Type

1. Add to `protocol.py`:
```python
class MessageType:
    # ... existing types ...
    CUSTOM_MESSAGE = "custom_message"

@dataclass
class CustomMessage:
    player_id: str
    data: str
    
    def to_json(self):
        return json.dumps({
            "type": MessageType.CUSTOM_MESSAGE,
            "player_id": self.player_id,
            "data": self.data
        })
    
    @staticmethod
    def from_json(data):
        obj = json.loads(data)
        return CustomMessage(obj["player_id"], obj["data"])
```

2. Handle in server (`server.py`):
```python
def _handle_client_message(self, player, message):
    # ... existing handlers ...
    elif message.get("type") == MessageType.CUSTOM_MESSAGE:
        # Process custom message
        pass
```

3. Handle in client (`client.py`):
```python
def _handle_message(self, message):
    # ... existing handlers ...
    elif msg_type == MessageType.CUSTOM_MESSAGE:
        # Process custom message
        pass
```

### Custom Player Model

Replace in `render_manager.py`:
```python
def add_remote_player(self, player_id, username):
    # ... setup node ...
    
    # Load custom model instead of card
    player_model = self.loader.loadModel("models/player.egg")
    player_node.attachChild(player_model)
    
    # Or load from URL/asset
    model_path = self.assets_dir / "models" / f"{username}.egg"
    if model_path.exists():
        model = self.loader.loadModel(str(model_path))
        player_node.attachChild(model)
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Connection refused | Ensure server is running on correct host/port |
| Player models not visible | Check `add_remote_player()` is being called |
| Updates not syncing | Verify `process_messages()` called in game loop |
| Blocks not shared | Ensure server receives and broadcasts `block_change` |
| High latency | Reduce player update frequency or increase network buffer |

## Performance Tips

- **Reduce Bandwidth**: Lower update frequency from 5Hz to 2Hz
- **Improve Responsiveness**: Increase to 10Hz for fast-paced gameplay
- **Optimize Rendering**: Only render players within render distance
- **Batch Updates**: Combine multiple changes into one message

## Testing Checklist

- [ ] Server starts without errors
- [ ] Client connects successfully
- [ ] Login message received
- [ ] Player appears in game
- [ ] Can see other players' positions
- [ ] Block changes propagate
- [ ] Player can disconnect/reconnect
- [ ] Multiple clients can play together

## Files Map

```
Root/
├── server.py                    ← Dedicated server entry point
├── launch_multiplayer.py        ← Launcher script
├── MULTIPLAYER.md               ← Full documentation
├── MULTIPLAYER_IMPLEMENTATION.md ← Implementation summary
├── game/
│   ├── networking/
│   │   ├── protocol.py          ← Message definitions
│   │   ├── client.py            ← Client implementation
│   │   └── __init__.py
│   ├── game_manager.py          ← Multiplayer integration
│   ├── player/
│   │   └── player_controller.py ← get_rotation() added
│   └── rendering/
│       └── render_manager.py    ← Remote player rendering
└── ...
```

## Common Tasks

### Connect to Multiplayer Game
```python
game = GameManager(project_root, config, multiplayer=True,
                   server_host="192.168.1.100", username="Player")
game.run()
```

### Add New Player Callback
```python
network_client.on_custom_event = lambda data: handle_custom_event(data)
```

### Send Block Change
```python
network_client.send_block_change(
    position=(100, 64, 100),
    old_block=1,
    new_block=2
)
```

### Render New Remote Player
```python
render_manager.add_remote_player("player_id", "PlayerName")
```

---

**Version**: 1.0  
**Last Updated**: 2026-06-22
