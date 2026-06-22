# Multiplayer Setup & Guide

## Quick Start

### 1. Start Dedicated Server

```bash
# On the server machine
python launch_multiplayer.py --server

# Output:
# 🌐 Voxel Sandbox Server started on 0.0.0.0:9999
```

### 2. Connect Client(s)

```bash
# On each client machine (or same machine for testing)
python launch_multiplayer.py --username YourPlayerName

# For remote server:
python launch_multiplayer.py --host 192.168.1.100 --port 9999 --username YourPlayerName
```

## Architecture

### Network Protocol

- **Transport**: TCP/IP with JSON messages
- **Message Types**:
  - `login` / `login_success` - Player authentication
  - `player_update` - Position, rotation, animation state (sent ~5x/second)
  - `player_join` / `player_leave` - Player lifecycle events
  - `block_change` - World modifications
  - `player_list` - Initial player state sync

### Server (`server.py`)

- **Role**: Authoritative world state + player management
- **Port**: 9999 (default)
- **Features**:
  - Multi-threaded connection handling
  - Server-side world validation
  - Player state synchronization
  - Block change broadcasting

**File Structure**:
```
game/networking/
├── protocol.py      # Message definitions & serialization
├── client.py        # Client-side networking
└── __init__.py

server.py           # Dedicated server (root level)
```

### Client (`networking/client.py`)

- **Role**: Connect to server, send input, render remote players
- **Features**:
  - Automatic reconnection with exponential backoff
  - Thread-safe message queuing
  - Callback-based event handling
  - Remote player state caching

**Integration Points**:
1. `GameManager` - Initializes network client + handles multiplayer lifecycle
2. `PlayerController` - Sends position/rotation updates via `get_rotation()`
3. `RenderManager` - Renders remote players, updates player labels

## Player Rendering

### Remote Player Models

Each remote player is rendered as a **simple card-based model** that can be customized:

```python
# Current: Simple card with optional player skin texture
skin_path = assets_dir / "items" / f"{username}_skin.png"
```

### To Customize Player Models:

1. **Add Skin Texture** (optional):
   - Create PNG file: `game/assets/items/{username}_skin.png`
   - Size: 64x128 pixels recommended (Minecraft-style)
   - Automatic loading if file exists

2. **Replace with Full Model**:
   - Modify `RenderManager.add_remote_player()` to load `.egg` or `.glb` models
   - Example:
     ```python
     player_model = self.loader.loadModel("models/player.egg")
     player_node.attachChild(player_model)
     ```

## Network Flow

### Player Join

```
Client A                    Server                      Client B
  |                           |                            |
  | -------- login ----------> |                            |
  |                           | -- player_join ---------> |
  | <-- login_success --------|                            |
  | <-- player_list --------- |                            |
  |                           | -- player_join ---------> |
  | ----- player_update ----> | -- player_update -------> |
```

### Real-time Updates

```
Client A                    Server                      Client B
  | ----- player_update ----> |                            |
  |                           | -- player_update -------> |
  | ----- block_change -----> | -- block_change -------> |
  |                           |                            |
  | <-- player_update ------- | <-- player_update ------- |
```

## Configuration

### Command Line Arguments

```bash
python launch_multiplayer.py --help

Options:
  --server              Launch as dedicated server
  --host HOST          Server host (client: localhost, server: 0.0.0.0)
  --port PORT          Port number (default: 9999)
  -u, --username NAME  Player username (default: Player)
```

### Programmatic Setup

```python
from game.game_manager import GameManager, AppConfig
from pathlib import Path

config = AppConfig()
game = GameManager(
    project_root=Path(__file__),
    app_config=config,
    multiplayer=True,
    server_host="localhost",
    server_port=9999,
    username="MyPlayer"
)
game.run()
```

## Development Notes

### Extending the Protocol

Add new message type to `networking/protocol.py`:

```python
@dataclass
class CustomMessage:
    player_id: str
    data: str
    
    def to_json(self) -> str:
        return json.dumps({
            "type": MessageType.CUSTOM,
            "player_id": self.player_id,
            "data": self.data
        })
    
    @staticmethod
    def from_json(data: str) -> CustomMessage:
        obj = json.loads(data)
        return CustomMessage(obj["player_id"], obj["data"])
```

