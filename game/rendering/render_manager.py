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
from pathlib import Path
from typing import Any

from direct.gui import DirectGuiGlobals as DGG
from direct.gui.DirectGui import DirectButton, DirectFrame, DirectLabel
from direct.gui.OnscreenImage import OnscreenImage
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import AmbientLight, DirectionalLight, Filename, NodePath, TextNode, Texture, TransparencyAttrib, Vec3, Vec4

from chunks.chunk import ChunkCoord
from inventory.inventory_manager import APPLE, BREAD, COAL, CRAFTING_ORDER, CRAFTING_RECIPES, IRON_ORE_ITEM, InventoryManager, WOOD_AXE, WOOD_PICKAXE, WOOD_SWORD
from rendering.chunk_mesher import ChunkMesher
from world.block_registry import BlockRegistry
from world.world_manager import WorldManager


# ---------------------------------------------------------------------------
# UI theme — single source of truth for HUD colors/fonts so every panel,
# slot, and button reads as part of one consistent design rather than a
# pile of ad-hoc DirectGui defaults.
# ---------------------------------------------------------------------------
class Theme:
    """Centralized HUD color/spacing constants."""

    PANEL_BG = (0.07, 0.08, 0.10, 0.92)
    PANEL_BORDER = (0.22, 0.24, 0.29, 1.0)
    PANEL_HEADER = (0.11, 0.12, 0.15, 1.0)

    ACCENT = (0.36, 0.62, 0.98, 1.0)
    ACCENT_DIM = (0.36, 0.62, 0.98, 0.30)

    TEXT_PRIMARY = (0.93, 0.94, 0.96, 1.0)
    TEXT_SECONDARY = (0.60, 0.64, 0.70, 1.0)
    TEXT_MUTED = (0.42, 0.45, 0.50, 1.0)

    SLOT_BG = (0.0, 0.0, 0.0, 0.45)
    SLOT_BORDER = (0.24, 0.26, 0.30, 1.0)
    SLOT_BORDER_SELECTED = ACCENT

    SHADOW = (0, 0, 0, 0.85)

    BORDER_WIDTH = 0.0035

    # DirectButton state order is (ready, press, rollover, disabled)
    BUTTON_COLORS = (
        (0.14, 0.16, 0.19, 1.0),
        (0.30, 0.52, 0.82, 1.0),
        (0.20, 0.23, 0.28, 1.0),
        (0.10, 0.10, 0.12, 0.5),
    )


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
        self.chunk_nodes: dict[ChunkCoord, NodePath] = {}
        self.crafting_buttons: list[DirectButton] = []
        self.time_of_day = 0.25
        self.menu_visible = False
        self.inventory_visible = False
        self.menu_labels: dict[str, DirectLabel] = {}
        self.inventory_slot_labels: list[DirectLabel] = []
        self.inventory_message_timer = 0.0
        self.max_chunk_rebuilds_per_frame = 16
        self.loader = base.loader  # ✅ FIX: makes loader available
        self.assets_dir = Path(__file__).resolve().parents[1] / "assets"
        self._icon_texture_cache: dict[str, Texture] = {}
        self._empty_slot_texture = self._slot_icon_texture(BlockRegistry.GRASS)
        self._last_hotbar_state = None
        self._last_inventory_state = None
        self._last_selected_index = -1
        self._create_sky_objects()

        self._setup_lighting()
        self._setup_ui()
        self.mesher = ChunkMesher(block_registry, world_manager)

    def _create_sky_objects(self):
        """Create sun, moon, clouds ONCE."""

        # SUN (world-space is OK)
        self.sun_model_np = self.loader.loadModel("models/misc/sphere")
        self.sun_model_np.reparentTo(self.base.render)
        self.sun_model_np.setScale(30)
        self.sun_model_np.setLightOff()

        # Moon stays in world space like the sun. We re-center it on the
        # camera's position each frame (see _update_lighting) so it follows
        # the player without rotating with camera heading. It must NOT be
        # parented to the camera.
        self.moon_model_np = self.loader.loadModel("models/misc/sphere")
        self.moon_model_np.reparentTo(self.base.render)
        self.moon_model_np.setScale(15)
        self.moon_model_np.setDepthTest(False)
        self.moon_model_np.setDepthWrite(False)
        self.moon_model_np.setBin("background", 10)
        self.moon_model_np.setLightOff()

    def _setup_lighting(self) -> None:

        ambient = AmbientLight("ambient-light")
        ambient.setColor(Vec4(0.35, 0.38, 0.42, 1))
        self.ambient_np = self.base.render.attachNewNode(ambient)
        self.base.render.setLight(self.ambient_np)

        sun = DirectionalLight("sun-light")
        sun.setColor(Vec4(0.9, 0.86, 0.74, 1))
        self.sun_light_np = self.base.render.attachNewNode(sun)
        self.base.render.setLight(self.sun_light_np)

    # ------------------------------------------------------------------
    # Small UI helpers — shared building blocks so every panel/slot/button
    # gets the same border + depth treatment instead of one-off styling.
    # ------------------------------------------------------------------
    def _bordered_frame(
        self,
        parent: Any,
        frame_size: tuple[float, float, float, float],
        pos: tuple[float, float, float] = (0, 0, 0),
        bg_color: tuple[float, float, float, float] = Theme.PANEL_BG,
        border_color: tuple[float, float, float, float] = Theme.PANEL_BORDER,
        border_width: float = Theme.BORDER_WIDTH,
    ) -> tuple[DirectFrame, DirectFrame]:
        """Create a panel with a crisp 1px-style border.

        Stacks a border-colored outer frame behind a slightly smaller
        background frame, since DirectFrame has no native border-color
        property independent of its fill.
        """

        outer = DirectFrame(
            parent=parent,
            relief=DGG.FLAT,
            frameColor=border_color,
            frameSize=frame_size,
            pos=pos,
        )
        inner_size = (
            frame_size[0] + border_width,
            frame_size[1] - border_width,
            frame_size[2] + border_width,
            frame_size[3] - border_width,
        )
        inner = DirectFrame(
            parent=outer,
            relief=DGG.FLAT,
            frameColor=bg_color,
            frameSize=inner_size,
            pos=(0, 0, 0),
        )
        return outer, inner

    def _styled_button(self, **kwargs: Any) -> DirectButton:
        """Create a DirectButton with the shared HUD button styling applied."""

        kwargs.setdefault("relief", DGG.FLAT)
        kwargs.setdefault("frameColor", Theme.BUTTON_COLORS)
        kwargs.setdefault("text_fg", Theme.TEXT_PRIMARY)
        kwargs.setdefault("pressEffect", 1)
        return DirectButton(**kwargs)

    def _styled_label(self, **kwargs: Any) -> DirectLabel:
        """Create a DirectLabel with shared HUD text styling applied."""

        kwargs.setdefault("frameColor", (0, 0, 0, 0))
        kwargs.setdefault("text_fg", Theme.TEXT_PRIMARY)
        return DirectLabel(**kwargs)

    def _slot_icon_texture(self, item_id: int) -> Texture | None:
        """Return the icon texture for a stack item or block."""

        if item_id == BlockRegistry.AIR:
            return None

        item_names = {
            APPLE: "apple",
            BREAD: "bread",
            COAL: "coal",
            IRON_ORE_ITEM: "raw_iron",
            WOOD_PICKAXE: "wood_pickaxe",
            WOOD_AXE: "wood_axe",
            WOOD_SWORD: "wood_sword",
        }
        icon_name = item_names.get(item_id)
        if icon_name is None:
            block = self.blocks.get(item_id)
            icon_path = self.assets_dir / "blocks" / f"{block.name}.png"
        else:
            icon_path = self.assets_dir / "items" / f"{icon_name}.png"

        cache_key = str(icon_path)
        texture = self._icon_texture_cache.get(cache_key)
        if texture is None:
            texture = self.loader.loadTexture(Filename.fromOsSpecific(cache_key))
            texture.setMinfilter(Texture.FTNearest)
            texture.setMagfilter(Texture.FTNearest)
            self._icon_texture_cache[cache_key] = texture
        return texture

    def _setup_ui(self) -> None:
        """Create the HUD: crosshair, hotbar, settings menu, inventory."""

        # ---------------- CROSSHAIR ----------------
        self.crosshair = OnscreenText(
            text="+",
            pos=(0, 0),
            scale=0.045,
            fg=Theme.TEXT_PRIMARY,
            shadow=Theme.SHADOW,
            align=TextNode.ACenter,
        )

        # ---------------- HOTBAR ----------------
        slot_size = 0.086
        slot_half = 0.038
        base_x = -slot_size * 4
        hotbar_y = -0.93

        # A single backing bar behind all nine slots gives the hotbar a
        # unified silhouette instead of nine floating squares.
        bar_margin = 0.012
        self.hotbar_bar_outer, self.hotbar_bar_inner = self._bordered_frame(
            self.base.aspect2d,
            frame_size=(
                base_x - slot_half - bar_margin,
                base_x + 8 * slot_size + slot_half + bar_margin,
                hotbar_y - slot_half - bar_margin,
                hotbar_y + slot_half + bar_margin,
            ),
            pos=(0, 0, 0),
            bg_color=Theme.PANEL_BG,
            border_color=Theme.PANEL_BORDER,
        )

        # Status readout (health / hunger) sits just above the hotbar.
        self.hotbar_status_text = OnscreenText(
            text="",
            pos=(0, hotbar_y + slot_half + bar_margin + 0.045),
            scale=0.04,
            fg=Theme.TEXT_PRIMARY,
            shadow=Theme.SHADOW,
            align=TextNode.ACenter,
        )

        self.hotbar_slots: list[tuple[DirectFrame, DirectFrame]] = []
        self.hotbar_icons: list[OnscreenImage] = []
        self.hotbar_labels: list[OnscreenText] = []
        self.hotbar_index_labels: list[OnscreenText] = []

        for i in range(9):
            x = base_x + i * slot_size
            outer, inner = self._bordered_frame(
                self.base.aspect2d,
                frame_size=(-slot_half, slot_half, -slot_half, slot_half),
                pos=(x, 0, hotbar_y),
                bg_color=Theme.SLOT_BG,
                border_color=Theme.SLOT_BORDER,
            )
            self.hotbar_slots.append((outer, inner))

            stack = self.inventory.slots[i] if i < len(self.inventory.slots) else None
            icon_texture = self._slot_icon_texture(stack.item_id) if stack is not None else None

            icon = OnscreenImage(
                parent=inner,
                image=icon_texture if icon_texture is not None else self._empty_slot_texture,
                pos=(0, 0, 0),
                scale=0.030,
            )
            icon.setTransparency(TransparencyAttrib.M_alpha)
            if icon_texture is None:
                icon.hide()
            self.hotbar_icons.append(icon)

            index_label = OnscreenText(
                text=str(i + 1),
                parent=inner,
                pos=(-slot_half + 0.010, slot_half - 0.012),
                scale=0.024,
                fg=Theme.TEXT_MUTED,
                shadow=Theme.SHADOW,
                align=TextNode.ALeft,
            )
            self.hotbar_index_labels.append(index_label)

            label = OnscreenText(
                text="",
                parent=inner,
                pos=(slot_half - 0.008, -slot_half + 0.004),
                scale=0.018,
                fg=Theme.TEXT_PRIMARY,
                shadow=Theme.SHADOW,
                align=TextNode.ARight,
            )
            self.hotbar_labels.append(label)

        # ---------------- SETTINGS TOAST (top-left) ----------------
        self.settings_text = OnscreenText(
            text="",
            pos=(-1.27, 0.93),
            scale=0.038,
            fg=Theme.TEXT_PRIMARY,
            shadow=Theme.SHADOW,
            align=TextNode.ALeft,
        )

        self.settings_timer = 0.0

        self._setup_settings_menu()
        self._setup_inventory_menu()

    def _setup_settings_menu(self) -> None:
        """Create the Esc settings menu."""

        panel_size = (-0.78, 0.78, -0.62, 0.62)
        self.menu_outer, self.menu_frame = self._bordered_frame(
            self.base.aspect2d,
            frame_size=panel_size,
            pos=(0, 0, 0),
            bg_color=Theme.PANEL_BG,
            border_color=Theme.PANEL_BORDER,
        )

        # Header strip: a thin accent-colored bar gives the panel a clear
        # "title bar," separating chrome from content.
        DirectFrame(
            parent=self.menu_frame,
            relief=DGG.FLAT,
            frameColor=Theme.PANEL_HEADER,
            frameSize=(panel_size[0], panel_size[1], 0.50, panel_size[3]),
            pos=(0, 0, 0),
        )
        DirectFrame(
            parent=self.menu_frame,
            relief=DGG.FLAT,
            frameColor=Theme.ACCENT,
            frameSize=(panel_size[0], panel_size[1], 0.495, 0.50),
            pos=(0, 0, 0),
        )
        self._styled_label(
            parent=self.menu_frame,
            text="Settings",
            scale=0.07,
            pos=(0, 0, 0.515),
            text_fg=Theme.TEXT_PRIMARY,
        )

        self._add_setting_row("render_distance", "Render Distance", 0.28, self.base.adjust_render_distance)
        self._add_setting_row("fov", "FOV", 0.08, self.base.adjust_fov)

        self._section_divider(-0.04)

        self._styled_label(
            parent=self.menu_frame,
            text="Movement",
            scale=0.046,
            pos=(-0.46, 0, -0.16),
            text_fg=Theme.TEXT_SECONDARY,
        )
        self.menu_labels["movement"] = self._styled_label(
            parent=self.menu_frame,
            text="",
            scale=0.046,
            pos=(0.08, 0, -0.16),
        )
        self._styled_button(
            parent=self.menu_frame,
            text="Toggle",
            scale=0.044,
            pos=(0.43, 0, -0.16),
            command=self.base.toggle_movement_mode,
        )

        self._section_divider(-0.30)

        self._styled_button(
            parent=self.menu_frame,
            text="Resume",
            scale=0.05,
            pos=(0, 0, -0.50),
            frameSize=(-2.4, 2.4, -0.7, 0.7),
            command=self.base.toggle_settings_menu,
        )
        self.menu_outer.hide()

    def _section_divider(self, y: float) -> DirectFrame:
        """A thin horizontal rule used to separate settings menu sections."""

        return DirectFrame(
            parent=self.menu_frame,
            relief=DGG.FLAT,
            frameColor=Theme.PANEL_BORDER,
            frameSize=(-0.7, 0.7, y, y + 0.0025),
            pos=(0, 0, 0),
        )

    def _setup_inventory_menu(self) -> None:
        """Minecraft-style inventory UI (improved layout + crafting integration)."""

        # ---------------- PANEL ----------------
        panel_size = (-0.9, 0.9, -0.62, 0.62)
        self.inventory_outer, self.inventory_frame = self._bordered_frame(
            self.base.aspect2d,
            frame_size=panel_size,
            pos=(0, 0, 0),
            bg_color=Theme.PANEL_BG,
            border_color=Theme.PANEL_BORDER,
        )

        # Header bar
        DirectFrame(
            parent=self.inventory_frame,
            relief=DGG.FLAT,
            frameColor=Theme.PANEL_HEADER,
            frameSize=(panel_size[0], panel_size[1], 0.50, panel_size[3]),
            pos=(0, 0, 0),
        )
        DirectFrame(
            parent=self.inventory_frame,
            relief=DGG.FLAT,
            frameColor=Theme.ACCENT,
            frameSize=(panel_size[0], panel_size[1], 0.495, 0.50),
            pos=(0, 0, 0),
        )

        self._styled_label(
            parent=self.inventory_frame,
            text="Inventory",
            scale=0.06,
            pos=(0, 0, 0.515),
        )

        # ---------------- INVENTORY GRID ----------------
        self.inventory_slots = []
        self.inventory_icons = []

        cols = 9
        slot_size = 0.098
        slot_half = 0.042
        slot_spacing = 0.010

        start_x = -(cols - 1) * (slot_size + slot_spacing) / 2
        start_y = 0.36

        for i in range(self.inventory.INVENTORY_SIZE):
            col = i % cols
            row = i // cols

            x = start_x + col * (slot_size + slot_spacing)
            y = start_y - row * (slot_size + slot_spacing)

            outer, inner = self._bordered_frame(
                self.inventory_frame,
                frame_size=(-slot_half, slot_half, -slot_half, slot_half),
                pos=(x, 0, y),
                bg_color=Theme.SLOT_BG,
                border_color=Theme.SLOT_BORDER,
            )

            slot = self.inventory.slots[i]
            icon_texture = self._slot_icon_texture(slot.item_id) if slot else None

            icon = OnscreenImage(
                parent=inner,
                image=icon_texture if icon_texture else self._empty_slot_texture,
                pos=(0, 0, 0),
                scale=0.034,
            )
            icon.setTransparency(TransparencyAttrib.M_alpha)

            if not icon_texture:
                icon.hide()

            self.inventory_icons.append(icon)

            label = OnscreenText(
                text="",
                parent=inner,
                pos=(0.03, -0.03),
                scale=0.018,
                fg=Theme.TEXT_PRIMARY,
                shadow=Theme.SHADOW,
                align=TextNode.ACenter,
            )

            self.inventory_slots.append(((outer, inner), label))

        # ---------------- STATUS LINE ----------------
        self.inventory_status = self._styled_label(
            parent=self.inventory_frame,
            text="",
            scale=0.04,
            pos=(0, 0, -0.56),
            text_fg=Theme.TEXT_SECONDARY,
        )

        # ---------------- CRAFTING ----------------
        self._setup_crafting_panel()

        self.inventory_outer.hide()

    def _setup_crafting_panel(self) -> None:
        """Improved crafting UI with better hierarchy and usability."""

        # ---------------- HEADER ----------------
        self._styled_label(
            parent=self.inventory_frame,
            text="Crafting",
            scale=0.05,
            pos=(0.55, 0, 0.49),
            text_fg=Theme.TEXT_PRIMARY,
        )

        self._styled_label(
            parent=self.inventory_frame,
            text="Select a recipe to craft items using materials.",
            scale=0.026,
            pos=(0.55, 0, 0.42),
            text_fg=Theme.TEXT_SECONDARY,
        )

        # ---------------- LAYOUT CONSTANTS ----------------
        start_x = 0.38
        start_y = 0.30
        x_step = 0.42
        y_step = 0.12

        self.crafting_buttons = []

        # ---------------- RECIPES ----------------
        for index, recipe_id in enumerate(CRAFTING_ORDER):
            ingredients, result = CRAFTING_RECIPES[recipe_id]

            output_name = self.inventory.item_name(result[0])
            output_count = result[1]

            # compact ingredient summary (cleaner than full dump)
            ingredient_summary = " + ".join(
                f"{self.inventory.item_name(item_id)}×{count}"
                for item_id, count in ingredients
            )

            col = index % 2
            row = index // 2

            x = start_x + col * x_step
            y = start_y - row * y_step

            button = self._styled_button(
                parent=self.inventory_frame,
                text=f"{output_name} ×{output_count}",
                scale=0.03,
                text_align=TextNode.ACenter,
                text_wordwrap=12,
                pos=(x, 0, y),
                frameSize=(-0.20, 0.20, -0.045, 0.045),
                command=self._craft_recipe,
                extraArgs=[recipe_id],
            )

            self.crafting_buttons.append(button)

            # optional: small ingredient label under button (much cleaner than full dump)
            self._styled_label(
                parent=self.inventory_frame,
                text=ingredient_summary,
                scale=0.022,
                pos=(x, 0, y - 0.055),
                text_fg=Theme.TEXT_MUTED,
            )

    def _add_setting_row(self, key: str, title: str, y: float, command: Any) -> None:
        """Add one +/- setting row to the menu."""

        self._styled_label(
            parent=self.menu_frame,
            text=title,
            scale=0.046,
            pos=(-0.46, 0, y),
            text_fg=Theme.TEXT_SECONDARY,
        )
        self._styled_button(
            parent=self.menu_frame,
            text="-",
            scale=0.05,
            pos=(-0.05, 0, y),
            frameSize=(-0.6, 0.6, -0.6, 0.6),
            command=command,
            extraArgs=[-1 if key == "render_distance" else -5],
        )
        self.menu_labels[key] = self._styled_label(
            parent=self.menu_frame,
            text="",
            scale=0.046,
            pos=(0.18, 0, y),
        )
        self._styled_button(
            parent=self.menu_frame,
            text="+",
            scale=0.05,
            pos=(0.43, 0, y),
            frameSize=(-0.6, 0.6, -0.6, 0.6),
            command=command,
            extraArgs=[1 if key == "render_distance" else 5],
        )

    def update(self, dt: float) -> None:
        self.time_of_day = (self.time_of_day + dt / 600.0) % 1.0

        self._update_lighting()

        # chunk rebuilding stays (but we will assume mesher is expensive already capped)
        self.rebuild_dirty_chunks()

        self.remove_unloaded_chunk_nodes()

        # ❌ REMOVE ALWAYS-ON UI UPDATES
        # self._update_hotbar_text()
        # self._update_inventory_menu()

        # ✔ only update UI when needed
        self._update_hotbar_if_dirty()
        self._update_inventory_if_dirty()

        # timers unchanged
        if self.inventory_message_timer > 0.0:
            self.inventory_message_timer = max(0.0, self.inventory_message_timer - dt)
            if self.inventory_message_timer == 0.0:
                self.inventory_status["text"] = ""

        if self.settings_timer > 0.0:
            self.settings_timer = max(0.0, self.settings_timer - dt)
            if self.settings_timer == 0.0:
                self.settings_text.setText("")

    def _update_hotbar_if_dirty(self):
        player = getattr(self.base, "player_controller", None)
        health = getattr(player, "health", 20)
        hunger = getattr(player, "hunger", 20)

        current_state = (tuple((s.item_id, s.count) for s in self.inventory.hotbar),
                        self.inventory.selected_index,
                        health,
                        hunger)

        if current_state == self._last_hotbar_state:
            return

        self._last_hotbar_state = current_state

        for i, stack in enumerate(self.inventory.hotbar):
            outer, _inner = self.hotbar_slots[i]

            texture = self._slot_icon_texture(stack.item_id) if stack.count > 0 else None
            if texture is None:
                self.hotbar_icons[i].hide()
            else:
                self.hotbar_icons[i].setImage(texture)
                self.hotbar_icons[i].show()

            self.hotbar_labels[i].setText(str(stack.count) if stack.count > 1 else "")

            if i == self.inventory.selected_index:
                outer["frameColor"] = Theme.SLOT_BORDER_SELECTED
                _inner["frameColor"] = Theme.ACCENT_DIM
            else:
                outer["frameColor"] = Theme.SLOT_BORDER
                _inner["frameColor"] = Theme.SLOT_BG

        self.hotbar_status_text.setText(f"♥ {health}    🍗 {hunger}")

    def _update_inventory_if_dirty(self):
        current_state = tuple(
            (getattr(s, "item_id", 0), getattr(s, "count", 0))
            for s in self.inventory.slots
    )

        if current_state == self._last_inventory_state and \
        self.inventory.selected_index == self._last_selected_index:
            return

        self._last_inventory_state = current_state
        self._last_selected_index = self.inventory.selected_index

        for i, ((outer, _inner), label) in enumerate(self.inventory_slots):
            stack = self.inventory.slots[i]

            texture = self._slot_icon_texture(stack.item_id) if stack.count > 0 else None
            if texture is None:
                self.inventory_icons[i].hide()
            else:
                self.inventory_icons[i].setImage(texture)
                self.inventory_icons[i].show()

            label.setText(str(stack.count) if stack.count > 1 else "")

            if i == self.inventory.selected_index:
                outer["frameColor"] = Theme.SLOT_BORDER_SELECTED
                _inner["frameColor"] = Theme.ACCENT_DIM
            else:
                outer["frameColor"] = Theme.SLOT_BORDER
                _inner["frameColor"] = Theme.SLOT_BG

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
            self.menu_outer.show()
        else:
            self.menu_outer.hide()

    def set_inventory_visible(self, visible: bool) -> None:
        """Show or hide the survival inventory."""

        self.inventory_visible = visible
        if visible:
            self._update_inventory_menu()
            self.inventory_outer.show()
        else:
            self.inventory_outer.hide()

    def _craft_recipe(self, recipe_id: str) -> None:
        """Attempt to craft one recipe."""

        success = self.inventory.craft(recipe_id)

        if success:
            self.inventory_status.setText("Crafted successfully")
            self.inventory_status["text_fg"] = Theme.ACCENT
        else:
            self.inventory_status.setText("Missing materials or space")
            self.inventory_status["text_fg"] = Theme.TEXT_SECONDARY

        self.inventory_message_timer = 2.0

        # 🔥 IMPORTANT: force full UI sync (not dirty-based)
        self._force_inventory_refresh()

    def _force_inventory_refresh(self) -> None:
        """Hard refresh inventory UI after crafting or mutation."""

        self._last_inventory_state = None
        self._last_hotbar_state = None
        self._last_selected_index = -1

        self._update_inventory_if_dirty()
        self._update_hotbar_if_dirty()

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
            nodes = self.mesher.build(chunk)
            if not nodes:
                chunk.dirty_for_render = False
                continue

            parent = self.base.render.attachNewNode(f"chunk-{chunk.coord.x}-{chunk.coord.z}")
            for block_id, node in nodes.items():
                child = parent.attachNewNode(node)
                texture = self._slot_icon_texture(block_id)
                if texture is not None:
                    child.setTexture(texture)
                child.setTwoSided(True)
            self.chunk_nodes[chunk.coord] = parent
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
        """Update sun, moon, clouds, and sky colors from time of day."""

        angle = self.time_of_day * math.tau
        daylight = max(0.08, math.sin(angle))

        sky_radius = 500

        # ---------------- SUN POSITION ----------------
        sun_angle = angle

        sun_x = math.cos(sun_angle) * sky_radius
        sun_z = math.sin(sun_angle) * sky_radius

        self.sun_model_np.setPos(sun_x, 0, sun_z)
        self.sun_model_np.setHpr(self.time_of_day * 360.0, -35 - daylight * 45, 0)

        self.sun_model_np.setColor(
            Vec4(0.95 * daylight, 0.88 * daylight, 0.72 * daylight, 1)
        )

        # ---------------- MOON POSITION ----------------
        if hasattr(self, "moon_model_np"):
            moon_angle = sun_angle + math.pi

            moon_x = math.cos(moon_angle) * sky_radius
            moon_z = math.sin(moon_angle) * sky_radius

            moon_light = max(0.05, 1.0 - daylight)

            cam_pos = self.base.camera.getPos(self.base.render)
            self.moon_model_np.setPos(
                cam_pos.x + moon_x, cam_pos.y, cam_pos.z + moon_z
            )
            self.moon_model_np.setHpr(self.time_of_day * 360.0 + 180.0, 25, 0)

            self.moon_model_np.setColor(
                Vec4(0.6 * moon_light, 0.65 * moon_light, 0.8 * moon_light, 1)
            )

            if daylight > 0.25:
                self.moon_model_np.hide()
            else:
                self.moon_model_np.show()

        # ---------------- AMBIENT LIGHT ----------------
        self.ambient_np.node().setColor(
            Vec4(
                0.08 + daylight * 0.28,
                0.09 + daylight * 0.30,
                0.12 + daylight * 0.34,
                1,
            )
        )

        # ---------------- SKY BACKGROUND ----------------
        self.base.setBackgroundColor(
            0.03 + daylight * 0.50,
            0.05 + daylight * 0.65,
            0.09 + daylight * 0.85,
            1,
        )

    def _update_hotbar_text(self) -> None:
        """Minecraft-style hotbar rendering."""

        self._update_hotbar_if_dirty()

    def _format_hotbar_slot(self, index: int, stack) -> str:
        """Return formatted text for a hotbar slot."""

        if stack.count > 0:
            name = self.inventory.item_name(stack.item_id)
            text = f"{index + 1}:{name} x{stack.count}"
        else:
            text = f"{index + 1}:Empty"

        return f"[{text}]" if index == self.inventory.selected_index else text

    def _format_mining_progress(self, player) -> str:
        """Return mining progress text or an empty string."""

        if (
            player is None
            or getattr(player, "mining_target", None) is None
            or player.mining_duration <= 0
        ):
            return ""

        progress = min(
            100,
            int(player.mining_timer / player.mining_duration * 100),
        )

        return f"  Mining:{progress}%"

    def _update_inventory_menu(self) -> None:
        """Refresh inventory UI."""

        self._update_inventory_if_dirty()