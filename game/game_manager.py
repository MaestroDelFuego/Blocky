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


class GameManager(ShowBase):

    TERRAIN_VERSION = 3
    MIN_RENDER_DISTANCE = 1
    MAX_RENDER_DISTANCE = 128

    def __init__(self, project_root: Path, app_config: Any) -> None:
        super().__init__()

        self.project_root = Path(project_root)
        self.app_config = app_config

        self.elapsed_time = 0.0
        self.autosave_timer = 0.0
        self.is_shutting_down = False

        self.render_distance = 2
        self.fov = 120.0
        self.camera_relative_movement = True
        self.settings_menu_open = False

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

        self.terrain_generator = TerrainGenerator(
            int(self.world_metadata["seed"]),
            self.block_registry
        )

        self.chunk_manager = ChunkManager(
            self.terrain_generator,
            self.save_manager,
            load_radius=self.render_distance
        )

        self.world_manager = WorldManager(self.chunk_manager, self.block_registry)
        self.inventory_manager = InventoryManager(self.block_registry)

        self.player_controller = PlayerController(
            self,
            self.world_manager,
            self.inventory_manager
        )

        self.player_controller.camera_relative_movement = self.camera_relative_movement

        saved_player = self.save_manager.load_player()
        if saved_player:
            self.player_controller.apply_saved_state(saved_player)
            if "inventory" in saved_player:
                self.inventory_manager.load_dict(saved_player["inventory"])

        self.world_manager.update_streaming(tuple(self.player_controller.position))
        self.player_controller.rescue_if_unsafe()

        self.render_manager = RenderManager(
            self,
            self.world_manager,
            self.inventory_manager,
            self.block_registry
        )

        self.render_manager.time_of_day = float(self.world_metadata.get("time_of_day", 0.25))

        self.render_manager.rebuild_dirty_chunks()

        self.player_controller.capture_mouse()

        self._bind_settings_inputs()

        self._safe_set_settings_menu()

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
        self.accept("e", self.toggle_inventory)
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

        self.chunk_manager.load_radius = self.render_distance
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

        self.taskMgr.remove("game-manager-update")
        self.destroy()