### Performance Optimization

- **Position Updates**: Currently sent at 5Hz. Increase frequency or use prediction for smoother motion
- **LOD (Level of Detail)**: Only sync players within render distance
- **Message Batching**: Combine multiple block changes into `block_changes` message
- **Compression**: Consider MessagePack or Protocol Buffers for larger worlds

### Known Limitations

1. **No Authentication**: Players aren't persisted; anyone can join
2. **No Encryption**: Messages sent in plaintext (add TLS for production)
3. **Simple Physics**: No server-side collision validation yet
4. **No Persistence**: Server doesn't save player/world state between restarts

### Future Improvements

- [ ] Player skins / full 3D models
- [ ] Voice chat integration
- [ ] Chunk streaming optimization
- [ ] Lag compensation / prediction
- [ ] Player accounts & persistence
- [ ] Admin commands & moderation
- [ ] Plugin system for server extensions
- [ ] Dedicated world save/load

## Troubleshooting

### "Connection refused"

Server isn't running or wrong host/port. Verify:
```bash
# Test server is listening
netstat -an | grep 9999  # Windows/Linux
```

### Players don't see each other

Check network connectivity:
```bash
# Ping server
ping localhost  # for local testing
ping <server_ip>  # for remote
```

### Slow/Laggy multiplayer

- Reduce `--render-distance` to lower bandwidth
- Increase `--fov` to improve performance
- Check network latency: `ping <server>`
- Monitor server CPU/memory usage

## Architecture Diagrams

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Game Server                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  VoxelSandboxServer                                  │  │
│  │  ├─ WorldManager (authoritative)                    │  │
│  │  ├─ ChunkManager                                    │  │
│  │  ├─ ServerPlayer[]: connection & state              │  │
│  │  └─ Message broadcast system                        │  │
│  └──────────────────────────────────────────────────────┘  │
│           ▲                          ▲                      │
│           │ (TCP/JSON)               │ (TCP/JSON)           │
│           │                          │                      │
└───────────┼──────────────────────────┼──────────────────────┘
            │                          │
    ┌───────┴──────────┐       ┌──────┴────────────┐
    │  Client A        │       │  Client B        │
    │ ┌──────────────┐ │       │ ┌──────────────┐ │
    │ │ NetworkClient│ │       │ │ NetworkClient│ │
    │ ├──────────────┤ │       │ ├──────────────┤ │
    │ │ GameManager  │ │       │ │ GameManager  │ │
    │ │ PlayerCtrl   │ │       │ │ PlayerCtrl   │ │
    │ │ RenderMgr    │ │       │ │ RenderMgr    │ │
    │ └──────────────┘ │       │ └──────────────┘ │
    └──────────────────┘       └──────────────────┘
```

## Example Gameplay Flow

1. **Server starts**
   ```bash
   $ python launch_multiplayer.py --server
   🌐 Voxel Sandbox Server started on 0.0.0.0:9999
   ```

2. **Alice joins**
   ```bash
   $ python launch_multiplayer.py --username Alice
   🎮 Starting Voxel Sandbox Client...
   🌐 Connecting to localhost:9999...
   ✅ Logged in as Alice (ID: a1b2c3d4)
   ```

3. **Bob joins**
   ```bash
   $ python launch_multiplayer.py --username Bob
   👋 Alice joined the game  # Alice sees this
   ✅ Logged in as Bob (ID: e5f6g7h8)
   ```

4. **Bob places a block**
   - Bob places dirt block at (100, 64, 100)
   - Server receives `block_change` message
   - Server broadcasts to all clients (including Alice)
   - Alice sees dirt block appear at that location

5. **Alice moves closer to Bob**
   - Alice's client sends position update to server every 0.2s
   - Server forwards Alice's position to Bob
   - Bob sees Alice's player model move in real-time

6. **Alice and Bob both disconnect**
   - Alice closes game → server receives disconnect
   - Server broadcasts `player_leave` to Bob
   - Bob sees "Alice left the game"
