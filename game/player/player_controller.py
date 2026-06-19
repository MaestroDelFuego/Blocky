"""File: player_controller.py

Purpose:
    Implements first-person movement, mouse look, collision, and block actions.

Responsibilities:
    * Read local input state.
    * Move a first-person body with gravity and jumping.
    * Rotate the camera from mouse movement.
    * Convert clicks into WorldManager action requests.
    * Avoid direct block mutation.

Dependencies:
    * math for movement vectors.
    * panda3d.core for vector and window pointer APIs.
    * world.world_manager for collision, raycast, and block requests.
    * inventory.inventory_manager for selected block access.

Systems that depend on it:
    * GameManager constructs and updates PlayerController.
    * RenderManager follows the Panda3D camera controlled here.

Future multiplayer considerations:
    PlayerController should later emit input/action commands. The server should
    validate movement and block edits, then send authoritative corrections.
"""

from __future__ import annotations

import math
from typing import Any

from panda3d.core import Vec3, WindowProperties

from inventory.inventory_manager import APPLE, COAL, IRON_ORE_ITEM, InventoryManager
from world.block_registry import BlockRegistry
from world.world_manager import WorldManager


class PlayerController:
    """First-person local player controller.

    Purpose:
        Provides movement, camera control, collision, and block interaction.

    Responsibilities:
        * Track player position and velocity.
        * Capture keyboard and mouse input.
        * Perform AABB collision checks through WorldManager.
        * Place and destroy blocks by calling WorldManager methods.

    Lifecycle:
        Constructed once by GameManager after world and inventory systems.

    Dependencies:
        Depends on Panda3D base/window/camera objects, WorldManager, and
        InventoryManager.

    Threading considerations:
        Main-thread only because Panda3D window and camera APIs are not
        thread-safe.

    Future networking considerations:
        This class should become a command producer in multiplayer, not an
        authority. WorldManager or server responses determine accepted edits.
    """

    def __init__(
        self,
        base: Any,
        world_manager: WorldManager,
        inventory_manager: InventoryManager,
        start_position: tuple[float, float, float] = (0.0, 85.0, 0.0),
    ) -> None:
        """Create the player controller.

        Purpose:
            Initializes player state and input bindings.

        Args:
            base: Panda3D ShowBase-compatible object.
            world_manager: Central world authority.
            inventory_manager: Inventory and hotbar manager.
            start_position: Initial player world position.

        Returns:
            None.

        Side Effects:
            Registers input event handlers and positions the camera.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        self.base = base
        self.world = world_manager
        self.inventory = inventory_manager
        self.position = Vec3(*start_position)
        self.velocity = Vec3(0, 0, 0)
        self.yaw = 0.0
        self.pitch = 0.0
        self.on_ground = False
        self.keys: dict[str, bool] = {}
        self.mouse_sensitivity = 0.12
        self.move_speed = 7.0
        self.jump_speed = 9
        self.gravity = 22.0
        self.camera_relative_movement = True
        self.player_radius = 0.32
        self.player_height = 2.0
        self.eye_height = 1.82
        self.health = 20
        self.hunger = 20
        self.hunger_timer = 0.0
        self.starve_timer = 0.0
        self.heal_timer = 0.0
        self.mining_target: tuple[int, int, int] | None = None
        self.mining_block_id = BlockRegistry.AIR
        self.mining_timer = 0.0
        self.mining_duration = 0.0
        self._bind_inputs()
        self._apply_camera()

    def _bind_inputs(self) -> None:
        """Bind local input events.

        Purpose:
            Captures movement, jump, hotbar, mouse wheel, and block actions.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Registers Panda3D event callbacks.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1), fixed input list.
        """

        for key in ("w", "a", "s", "d", "arrow_up", "arrow_down", "arrow_left", "arrow_right", "space", "shift"):
            self.base.accept(key, self._set_key, [key, True])
            self.base.accept(f"{key}-up", self._set_key, [key, False])
        for index in range(8):
            self.base.accept(str(index + 1), self.inventory.select, [index])
        self.base.accept("wheel_up", self.inventory.scroll, [-1])
        self.base.accept("wheel_down", self.inventory.scroll, [1])
        self.base.accept("mouse1", self.destroy_target_block)
        self.base.accept("mouse3", self.place_target_block)

    def _set_key(self, key: str, pressed: bool) -> None:
        """Set one key state.

        Purpose:
            Maintains continuous input state for the update loop.

        Args:
            key: Input key name.
            pressed: Whether the key is currently pressed.

        Returns:
            None.

        Side Effects:
            Mutates the keys dictionary.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        self.keys[key] = pressed

    def update(self, dt: float) -> None:
        """Advance movement and camera for one frame.

        Purpose:
            Runs first-person input, collision, and camera placement.

        Args:
            dt: Delta time in seconds.

        Returns:
            None.

        Side Effects:
            Mutates player position/velocity and Panda3D camera transform.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(c), where c is the small number of collision cells around the
            player AABB.
        """

        dt = min(dt, 0.1)
        if self.position.y < -8.0:
            self.take_damage(20)
        self._update_mouse_look()
        wish = self._movement_vector()
        speed = self.move_speed * (1.7 if self.keys.get("shift") else 1.0)
        self.velocity.x = wish.x * speed
        self.velocity.z = wish.z * speed
        if self.keys.get("space") and self.on_ground:
            self.velocity.y = self.jump_speed
            self.on_ground = False
        self.velocity.y -= self.gravity * dt
        if wish.lengthSquared() > 0:
            self.hunger_timer += dt
            if self.hunger_timer >= 18.0:
                self.hunger_timer = 0.0
                self.hunger = max(0, self.hunger - 1)
        if self.hunger <= 0:
            self.starve_timer += dt
            if self.starve_timer >= 4.0:
                self.starve_timer = 0.0
                self.take_damage(1)
        else:
            self.starve_timer = 0.0
            if self.hunger >= 18 and self.health < 20:
                self.heal_timer += dt
                if self.heal_timer >= 5.0:
                    self.heal_timer = 0.0
                    self.health = min(20, self.health + 1)
            else:
                self.heal_timer = 0.0
        self._update_mining(dt)
        steps = max(1, int(max(abs(self.velocity.x), abs(self.velocity.y), abs(self.velocity.z)) * dt / 0.25) + 1)
        step_dt = dt / steps
        for _ in range(steps):
            self._move_axis("x", self.velocity.x * step_dt)
            self._move_axis("z", self.velocity.z * step_dt)
            self._move_axis("y", self.velocity.y * step_dt)
        self._apply_camera()

    def _update_mouse_look(self) -> None:
        """Read mouse delta and update view angles.

        Purpose:
            Implements mouse-look camera control.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Recenters the OS pointer and changes yaw/pitch.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        if not self.base.win or not hasattr(self.base.win, "getPointer"):
            return
        pointer = self.base.win.getPointer(0)
        center_x = self.base.win.getXSize() // 2
        center_y = self.base.win.getYSize() // 2
        dx = pointer.getX() - center_x
        dy = pointer.getY() - center_y
        if abs(dx) > center_x or abs(dy) > center_y:
            self.base.win.movePointer(0, center_x, center_y)
            return
        if dx or dy:
            self.yaw = (self.yaw - dx * self.mouse_sensitivity) % 360.0
            self.pitch = max(-89.0, min(89.0, self.pitch - dy * self.mouse_sensitivity))
            self.base.win.movePointer(0, center_x, center_y)

    def _movement_vector(self) -> Vec3:
        """Return normalized horizontal movement direction.

        Purpose:
            Converts WASD state and yaw into a world-space movement vector.

        Args:
            None.

        Returns:
            Panda3D Vec3 with y unused and x/z movement components.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        forward = 1.0 if self.keys.get("w") else 0.0
        forward -= 1.0 if self.keys.get("s") else 0.0
        forward += 1.0 if self.keys.get("arrow_up") else 0.0
        forward -= 1.0 if self.keys.get("arrow_down") else 0.0

        strafe = 1.0 if self.keys.get("d") else 0.0
        strafe -= 1.0 if self.keys.get("a") else 0.0
        strafe += 1.0 if self.keys.get("arrow_right") else 0.0
        strafe -= 1.0 if self.keys.get("arrow_left") else 0.0

        if self.camera_relative_movement:
            yaw_radians = math.radians(self.yaw)
            move = Vec3(
                math.cos(yaw_radians) * strafe - math.sin(yaw_radians) * forward,
                0,
                math.sin(yaw_radians) * strafe + math.cos(yaw_radians) * forward,
            )
        else:
            move = Vec3(strafe, 0, forward)

        if move.lengthSquared() > 0:
            move.normalize()
        return move

    def _move_axis(self, axis: str, amount: float) -> None:
        """Move along one axis with collision.

        Purpose:
            Resolves simple AABB collision one axis at a time.

        Args:
            axis: Axis name, x, y, or z.
            amount: Movement amount in world units.

        Returns:
            None.

        Side Effects:
            Mutates position and velocity.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(c), where c is overlapped block count for the player box.
        """

        if amount == 0:
            return
        original = Vec3(self.position)
        setattr(self.position, axis, getattr(self.position, axis) + amount)
        if self._collides():
            self.position = original
            if axis == "y":
                if amount < 0:
                    fall_speed = abs(self.velocity.y)
                    if fall_speed > 13.0:
                        self.take_damage(int((fall_speed - 12.0) * 0.7))
                    self.on_ground = True
                self.velocity.y = 0
            else:
                setattr(self.velocity, axis, 0)
        elif axis == "y" and amount < 0:
            self.on_ground = False

    def _collides(self) -> bool:
        """Return whether the player's body intersects solid blocks.

        Purpose:
            Keeps movement outside solid terrain.

        Args:
            None.

        Returns:
            True when the player AABB intersects world blocks.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(c), where c is overlapped block count.
        """

        minimum = (
            self.position.x - self.player_radius,
            self.position.y,
            self.position.z - self.player_radius,
        )
        maximum = (
            self.position.x + self.player_radius,
            self.position.y + self.player_height,
            self.position.z + self.player_radius,
        )
        return self.world.collides_aabb(minimum, maximum)

    def _view_direction(self) -> tuple[float, float, float]:
        """Return the camera forward vector.

        Purpose:
            Supplies raycast targeting for block interactions.

        Args:
            None.

        Returns:
            Normalized direction tuple.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        forward = self.base.camera.getQuat(self.base.render).getForward()
        return (forward.x, forward.z, forward.y)

    def destroy_target_block(self) -> None:
        """Destroy the currently targeted block.

        Purpose:
            Turns a mouse click into a WorldManager destruction request.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            May mutate world state through WorldManager.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(r), where r is raycast sample count.
        """

        if getattr(self.base, "settings_menu_open", False) or getattr(self.base.render_manager, "inventory_visible", False):
            return
        hit = self.world.raycast(self.eye_position(), self._view_direction())
        if not hit:
            self._clear_mining()
            return
        block_id = self.world.get_block(*hit[0])
        if self.mining_target != hit[0] or self.mining_block_id != block_id:
            self.mining_target = hit[0]
            self.mining_block_id = block_id
            self.mining_timer = 0.0
            self.mining_duration = self._mining_duration(block_id)

    def _update_mining(self, dt: float) -> None:
        """Advance block mining for the current target."""

        if self.mining_target is None:
            return
        hit = self.world.raycast(self.eye_position(), self._view_direction())
        if not hit or hit[0] != self.mining_target or self.world.get_block(*self.mining_target) != self.mining_block_id:
            self._clear_mining()
            return
        self.mining_timer += dt
        if self.mining_timer < self.mining_duration:
            return
        block_id = self.mining_block_id
        if self.world.destroy_block(self.mining_target):
            self.inventory.add_item(self._drop_for_block(block_id), self._drop_count_for_block(block_id))
        self._clear_mining()

    def _clear_mining(self) -> None:
        """Clear the active mining target."""

        self.mining_target = None
        self.mining_block_id = BlockRegistry.AIR
        self.mining_timer = 0.0
        self.mining_duration = 0.0

    def _mining_duration(self, block_id: int) -> float:
        """Return seconds needed to break a block with the selected item."""

        hardness = {
            BlockRegistry.LEAVES: 0.35,
            BlockRegistry.SNOW: 0.35,
            BlockRegistry.DIRT: 0.55,
            BlockRegistry.GRASS: 0.65,
            BlockRegistry.SAND: 0.55,
            BlockRegistry.CLAY: 0.75,
            BlockRegistry.WOOD: 1.25,
            BlockRegistry.PLANKS: 1.05,
            BlockRegistry.DOOR_CLOSED: 1.0,
            BlockRegistry.DOOR_OPEN: 1.0,
            BlockRegistry.CACTUS: 0.8,
            BlockRegistry.STONE: 1.8,
            BlockRegistry.COBBLESTONE: 1.9,
            BlockRegistry.COAL_ORE: 2.2,
            BlockRegistry.IRON_ORE: 2.5,
            BlockRegistry.BRICKS: 2.0,
            BlockRegistry.GLASS: 0.4,
        }.get(block_id, 1.0)
        speed = self.inventory.tool_speed(self.inventory.selected_item_id(), block_id)
        return max(0.12, hardness / speed)

    def place_target_block(self) -> None:
        """Place the selected block next to the target block.

        Purpose:
            Turns a mouse click into a WorldManager placement request.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            May mutate world state through WorldManager.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(r), where r is raycast sample count.
        """

        if getattr(self.base, "settings_menu_open", False) or getattr(self.base.render_manager, "inventory_visible", False):
            return
        selected_item = self.inventory.selected_item_id()
        food_value = self.inventory.food_value(selected_item)
        if food_value and self.hunger < 20:
            if self.inventory.consume_selected():
                self.hunger = min(20, self.hunger + food_value)
            return
        hit = self.world.raycast(self.eye_position(), self._view_direction())
        if hit:
            target_block = self.world.get_block(*hit[0])
            if target_block in (BlockRegistry.DOOR_CLOSED, BlockRegistry.DOOR_OPEN):
                self.world.set_block(*hit[0], BlockRegistry.DOOR_OPEN if target_block == BlockRegistry.DOOR_CLOSED else BlockRegistry.DOOR_CLOSED)
                return
        block_id = self.inventory.selected_block_id()
        if block_id == 0:
            return
        if hit:
            place_position = hit[1]
            if not self._block_overlaps_player(place_position):
                if self.world.place_block(place_position, block_id):
                    self.inventory.consume_selected()

    def _drop_for_block(self, block_id: int) -> int:
        """Return the item dropped when a block is broken."""

        drops = {
            BlockRegistry.GRASS: BlockRegistry.DIRT,
            BlockRegistry.STONE: BlockRegistry.COBBLESTONE,
            BlockRegistry.LEAVES: APPLE,
            BlockRegistry.COAL_ORE: COAL,
            BlockRegistry.IRON_ORE: IRON_ORE_ITEM,
            BlockRegistry.DOOR_OPEN: BlockRegistry.DOOR_CLOSED,
        }
        return drops.get(block_id, block_id)

    def _drop_count_for_block(self, block_id: int) -> int:
        """Return the amount dropped when a block is broken."""

        return 1 if block_id != BlockRegistry.LEAVES else 1

    def _block_overlaps_player(self, position: tuple[int, int, int]) -> bool:
        """Return whether a block position overlaps the player body.

        Purpose:
            Prevents placing blocks inside the player.

        Args:
            position: World block coordinate.

        Returns:
            True if the target block would intersect the player AABB.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        x, y, z = position
        return (
            self.position.x + self.player_radius > x
            and self.position.x - self.player_radius < x + 1
            and self.position.y + self.player_height > y
            and self.position.y < y + 1
            and self.position.z + self.player_radius > z
            and self.position.z - self.player_radius < z + 1
        )

    def eye_position(self) -> tuple[float, float, float]:
        """Return camera eye position.

        Purpose:
            Provides raycast origin and save data.

        Args:
            None.

        Returns:
            World-space eye position tuple.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        return (self.position.x, self.position.y + self.eye_height, self.position.z)

    def _apply_camera(self) -> None:
        """Apply player transform to the Panda3D camera.

        Purpose:
            Updates first-person camera position and orientation.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Mutates Panda3D camera transform.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        eye_x, eye_y, eye_z = self.eye_position()
        self.base.camera.setPos(eye_x, eye_z, eye_y)
        self.base.camera.setHpr(self.yaw, self.pitch, 0)

    def apply_saved_state(self, data: dict[str, object]) -> None:
        """Restore player transform from saved state.

        Purpose:
            Loads position and view angles.

        Args:
            data: JSON-compatible player state.

        Returns:
            None.

        Side Effects:
            Mutates player transform and camera transform.

        Raises:
            KeyError: If expected fields are missing.

        Performance considerations:
            O(1).
        """

        position = data["position"]
        self.position = Vec3(float(position[0]), float(position[1]), float(position[2]))
        raw_yaw = float(data.get("yaw", 0.0))
        raw_pitch = float(data.get("pitch", 0.0))
        self.yaw = raw_yaw % 360.0
        self.pitch = max(-89.0, min(89.0, raw_pitch))
        self.health = max(0, min(20, int(data.get("health", self.health))))
        self.hunger = max(0, min(20, int(data.get("hunger", self.hunger))))
        if abs(raw_yaw) > 10000.0 and abs(raw_pitch) >= 88.0:
            self.pitch = 0.0
        self._apply_camera()

    def move_to_safe_spawn(self) -> None:
        """Place the player above the nearest loaded solid surface."""

        self.position = Vec3(*self.world.safe_spawn_near(self.position.x, self.position.z))
        self.velocity = Vec3(0, 0, 0)
        self.on_ground = False
        self.pitch = max(-45.0, min(45.0, self.pitch))
        self._apply_camera()

    def take_damage(self, amount: int) -> None:
        """Apply survival damage and respawn on death."""

        if amount <= 0:
            return
        self.health = max(0, self.health - amount)
        if self.health == 0:
            self.health = 20
            self.hunger = 20
            self.move_to_safe_spawn()

    def rescue_if_unsafe(self) -> None:
        """Move the player to terrain if the saved position is unplayable."""

        if self._collides() or self.position.y < 1.0:
            self.move_to_safe_spawn()
            return
        surface = self.world.surface_y(math.floor(self.position.x), math.floor(self.position.z))
        if surface is not None and self.position.y < surface:
            self.move_to_safe_spawn()
        elif surface is not None and self.position.y >= 88.0 and self.position.y - surface > 8.0:
            self.move_to_safe_spawn()

    def to_dict(self) -> dict[str, object]:
        """Serialize player state.

        Purpose:
            Provides SaveManager with local player state.

        Args:
            None.

        Returns:
            JSON-compatible player snapshot.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        return {
            "position": [self.position.x, self.position.y, self.position.z],
            "yaw": self.yaw,
            "pitch": self.pitch,
            "health": self.health,
            "hunger": self.hunger,
        }

    def capture_mouse(self) -> None:
        """Request hidden relative-style mouse behavior.

        Purpose:
            Keeps the cursor centered for mouse look.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Changes window cursor visibility and pointer position.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        if not self.base.win or not hasattr(self.base.win, "requestProperties"):
            return
        props = WindowProperties()
        props.setCursorHidden(True)
        self.base.win.requestProperties(props)
        self.base.win.movePointer(0, self.base.win.getXSize() // 2, self.base.win.getYSize() // 2)
