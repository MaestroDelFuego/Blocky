"""File: render_manager.py

Purpose:
    Owns client-only scene graph rendering, lighting, and UI overlays.

Responsibilities:
    * Rebuild dirty chunk meshes.
    * Remove meshes for unloaded chunks.
    * Display crosshair and hotbar UI.
    * Update day/night lighting.
    * Never modify world data.

Dependencies:
    * direct.gui.OnscreenText for simple UI.
    * panda3d.core for lights and scene nodes.
    * chunks.chunk for chunk coordinates.
    * rendering.chunk_mesher for mesh construction.

Systems that depend on it:
    * GameManager constructs and updates RenderManager.

Future multiplayer considerations:
    Rendering stays client-side. It should consume server/world events and
    snapshots, never decide authoritative simulation state.
"""

from __future__ import annotations

import math
from typing import Any

from direct.gui.DirectGui import DirectButton, DirectFrame, DirectLabel
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import AmbientLight, DirectionalLight, NodePath, TextNode, Vec3, Vec4

from chunks.chunk import ChunkCoord
from inventory.inventory_manager import InventoryManager
from rendering.chunk_mesher import ChunkMesher
from world.block_registry import BlockRegistry
from world.world_manager import WorldManager


class RenderManager:
    """Client-only render coordinator.

    Purpose:
        Converts world state into Panda3D scene graph and UI updates.

    Responsibilities:
        * Build and attach chunk mesh nodes.
        * Update lighting based on time of day.
        * Show hotbar and crosshair information.
        * Remove scene nodes for unloaded chunks.

    Lifecycle:
        Constructed once by GameManager after WorldManager and InventoryManager.

    Dependencies:
        Depends on Panda3D base, WorldManager, InventoryManager, BlockRegistry,
        and ChunkMesher.

    Threading considerations:
        Scene graph mutation must remain on the main thread.

    Future networking considerations:
        This manager can render replicated server state without knowing whether
        the source is local generation or network updates.
    """

    def __init__(
        self,
        base: Any,
        world_manager: WorldManager,
        inventory_manager: InventoryManager,
        block_registry: BlockRegistry,
    ) -> None:
        """Create the render manager.

        Purpose:
            Initializes chunk mesh storage, lights, and UI overlays.

        Args:
            base: Panda3D ShowBase-compatible object.
            world_manager: World state read/event source.
            inventory_manager: Hotbar state source.
            block_registry: Block metadata registry.

        Returns:
            None.

        Side Effects:
            Adds lights and UI nodes to the Panda3D scene.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1) setup.
        """

        self.base = base
        self.world = world_manager
        self.inventory = inventory_manager
        self.blocks = block_registry
        self.mesher = ChunkMesher(block_registry, world_manager)
        self.chunk_nodes: dict[ChunkCoord, NodePath] = {}
        self.time_of_day = 0.25
        self.menu_visible = False
        self.inventory_visible = False
        self.menu_labels: dict[str, DirectLabel] = {}
        self.inventory_slot_labels: list[DirectLabel] = []
        self.inventory_message_timer = 0.0
        self.max_chunk_rebuilds_per_frame = 1
        self._setup_lighting()
        self._setup_ui()

    def _setup_lighting(self) -> None:
        """Create basic scene lighting.

        Purpose:
            Adds ambient and directional light for day/night rendering.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Attaches light nodes to the scene graph.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        ambient = AmbientLight("ambient-light")
        ambient.setColor(Vec4(0.35, 0.38, 0.42, 1))
        self.ambient_np = self.base.render.attachNewNode(ambient)
        self.base.render.setLight(self.ambient_np)

        sun = DirectionalLight("sun-light")
        sun.setColor(Vec4(0.9, 0.86, 0.74, 1))
        self.sun_np = self.base.render.attachNewNode(sun)
        self.sun_np.setHpr(35, -55, 0)
        self.base.render.setLight(self.sun_np)

    def _setup_ui(self) -> None:
        """Create crosshair and hotbar text.

        Purpose:
            Provides basic offline UI without image assets.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Creates OnscreenText nodes.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        self.crosshair = OnscreenText(text="+", pos=(0, 0), scale=0.055, fg=(1, 1, 1, 0.85), align=TextNode.ACenter)
        self.hotbar = OnscreenText(text="", pos=(0, -0.92), scale=0.045, fg=(1, 1, 1, 0.95), align=TextNode.ACenter)
        self.settings_text = OnscreenText(
            text="",
            pos=(-1.30, 0.92),
            scale=0.038,
            fg=(1, 1, 1, 0.90),
            align=TextNode.ALeft,
        )
        self.settings_timer = 0.0
        self._setup_settings_menu()
        self._setup_inventory_menu()

    def _setup_settings_menu(self) -> None:
        """Create the Esc settings menu."""

        self.menu_frame = DirectFrame(
            parent=self.base.aspect2d,
            frameColor=(0.05, 0.06, 0.07, 0.88),
            frameSize=(-0.78, 0.78, -0.62, 0.62),
            pos=(0, 0, 0),
        )
        DirectLabel(
            parent=self.menu_frame,
            text="Settings",
            scale=0.075,
            pos=(0, 0, 0.48),
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )
        self._add_setting_row("render_distance", "Render Distance", 0.28, self.base.adjust_render_distance)
        self._add_setting_row("fov", "FOV", 0.08, self.base.adjust_fov)
        DirectLabel(
            parent=self.menu_frame,
            text="Movement",
            scale=0.048,
            pos=(-0.46, 0, -0.12),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.88, 0.92, 0.95, 1),
        )
        self.menu_labels["movement"] = DirectLabel(
            parent=self.menu_frame,
            text="",
            scale=0.048,
            pos=(0.08, 0, -0.12),
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )
        DirectButton(
            parent=self.menu_frame,
            text="Toggle",
            scale=0.045,
            pos=(0.43, 0, -0.12),
            command=self.base.toggle_movement_mode,
        )
        DirectButton(parent=self.menu_frame, text="Resume", scale=0.052, pos=(0, 0, -0.38), command=self.base.toggle_settings_menu)
        self.menu_frame.hide()

    def _setup_inventory_menu(self) -> None:
        """Create the survival inventory and crafting overlay."""

        self.inventory_frame = DirectFrame(
            parent=self.base.aspect2d,
            frameColor=(0.04, 0.05, 0.05, 0.91),
            frameSize=(-1.05, 1.05, -0.74, 0.74),
            pos=(0, 0, 0),
        )
        DirectLabel(
            parent=self.inventory_frame,
            text="Inventory",
            scale=0.064,
            pos=(-0.72, 0, 0.62),
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )
        DirectLabel(
            parent=self.inventory_frame,
            text="Crafting",
            scale=0.064,
            pos=(0.48, 0, 0.62),
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )
        self.inventory_status = DirectLabel(
            parent=self.inventory_frame,
            text="",
            scale=0.04,
            pos=(0, 0, -0.64),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.95, 0.95, 0.85, 1),
        )
        for slot in range(self.inventory.INVENTORY_SIZE):
            col = slot % 4
            row = slot // 4
            label = DirectLabel(
                parent=self.inventory_frame,
                text="",
                scale=0.037,
                pos=(-0.84 + col * 0.31, 0, 0.45 - row * 0.16),
                frameColor=(0.12, 0.13, 0.14, 0.82),
                frameSize=(-3.55, 3.55, -1.0, 1.0),
                text_fg=(1, 1, 1, 1),
            )
            self.inventory_slot_labels.append(label)
        recipes = (
            ("planks", "Planks: 1 Wood -> 4"),
            ("door", "Door: 3 Planks -> 1"),
            ("pickaxe", "Pickaxe: 3 Planks -> 1"),
            ("axe", "Axe: 3 Planks -> 1"),
            ("sword", "Sword: 2 Planks -> 1"),
            ("cobble", "Cobble: 1 Stone -> 1"),
            ("bread", "Bread: 2 Apples -> 1"),
            ("glass", "Glass: 2 Sand + 1 Coal -> 2"),
            ("bricks", "Bricks: 4 Clay -> 2"),
        )
        for index, (recipe_id, text) in enumerate(recipes):
            DirectButton(
                parent=self.inventory_frame,
                text=text,
                scale=0.032,
                pos=(0.48, 0, 0.45 - index * 0.105),
                command=self._craft_recipe,
                extraArgs=[recipe_id],
            )
        DirectButton(parent=self.inventory_frame, text="Close", scale=0.048, pos=(0.48, 0, -0.50), command=self.base.toggle_inventory)
        self.inventory_frame.hide()

    def _add_setting_row(self, key: str, title: str, y: float, command: Any) -> None:
        """Add one +/- setting row to the menu."""

        DirectLabel(
            parent=self.menu_frame,
            text=title,
            scale=0.048,
            pos=(-0.46, 0, y),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.88, 0.92, 0.95, 1),
        )
        DirectButton(parent=self.menu_frame, text="-", scale=0.052, pos=(-0.05, 0, y), command=command, extraArgs=[-1 if key == "render_distance" else -5])
        self.menu_labels[key] = DirectLabel(
            parent=self.menu_frame,
            text="",
            scale=0.048,
            pos=(0.18, 0, y),
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )
        DirectButton(parent=self.menu_frame, text="+", scale=0.052, pos=(0.43, 0, y), command=command, extraArgs=[1 if key == "render_distance" else 5])

    def update(self, dt: float) -> None:
        """Update rendering for one frame.

        Purpose:
            Rebuilds dirty chunks, advances lighting, and refreshes UI.

        Args:
            dt: Delta time in seconds.

        Returns:
            None.

        Side Effects:
            Mutates scene graph, light colors, and UI text.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(d * mesh_cost + n), where d is dirty chunk count and n is loaded
            chunk count for stale-node cleanup.
        """

        self.time_of_day = (self.time_of_day + dt / 600.0) % 1.0
        self._update_lighting()
        self.rebuild_dirty_chunks()
        self.remove_unloaded_chunk_nodes()
        self._update_hotbar_text()
        self._update_inventory_menu()
        if self.inventory_message_timer > 0.0:
            self.inventory_message_timer = max(0.0, self.inventory_message_timer - dt)
            if self.inventory_message_timer == 0.0:
                self.inventory_status["text"] = ""
        if self.settings_timer > 0.0:
            self.settings_timer = max(0.0, self.settings_timer - dt)
            if self.settings_timer == 0.0:
                self.settings_text.setText("")

    def show_settings(self, render_distance: int, fov: float, camera_relative: bool) -> None:
        """Briefly show live settings values."""

        movement = "camera" if camera_relative else "world"
        self.update_settings_menu(render_distance, fov, camera_relative)
        self.settings_text.setText(f"Render distance: {render_distance}   FOV: {int(fov)}   Movement: {movement}")
        self.settings_timer = 3.0

    def update_settings_menu(self, render_distance: int, fov: float, camera_relative: bool) -> None:
        """Refresh settings menu labels."""

        movement = "Camera-relative" if camera_relative else "World-axis"
        self.menu_labels["render_distance"]["text"] = str(render_distance)
        self.menu_labels["fov"]["text"] = str(int(fov))
        self.menu_labels["movement"]["text"] = movement

    def set_settings_menu_visible(self, visible: bool, render_distance: int, fov: float, camera_relative: bool) -> None:
        """Show or hide the settings menu."""

        self.menu_visible = visible
        self.update_settings_menu(render_distance, fov, camera_relative)
        if visible:
            self.settings_text.setText("")
            self.settings_timer = 0.0
            self.menu_frame.show()
        else:
            self.menu_frame.hide()

    def set_inventory_visible(self, visible: bool) -> None:
        """Show or hide the survival inventory."""

        self.inventory_visible = visible
        if visible:
            self._update_inventory_menu()
            self.inventory_frame.show()
        else:
            self.inventory_frame.hide()

    def _craft_recipe(self, recipe_id: str) -> None:
        """Attempt to craft one recipe from the inventory menu."""

        if self.inventory.craft(recipe_id):
            self.inventory_status["text"] = "Crafted."
        else:
            self.inventory_status["text"] = "Missing ingredients or inventory space."
        self.inventory_message_timer = 2.0
        self._update_inventory_menu()

    def rebuild_dirty_chunks(self) -> None:
        """Rebuild all render-dirty chunks.

        Purpose:
            Keeps chunk meshes synchronized with world data.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Replaces Panda3D chunk nodes and clears chunk render-dirty flags.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(d * b), where d is dirty chunks and b is non-air blocks.
        """

        for chunk in self.world.chunk_manager.dirty_render_chunks()[: self.max_chunk_rebuilds_per_frame]:
            old = self.chunk_nodes.pop(chunk.coord, None)
            if old is not None:
                old.removeNode()
            node = self.mesher.build(chunk)
            path = self.base.render.attachNewNode(node)
            path.setTwoSided(True)
            self.chunk_nodes[chunk.coord] = path
            chunk.dirty_for_render = False

    def remove_unloaded_chunk_nodes(self) -> None:
        """Remove render nodes for chunks no longer loaded.

        Purpose:
            Prevents stale meshes from staying visible after chunk unloading.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Removes Panda3D scene nodes.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(n), where n is rendered chunk count.
        """

        loaded = set(self.world.chunk_manager.loaded)
        for coord in list(self.chunk_nodes):
            if coord not in loaded:
                self.chunk_nodes.pop(coord).removeNode()

    def _update_lighting(self) -> None:
        """Update sun and sky color from time of day.

        Purpose:
            Implements a simple day/night cycle.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Changes light colors and background color.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        angle = self.time_of_day * math.tau
        daylight = max(0.08, math.sin(angle))
        self.sun_np.setHpr(self.time_of_day * 360.0, -35 - daylight * 45, 0)
        self.sun_np.node().setColor(Vec4(0.95 * daylight, 0.88 * daylight, 0.72 * daylight, 1))
        self.ambient_np.node().setColor(Vec4(0.08 + daylight * 0.28, 0.09 + daylight * 0.30, 0.12 + daylight * 0.34, 1))
        self.base.setBackgroundColor(0.03 + daylight * 0.50, 0.05 + daylight * 0.65, 0.09 + daylight * 0.85, 1)

    def _update_hotbar_text(self) -> None:
        """Refresh hotbar text.

        Purpose:
            Displays selected block names and slot numbers.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Changes UI text.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(n), where n is hotbar size.
        """

        labels = []
        for index, stack in enumerate(self.inventory.hotbar):
            name = self.inventory.item_name(stack.item_id) if stack.count > 0 else "Empty"
            count = f"x{stack.count}" if stack.count > 0 else ""
            label = f"{index + 1}:{name}{count}"
            labels.append(f"[{label}]" if index == self.inventory.selected_index else label)
        player = getattr(self.base, "player_controller", None)
        hunger = getattr(player, "hunger", 20)
        health = getattr(player, "health", 20)
        mining = ""
        if player is not None and getattr(player, "mining_target", None) is not None and player.mining_duration > 0:
            progress = min(100, int(player.mining_timer / player.mining_duration * 100))
            mining = f"  Mining:{progress}%"
        self.hotbar.setText("  ".join(labels) + f"     Health:{health}/20  Food:{hunger}/20{mining}")

    def _update_inventory_menu(self) -> None:
        """Refresh inventory slot labels."""

        for index, label in enumerate(self.inventory_slot_labels):
            stack = self.inventory.slots[index]
            if stack.count > 0:
                text = f"{index + 1}. {self.inventory.item_name(stack.item_id)} x{stack.count}"
            else:
                text = f"{index + 1}. Empty"
            if index == self.inventory.selected_index:
                text = f"> {text}"
            label["text"] = text
