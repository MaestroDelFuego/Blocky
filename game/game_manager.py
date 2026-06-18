"""File: game_manager.py

Purpose:
    Top-level coordinator for the local Panda3D client.

Responsibilities:
    * Own the Panda3D ShowBase instance.
    * Establish the client update loop.
    * Keep references to high-level systems as they are generated.
    * Provide lifecycle hooks for startup and shutdown.
    * Enforce the architectural rule that game systems are coordinated through
      managers instead of directly reaching across subsystem boundaries.

Dependencies:
    * direct.showbase.ShowBase.ShowBase for Panda3D application ownership.
    * pathlib.Path for project-root storage.
    * main.AppConfig-compatible startup configuration.

Systems that depend on it:
    * main.py constructs GameManager during client startup.
    * Future WorldManager, PlayerController, InventoryManager, RenderManager,
      and SaveManager instances will be owned or coordinated here.

Future multiplayer considerations:
    GameManager is a client orchestrator, not a server simulation authority.
    The eventual dedicated server should not inherit from ShowBase and should
    not import rendering code. Shared gameplay systems should expose pure data
    and event APIs that can be driven by either this client manager or a future
    server manager.
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


class GameManager(ShowBase):
    """Top-level lifecycle manager for the local game client.

    Purpose:
        Creates the Panda3D application object and provides the stable root that
        future systems attach to.

    Responsibilities:
        * Initialize Panda3D's window, scene graph, camera, and task manager.
        * Register one central update task.
        * Store project paths and startup configuration for child systems.
        * Own client-only systems while keeping world mutation delegated to the
          future WorldManager.

    Lifecycle:
        Constructed once by main.create_game(). It lives until the application
        exits or shutdown() is called by a smoke test.

    Dependencies:
        Depends on Panda3D ShowBase and an AppConfig-like object. It currently
        does not depend on world, player, rendering, inventory, or saving
        systems because those will be generated one stage at a time.

    Threading considerations:
        Panda3D scene graph operations happen on the main thread. Future worker
        threads may prepare chunk data, but they must communicate back through
        queues or events rather than mutating Panda3D nodes directly.

    Future networking considerations:
        This class will eventually translate local input into player action
        requests and consume authoritative world events. It must not become the
        owner of canonical world state in multiplayer.
    """

    TERRAIN_VERSION = 3
    MIN_RENDER_DISTANCE = 1
    MAX_RENDER_DISTANCE = 5

    def __init__(self, project_root: Path, app_config: Any) -> None:
        """Initialize the Panda3D client shell.

        Purpose:
            Builds the engine-level application object and registers the first
            lifecycle task.

        Args:
            project_root: Absolute path to the game package directory.
            app_config: Startup configuration produced by main.AppConfig.

        Returns:
            None.

        Side Effects:
            Creates Panda3D global application state, opens a window unless the
            configured window type is "none", changes the background color, and
            registers an update task.

        Raises:
            Exception: Panda3D may raise engine-specific exceptions if graphics
            initialization fails.

        Performance considerations:
            O(1) during this stage. Later system construction costs will be
            documented in the systems that introduce them.
        """

        super().__init__()
        self.project_root = Path(project_root)
        self.app_config = app_config
        self.elapsed_time = 0.0
        self.autosave_timer = 0.0
        self.is_shutting_down = False
        self.render_distance = 3
        self.fov = 75.0
        self.camera_relative_movement = True
        self.settings_menu_open = False

        self.disableMouse()
        self.setBackgroundColor(0.54, 0.73, 0.94, 1.0)
        self._create_systems()
        self.taskMgr.add(self.update, "game-manager-update")

    def _create_systems(self) -> None:
        """Create all gameplay systems in dependency order.

        Purpose:
            Builds the single-player client stack while preserving clear
            boundaries between world authority, rendering, input, inventory,
            terrain, chunks, and saving.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Creates managers, loads metadata, restores player state, and loads
            initial chunks around the player.

        Raises:
            OSError: If save directories or files cannot be accessed.

        Performance considerations:
            O(r^2 * chunk_generation_cost), where r is initial chunk radius.
        """

        self.block_registry = BlockRegistry()
        self.save_manager = SaveManager(self.project_root.parent / "saves")
        self.save_manager.terrain_version = self.TERRAIN_VERSION
        self.world_metadata = self.save_manager.load_metadata(default_seed=1337)
        if int(self.world_metadata.get("terrain_version", 1)) < self.TERRAIN_VERSION:
            self.world_metadata["terrain_version"] = self.TERRAIN_VERSION
        self._load_settings()
        self._apply_fov()
        self.terrain_generator = TerrainGenerator(int(self.world_metadata["seed"]), self.block_registry)
        self.chunk_manager = ChunkManager(self.terrain_generator, self.save_manager, load_radius=self.render_distance)
        self.world_manager = WorldManager(self.chunk_manager, self.block_registry)
        self.inventory_manager = InventoryManager(self.block_registry)
        self.player_controller = PlayerController(self, self.world_manager, self.inventory_manager)
        self.player_controller.camera_relative_movement = self.camera_relative_movement

        saved_player = self.save_manager.load_player()
        if saved_player:
            self.player_controller.apply_saved_state(saved_player)
            if "inventory" in saved_player:
                self.inventory_manager.load_dict(saved_player["inventory"])

        self.world_manager.update_streaming(tuple(self.player_controller.position))
        self.player_controller.rescue_if_unsafe()
        self.render_manager = RenderManager(self, self.world_manager, self.inventory_manager, self.block_registry)
        self.render_manager.time_of_day = float(self.world_metadata.get("time_of_day", 0.25))
        self.render_manager.rebuild_dirty_chunks()
        self.player_controller.capture_mouse()
        self._bind_settings_inputs()
        self.render_manager.update_settings_menu(self.render_distance, self.fov, self.camera_relative_movement)

    def _load_settings(self) -> None:
        """Load client settings from world metadata."""

        settings = self.world_metadata.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
        self.render_distance = self._clamp_render_distance(int(settings.get("render_distance", self.render_distance)))
        self.fov = max(45.0, min(110.0, float(settings.get("fov", self.fov))))
        self.camera_relative_movement = bool(settings.get("camera_relative_movement", self.camera_relative_movement))

    def _clamp_render_distance(self, value: int) -> int:
        """Keep render distance inside a playable range."""

        return max(self.MIN_RENDER_DISTANCE, min(self.MAX_RENDER_DISTANCE, value))

    def _bind_settings_inputs(self) -> None:
        """Bind live settings controls."""

        self.accept("f5", self.adjust_render_distance, [-1])
        self.accept("f6", self.adjust_render_distance, [1])
        self.accept("f7", self.adjust_fov, [-5])
        self.accept("f8", self.adjust_fov, [5])
        self.accept("f9", self.toggle_movement_mode)
        self.accept("e", self.toggle_inventory)
        self.accept("escape", self.toggle_settings_menu)

    def _apply_fov(self) -> None:
        """Apply the current camera field of view."""

        self.camLens.setFov(self.fov)

    def _show_settings(self) -> None:
        """Refresh the temporary settings HUD."""

        if hasattr(self, "render_manager"):
            if self.settings_menu_open:
                self.render_manager.update_settings_menu(self.render_distance, self.fov, self.camera_relative_movement)
            else:
                self.render_manager.show_settings(self.render_distance, self.fov, self.camera_relative_movement)

    def toggle_settings_menu(self) -> None:
        """Open or close the Esc settings menu."""

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
        """Open or close the survival inventory."""

        if self.settings_menu_open:
            return
        self.render_manager.set_inventory_visible(not self.render_manager.inventory_visible)
        self._set_mouse_captured(not self.render_manager.inventory_visible)

    def _set_mouse_captured(self, captured: bool) -> None:
        """Capture or release the mouse cursor."""

        if not self.win or not hasattr(self.win, "requestProperties"):
            return
        props = WindowProperties()
        props.setCursorHidden(captured)
        self.win.requestProperties(props)
        if captured:
            self.win.movePointer(0, self.win.getXSize() // 2, self.win.getYSize() // 2)

    def adjust_render_distance(self, delta: int) -> None:
        """Change chunk loading radius at runtime."""

        old_distance = self.render_distance
        self.render_distance = self._clamp_render_distance(self.render_distance + delta)
        if self.render_distance == old_distance:
            self._show_settings()
            return
        self.chunk_manager.load_radius = self.render_distance
        self.world_manager.update_streaming(tuple(self.player_controller.position))
        self.render_manager.remove_unloaded_chunk_nodes()
        self._show_settings()
        self.save_settings()

    def adjust_fov(self, delta: int) -> None:
        """Change camera FOV at runtime."""

        self.fov = max(45.0, min(110.0, self.fov + delta))
        self._apply_fov()
        self._show_settings()
        self.save_settings()

    def toggle_movement_mode(self) -> None:
        """Toggle between camera-relative and world-axis movement."""

        self.camera_relative_movement = not self.camera_relative_movement
        self.player_controller.camera_relative_movement = self.camera_relative_movement
        self._show_settings()
        self.save_settings()

    def save_settings(self) -> None:
        """Persist lightweight client settings without forcing a full world save."""

        self.world_metadata["settings"] = {
            "render_distance": self.render_distance,
            "fov": self.fov,
            "camera_relative_movement": self.camera_relative_movement,
        }
        self.save_manager.save_metadata(self.world_metadata)

    def update(self, task: Any) -> Any:
        """Advance the client shell by one frame.

        Purpose:
            Provides the central per-frame hook that future systems will use for
            input, player movement, world streaming, rendering updates, and save
            scheduling.

        Args:
            task: Panda3D task object supplied by the task manager.

        Returns:
            task.cont while the game is active, or task.done during shutdown.

        Side Effects:
            Updates elapsed_time. Future revisions will dispatch update calls to
            generated systems from this method.

        Raises:
            No expected exceptions in the current implementation.

        Performance considerations:
            O(1) in this stage. Future work inside this method must stay bounded
            per frame and move expensive chunk generation or meshing into
            budgeted queues.
        """

        if self.is_shutting_down:
            return task.done

        dt = ClockObject.getGlobalClock().getDt()
        self.elapsed_time += dt
        self.autosave_timer += dt
        if not self.settings_menu_open and not self.render_manager.inventory_visible:
            self.player_controller.update(dt)
            self.world_manager.update_streaming(tuple(self.player_controller.position))
        self.world_manager.consume_events()
        self.render_manager.update(dt)
        if self.autosave_timer >= 20.0:
            self.autosave_timer = 0.0
            self.save_game()
        return task.cont

    def save_game(self) -> None:
        """Save current single-player world state.

        Purpose:
            Flushes world metadata, dirty chunks, inventory, and player state.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Writes JSON save files to disk.

        Raises:
            OSError: If save files cannot be written.

        Performance considerations:
            O(d * n), where d is dirty chunk count and n is average chunk size.
        """

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
        """Shut down the local client shell.

        Purpose:
            Provides a controlled teardown path for smoke tests and future menu
            exits without overriding Panda3D's internal shutdown() method.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Marks the manager as closing, removes the update task, and
            destroys the Panda3D ShowBase resources owned by this instance.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1) for this stage. Future systems should release resources in
            reverse construction order to avoid dangling scene nodes or file
            handles.
        """

        self.is_shutting_down = True
        if hasattr(self, "chunk_manager"):
            self.save_game()
        self.taskMgr.remove("game-manager-update")
        self.destroy()
