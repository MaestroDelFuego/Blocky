"""File: game_manager.py

Purpose:
    Top-level coordinator for the local Panda3D client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from direct.showbase.ShowBase import ShowBase
from panda3d.core import ClockObject, WindowProperties

from chunks.chunk_manager import ChunkManager
from inventory.inventory_manager import InventoryManager
from player.player_controller import PlayerController
from rendering.render_manager import RenderManager
from saving.save_manager import SaveManager
from terrain.terrain_generator import TerrainGenerator
from world.block_registry import BlockRegistry
from world.world_manager import WorldManager
from chunks.chunk import ChunkCoord
from networking.client import NetworkClient
from networking.protocol import Vector3


class GameManager(ShowBase):

    TERRAIN_VERSION = 3
    MIN_RENDER_DISTANCE = 1
    MAX_RENDER_DISTANCE = 128
    MAX_EFFECTIVE_RENDER_DISTANCE = 16

    def __init__(self, project_root: Path, app_config: Any, multiplayer: bool = False, 
                 server_host: str = "localhost", server_port: int = 9999, username: str = "Player") -> None:
        super().__init__()

        self.project_root = Path(project_root)
        self.app_config = app_config
        self.multiplayer = multiplayer
        self.server_host = server_host
        self.server_port = server_port
        self.username = username

        self.elapsed_time = 0.0
        self.autosave_timer = 0.0
        self.is_shutting_down = False
        self.network_client: NetworkClient | None = None
        self.network_update_timer = 0.0

        self.render_distance = 2
        self.fov = 120.0
        self.camera_relative_movement = True
        self.settings_menu_open = False
        self._last_streamed_chunk: ChunkCoord | None = None

        self.disableMouse()
        self.setBackgroundColor(0.54, 0.73, 0.94, 1.0)

        self._create_systems()

        self.taskMgr.add(self.update, "game-manager-update")

    def _create_systems(self) -> None:

        self.block_registry = BlockRegistry()

        self.save_manager = SaveManager(self.project_root.parent / "saves")
        self.save_manager.terrain_version = self.TERRAIN_VERSION

        self.world_metadata = self.save_manager.load_metadata(default_seed=1337)

        if int(self.world_metadata.get("terrain_version", 1)) < self.TERRAIN_VERSION:
            self.world_metadata["terrain_version"] = self.TERRAIN_VERSION

        self._load_settings()
        self._apply_fov()
        self._sync_effective_render_distance()

        self.terrain_generator = TerrainGenerator(
            int(self.world_metadata["seed"]),
            self.block_registry
        )

        self.chunk_manager = ChunkManager(
            self.terrain_generator,
            self.save_manager,
            load_radius=self._effective_render_distance
        )

        self.world_manager = WorldManager(self.chunk_manager, self.block_registry)
        self.inventory_manager = InventoryManager(self.block_registry)

        self.player_controller = PlayerController(
            self,
            self.world_manager,
            self.inventory_manager,
            network_client=None  # Will be set after multiplayer init
        )

        self.player_controller.camera_relative_movement = self.camera_relative_movement

        saved_player = self.save_manager.load_player()
        if saved_player:
            self.player_controller.apply_saved_state(saved_player)
            if "inventory" in saved_player:
                self.inventory_manager.load_dict(saved_player["inventory"])

        initial_loaded_chunks = self.world_manager.update_streaming(tuple(self.player_controller.position))
        self.player_controller.rescue_if_unsafe()

        self.render_manager = RenderManager(
            self,
            self.world_manager,
            self.inventory_manager,
            self.block_registry
        )

        self._sync_streaming_budget()

        self.render_manager.time_of_day = float(self.world_metadata.get("time_of_day", 0.25))
        if initial_loaded_chunks:
            self.render_manager.queue_dirty_chunks(initial_loaded_chunks)
        self.render_manager.queue_dirty_chunks(self.chunk_manager.dirty_render_chunks())

        self.render_manager.rebuild_dirty_chunks()
        self._last_streamed_chunk = ChunkCoord.from_world(
            int(self.player_controller.position.x),
            int(self.player_controller.position.z),
        )
        
        # ✅ Initialize multiplayer if enabled
        if self.multiplayer:
            self._init_multiplayer()

    def _init_multiplayer(self) -> None:
        """Initialize multiplayer connection."""
        self.network_client = NetworkClient(self.server_host, self.server_port)
        
        # Set up callbacks
        self.network_client.on_login_success = self._on_network_login_success
        self.network_client.on_player_join = self._on_remote_player_join
        self.network_client.on_player_leave = self._on_remote_player_leave
        self.network_client.on_player_update = self._on_remote_player_update
        self.network_client.on_block_change = self._on_remote_block_change
        
        # Give PlayerController access to network client for block sync
        self.player_controller.network_client = self.network_client
        
        # Connect to server
        if self.network_client.connect(self.username):
            print(f"🌐 Connecting to {self.server_host}:{self.server_port}...")
        else:
            print("❌ Failed to start network connection")
            self.network_client = None
    
    def _on_network_login_success(self, player_id: str, spawn_pos: Vector3) -> None:
        """Callback when successfully logged in to server."""
        print(f"✅ Logged in as {self.username} (ID: {player_id})")
        # Optionally teleport to server spawn position
        # self.player_controller.position = (spawn_pos.x, spawn_pos.y, spawn_pos.z)
    
    def _on_remote_player_join(self, player_id: str, username: str, position: Vector3) -> None:
        """Callback when a remote player joins."""
        print(f"👋 {username} joined the game")
        self.render_manager.add_remote_player(player_id, username)
    
    def _on_remote_player_leave(self, player_id: str) -> None:
        """Callback when a remote player leaves."""
        print(f"👋 Player {player_id} left the game")
        self.render_manager.remove_remote_player(player_id)
    
    def _on_remote_player_update(self, player_id: str, position: Vector3, rotation: tuple, animation: str) -> None:
        """Callback when a remote player's state is updated."""
        self.render_manager.update_remote_player(
            player_id,
            (position.x, position.y, position.z),
            rotation,
            animation
        )
    
    def _on_remote_block_change(self, position: tuple, old_block: int, new_block: int) -> None:
        """Callback when a remote player changes a block."""
        # Directly apply block change from network
        try:
            self.world_manager.set_block_direct(position, new_block)
        except Exception as e:
            print(f"Error applying remote block change: {e}")

    def _load_settings(self) -> None:
        settings = self.world_metadata.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}

        self.render_distance = self._clamp_render_distance(
            int(settings.get("render_distance", self.render_distance))
        )

        self.fov = max(45.0, min(120.0, float(settings.get("fov", self.fov))))
        self.camera_relative_movement = bool(
            settings.get("camera_relative_movement", self.camera_relative_movement)
        )

    def _clamp_render_distance(self, value: int) -> int:
        return max(self.MIN_RENDER_DISTANCE, min(self.MAX_RENDER_DISTANCE, value))

    def _bind_settings_inputs(self) -> None:
        self.accept("f5", self.adjust_render_distance, [-1])
        self.accept("f6", self.adjust_render_distance, [1])
        self.accept("f7", self.adjust_fov, [-5])
        self.accept("f8", self.adjust_fov, [5])
        self.accept("f9", self.toggle_movement_mode)
        self.accept("f10", self.toggle_debug_overlay)
        self.accept("e", self.toggle_inventory)
        self.accept("t", self.toggle_crafting_menu)
        self.accept("escape", self.toggle_settings_menu)

    def _apply_fov(self) -> None:
        self.camLens.setFov(self.fov)

    def _safe_set_settings_menu(self) -> None:
        """Single safe entry point for RenderManager menu sync."""

        if not hasattr(self, "render_manager"):
            return

        self.render_manager.set_settings_menu_visible(
            self.settings_menu_open,
            self.render_distance,
            self.fov,
            self.camera_relative_movement,
        )

    def _show_settings(self) -> None:
        if not hasattr(self, "render_manager"):
            return

        if self.settings_menu_open:
            self.render_manager.update_settings_menu(
                self.render_distance,
                self.fov,
                self.camera_relative_movement,
            )
        else:
            self.render_manager.show_settings(
                self.render_distance,
                self.fov,
                self.camera_relative_movement,
            )

    def toggle_settings_menu(self) -> None:
        if hasattr(self, "render_manager") and self.render_manager.inventory_visible:
            self.toggle_inventory()
            return

        self.settings_menu_open = not self.settings_menu_open

        self.render_manager.set_settings_menu_visible(
            self.settings_menu_open,
            self.render_distance,
            self.fov,
            self.camera_relative_movement,
        )

        self._set_mouse_captured(not self.settings_menu_open)

    def toggle_inventory(self) -> None:
        if self.settings_menu_open:
            return

        self.render_manager.set_inventory_visible(
            not self.render_manager.inventory_visible
        )

        self._set_mouse_captured(not self.render_manager.inventory_visible)

    def toggle_crafting_menu(self) -> None:
        if self.settings_menu_open:
            return

        self.render_manager.set_crafting_menu_visible(
            not self.render_manager.crafting_menu_visible
        )

        self._set_mouse_captured(not self.render_manager.crafting_menu_visible)

    def _set_mouse_captured(self, captured: bool) -> None:
        if not self.win or not hasattr(self.win, "requestProperties"):
            return

        props = WindowProperties()
        props.setCursorHidden(captured)
        self.win.requestProperties(props)

        if captured:
            self.win.movePointer(
                0,
                self.win.getXSize() // 2,
                self.win.getYSize() // 2
            )

    def adjust_render_distance(self, delta: int) -> None:
        old = self.render_distance
        self.render_distance = self._clamp_render_distance(self.render_distance + delta)

        if self.render_distance == old:
            self._show_settings()
            return

        self._sync_effective_render_distance()
        self._sync_streaming_budget()
        self.world_manager.update_streaming(tuple(self.player_controller.position))
        self.render_manager.remove_unloaded_chunk_nodes()

        self._show_settings()
        self.save_settings()

    def adjust_fov(self, delta: int) -> None:
        self.fov = max(45.0, min(110.0, self.fov + delta))
        self._apply_fov()
        self._show_settings()
        self.save_settings()

    def toggle_movement_mode(self) -> None:
        self.camera_relative_movement = not self.camera_relative_movement
        self.player_controller.camera_relative_movement = self.camera_relative_movement
        self._show_settings()
        self.save_settings()

    def set_time(self, hours: float) -> None:
        """Set the world time using a 0-24 hour value."""

        self.set_time_of_day(hours)

    def set_time_of_day(self, hours: float) -> None:
        """Set the in-game time using hours in the 0-24 range."""

        normalized = (float(hours) % 24.0) / 24.0
        self.render_manager.time_of_day = normalized
        self.world_metadata["time_of_day"] = normalized
        self.save_manager.save_metadata(self.world_metadata)

    def debug_on(self) -> None:
        """Show the performance debug overlay."""

        self.render_manager.set_debug_visible(True)

    def debug_off(self) -> None:
        """Hide the performance debug overlay."""

        self.render_manager.set_debug_visible(False)

    def toggle_debug_overlay(self) -> None:
        """Toggle the performance debug overlay."""

        self.render_manager.toggle_debug_visible()

    def _sync_streaming_budget(self) -> None:
        """Adjust chunk and mesh work budgets to the current render distance.
        
        Balance: Load enough chunks to keep up with player, but not so many
        that it causes stuttering. Prioritize core (closer) chunks.
        """

        effective = self._effective_render_distance
        # Conservative but functional: 4-8 chunks per update
        load_budget = max(4, min(8, effective))
        unload_budget = 2
        rebuild_budget = max(8, min(24, effective * 3))

        self.chunk_manager.max_loads_per_update = load_budget
        self.chunk_manager.max_unloads_per_update = unload_budget
        self.render_manager.max_chunk_rebuilds_per_frame = rebuild_budget

    def _sync_effective_render_distance(self) -> None:
        """Clamp the actual chunk streaming radius to a stable internal limit."""

        self._effective_render_distance = min(self.render_distance, self.MAX_EFFECTIVE_RENDER_DISTANCE)
        if hasattr(self, 'chunk_manager'):
            self.chunk_manager.load_radius = self._effective_render_distance

    def save_settings(self) -> None:
        self.world_metadata["settings"] = {
            "render_distance": self.render_distance,
            "fov": self.fov,
            "camera_relative_movement": self.camera_relative_movement,
        }
        self.save_manager.save_metadata(self.world_metadata)

    def update(self, task: Any) -> Any:
        if self.is_shutting_down:
            return task.done

        dt = ClockObject.getGlobalClock().getDt()

        self.elapsed_time += dt
        self.autosave_timer += dt
        
        # ✅ Process network messages if in multiplayer
        if self.network_client:
            self.network_client.process_messages()
            
            # Periodically send player state updates (5x per second)
            self.network_update_timer += dt
            if self.network_update_timer >= 0.2:
                self.network_update_timer = 0.0
                self.network_client.send_player_update(
                    self.player_controller.position,
                    self.player_controller.get_rotation(),
                    self._get_animation_state()
                )

        if not self.settings_menu_open and not self.render_manager.inventory_visible:
            self.player_controller.update(dt)
            current_chunk = ChunkCoord.from_world(
                int(self.player_controller.position.x),
                int(self.player_controller.position.z),
            )
            if current_chunk != self._last_streamed_chunk:
                self._last_streamed_chunk = current_chunk
                new_chunks = self.world_manager.update_streaming(tuple(self.player_controller.position))
                if new_chunks:
                    self.render_manager.queue_dirty_chunks(new_chunks)

        ready_chunks = self.world_manager.poll_streaming()
        if ready_chunks:
            self.render_manager.queue_dirty_chunks(
                [ChunkCoord(x, z) for x, z in ready_chunks]
            )

        for event in self.world_manager.consume_events():
            self.render_manager.queue_dirty_chunk(event.chunk)
        self.render_manager.update(dt)

        if self.autosave_timer >= 20.0:
            self.autosave_timer = 0.0
            self.save_game()

        return task.cont
    
    def _get_animation_state(self) -> str:
        """Determine current animation state based on player movement."""
        player = self.player_controller
        # Simplified: walking if moving horizontally, idle otherwise
        horizontal_velocity = (player.velocity.x**2 + player.velocity.z**2)**0.5
        if horizontal_velocity > 0.1:
            return "walking"
        elif player.velocity.y < -0.5:
            return "falling"
        return "idle"

    def save_game(self) -> None:
        self.world_metadata["time_of_day"] = self.render_manager.time_of_day

        self.world_metadata["settings"] = {
            "render_distance": self.render_distance,
            "fov": self.fov,
            "camera_relative_movement": self.camera_relative_movement,
        }

        self.save_manager.save_metadata(self.world_metadata)
        self.chunk_manager.save_all()

        player_state = self.player_controller.to_dict()
        player_state["inventory"] = self.inventory_manager.to_dict()
        self.save_manager.save_player(player_state)

    def close(self) -> None:
        self.is_shutting_down = True

        if hasattr(self, "chunk_manager"):
            self.save_game()
            self.chunk_manager.shutdown()
        if hasattr(self, "render_manager"):
            self.render_manager.shutdown()

        self.taskMgr.remove("game-manager-update")
        self.destroy()