"""File: inventory_manager.py

Purpose:
    Manages inventory slots and hotbar selection for placeable blocks.

Responsibilities:
    * Store item stacks.
    * Track selected hotbar slot.
    * Provide the currently placeable block ID.
    * Serialize local inventory state.

Dependencies:
    * dataclasses for item stack data.
    * world.block_registry for default block IDs.

Systems that depend on it:
    * PlayerController asks which block to place.
    * RenderManager displays hotbar UI.
    * SaveManager persists local player inventory state.

Future multiplayer considerations:
    Inventory authority should move to the dedicated server. The client should
    later send item-use requests and render server-confirmed inventory state.
"""

from __future__ import annotations

from dataclasses import dataclass

from world.block_registry import BlockRegistry


APPLE = 100
BREAD = 101
COAL = 102
IRON_ORE_ITEM = 103
WOOD_PICKAXE = 104
WOOD_AXE = 105
WOOD_SWORD = 106

ITEM_NAMES = {
    APPLE: "Apple",
    BREAD: "Bread",
    COAL: "Coal",
    IRON_ORE_ITEM: "Raw Iron",
    WOOD_PICKAXE: "Wood Pickaxe",
    WOOD_AXE: "Wood Axe",
    WOOD_SWORD: "Wood Sword",
}

CRAFTING_RECIPES: dict[str, tuple[tuple[tuple[int, int], ...], tuple[int, int]]] = {
    "torch": (((COAL, 1), (BlockRegistry.WOOD, 1)), (BlockRegistry.TORCH, 4)),
    "bed": (((BlockRegistry.PLANKS, 3), (BlockRegistry.LEAVES, 3)), (BlockRegistry.BED, 1)),
    "furnace": (((BlockRegistry.STONE, 8),), (BlockRegistry.FURNACE, 1)),
    "ladder": (((BlockRegistry.WOOD, 7),), (BlockRegistry.LADDER, 3)),
    "chest": (((BlockRegistry.PLANKS, 8),), (BlockRegistry.CHEST, 1)),
    "bookshelf": (((BlockRegistry.PLANKS, 6), (BlockRegistry.WOOD, 3)), (BlockRegistry.BOOKSHELF, 1)),
    "stone_slab": (((BlockRegistry.STONE, 3),), (BlockRegistry.STONE_SLAB, 6)),
    "wood_stairs": (((BlockRegistry.PLANKS, 6),), (BlockRegistry.WOOD_STAIRS, 4)),
    "planks": (((BlockRegistry.WOOD, 1),), (BlockRegistry.PLANKS, 4)),
    "bread": (((APPLE, 2),), (BREAD, 1)),
    "glass": (((BlockRegistry.SAND, 2), (COAL, 1)), (BlockRegistry.GLASS, 2)),
    "bricks": (((BlockRegistry.CLAY, 4),), (BlockRegistry.BRICKS, 2)),
    "cobble": (((BlockRegistry.STONE, 1),), (BlockRegistry.COBBLESTONE, 1)),
    "door": (((BlockRegistry.PLANKS, 3),), (BlockRegistry.DOOR_CLOSED, 1)),
    "pickaxe": (((BlockRegistry.PLANKS, 3),), (WOOD_PICKAXE, 1)),
    "axe": (((BlockRegistry.PLANKS, 3),), (WOOD_AXE, 1)),
    "sword": (((BlockRegistry.PLANKS, 2),), (WOOD_SWORD, 1)),
}

CRAFTING_ORDER: tuple[str, ...] = (
    "torch",
    "bed",
    "furnace",
    "ladder",
    "chest",
    "bookshelf",
    "stone_slab",
    "wood_stairs",
    "planks",
    "bread",
    "glass",
    "bricks",
    "cobble",
    "door",
    "pickaxe",
    "axe",
    "sword",
)

FOOD_VALUES = {
    APPLE: 4,
    BREAD: 6,
}

PLACEABLE_BLOCKS = {
    block_id
    for block_id in (
        BlockRegistry.GRASS,
        BlockRegistry.DIRT,
        BlockRegistry.STONE,
        BlockRegistry.SAND,
        BlockRegistry.WOOD,
        BlockRegistry.LEAVES,
        BlockRegistry.WATER,
        BlockRegistry.COBBLESTONE,
        BlockRegistry.PLANKS,
        BlockRegistry.GLASS,
        BlockRegistry.BRICKS,
        BlockRegistry.CLAY,
        BlockRegistry.SNOW,
        BlockRegistry.CACTUS,
        BlockRegistry.DOOR_CLOSED,
        BlockRegistry.TORCH,
        BlockRegistry.BED,
        BlockRegistry.FURNACE,
        BlockRegistry.LADDER,
        BlockRegistry.CHEST,
        BlockRegistry.BOOKSHELF,
        BlockRegistry.STONE_SLAB,
        BlockRegistry.WOOD_STAIRS,
    )
}

TOOL_ITEMS = {WOOD_PICKAXE, WOOD_AXE, WOOD_SWORD}


@dataclass
class ItemStack:
    """One inventory slot.

    Purpose:
        Stores an item/block ID and count.

    Responsibilities:
        * Represent empty and non-empty inventory slots.
        * Keep stack data serializable.

    Lifecycle:
        Created by InventoryManager during startup and restored from saves.

    Dependencies:
        Uses dataclasses only.

    Threading considerations:
        Mutated on the main thread in this client.

    Future networking considerations:
        Server should later own stack counts and send authoritative snapshots.
    """

    item_id: int
    count: int

    @property
    def block_id(self) -> int:
        """Backward-compatible alias for old save/UI code."""

        return self.item_id


class InventoryManager:
    """Local inventory and hotbar manager.

    Purpose:
        Tracks the player's available placeable blocks.

    Responsibilities:
        * Initialize a creative-style hotbar.
        * Change selected slot from number keys or scroll.
        * Provide selected block IDs to player action code.
        * Serialize and deserialize inventory state.

    Lifecycle:
        Constructed once by GameManager and updated by PlayerController input.

    Dependencies:
        Depends on BlockRegistry IDs.

    Threading considerations:
        Main-thread only in the current single-player client.

    Future networking considerations:
        This is currently client-authoritative for convenience. In multiplayer,
        the server validates item use and broadcasts inventory updates.
    """

    HOTBAR_SIZE = 8
    INVENTORY_SIZE = 24
    MAX_STACK = 64

    def __init__(self, block_registry: BlockRegistry | None = None) -> None:
        """Create a default creative hotbar.

        Purpose:
            Gives the player immediate access to all implemented block types.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Initializes slot data.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(HOTBAR_SIZE).
        """

        self.blocks = block_registry or BlockRegistry()
        self.slots: list[ItemStack] = [ItemStack(BlockRegistry.AIR, 0) for _ in range(self.INVENTORY_SIZE)]
        self.add_item(BlockRegistry.WOOD, 8)
        self.add_item(BlockRegistry.DIRT, 16)
        self.add_item(APPLE, 3)
        self.add_item(WOOD_PICKAXE, 1)
        self.selected_index = 0

    @property
    def hotbar(self) -> list[ItemStack]:
        """Return the first inventory row as the hotbar."""

        return self.slots[: self.HOTBAR_SIZE]

    def select(self, index: int) -> None:
        """Select a hotbar slot.

        Purpose:
            Updates the active item slot from direct number-key input.

        Args:
            index: Zero-based hotbar index.

        Returns:
            None.

        Side Effects:
            Changes selected_index when index is valid.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        if 0 <= index < self.HOTBAR_SIZE:
            self.selected_index = index

    def scroll(self, delta: int) -> None:
        """Move hotbar selection.

        Purpose:
            Supports mouse wheel item selection.

        Args:
            delta: Positive or negative slot movement.

        Returns:
            None.

        Side Effects:
            Changes selected_index.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        self.selected_index = (self.selected_index + delta) % self.HOTBAR_SIZE

    def selected_stack(self) -> ItemStack:
        """Return the selected hotbar stack.

        Purpose:
            Lets player and UI systems inspect the active item.

        Args:
            None.

        Returns:
            Selected ItemStack.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        return self.slots[self.selected_index]

    def selected_block_id(self) -> int:
        """Return the selected placeable block ID.

        Purpose:
            Supplies block placement requests with the active block type.

        Args:
            None.

        Returns:
            Numeric block ID, or air if the slot is empty.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1).
        """

        stack = self.selected_stack()
        return stack.item_id if stack.count > 0 and stack.item_id in PLACEABLE_BLOCKS else BlockRegistry.AIR

    def selected_item_id(self) -> int:
        """Return the selected item ID, or air for an empty slot."""

        stack = self.selected_stack()
        return stack.item_id if stack.count > 0 else BlockRegistry.AIR

    def item_name(self, item_id: int) -> str:
        """Return a display name for block and non-block items."""

        if item_id in ITEM_NAMES:
            return ITEM_NAMES[item_id]
        return self.blocks.get(item_id).display_name

    def add_item(self, item_id: int, count: int = 1) -> int:
        """Add items to inventory and return the leftover count."""

        if item_id == BlockRegistry.AIR or count <= 0:
            return 0
        for stack in self.slots:
            if stack.item_id == item_id and stack.count < self.MAX_STACK:
                moved = min(count, self.MAX_STACK - stack.count)
                stack.count += moved
                count -= moved
                if count == 0:
                    return 0
        for stack in self.slots:
            if stack.count <= 0:
                moved = min(count, self.MAX_STACK)
                stack.item_id = item_id
                stack.count = moved
                count -= moved
                if count == 0:
                    return 0
        return count

    def can_accept(self, item_id: int, count: int = 1) -> bool:
        """Return whether the inventory has room for an item stack."""

        if item_id == BlockRegistry.AIR or count <= 0:
            return True
        remaining = count
        for stack in self.slots:
            if stack.item_id == item_id:
                remaining -= max(0, self.MAX_STACK - stack.count)
            elif stack.count <= 0:
                remaining -= self.MAX_STACK
            if remaining <= 0:
                return True
        return False

    def remove_item(self, item_id: int, count: int = 1) -> bool:
        """Remove items from inventory if enough are available."""

        if self.count_item(item_id) < count:
            return False
        for stack in self.slots:
            if stack.item_id != item_id:
                continue
            moved = min(count, stack.count)
            stack.count -= moved
            count -= moved
            if stack.count == 0:
                stack.item_id = BlockRegistry.AIR
            if count == 0:
                return True
        return True

    def consume_selected(self, count: int = 1) -> bool:
        """Consume items from the selected slot."""

        stack = self.selected_stack()
        if stack.count < count or stack.item_id == BlockRegistry.AIR:
            return False
        stack.count -= count
        if stack.count == 0:
            stack.item_id = BlockRegistry.AIR
        return True

    def count_item(self, item_id: int) -> int:
        """Return total inventory count for one item ID."""

        return sum(stack.count for stack in self.slots if stack.item_id == item_id)

    def food_value(self, item_id: int) -> int:
        """Return hunger restored by an item."""

        return FOOD_VALUES.get(item_id, 0)

    def tool_speed(self, item_id: int, block_id: int) -> float:
        """Return block-breaking speed multiplier for the selected item."""

        if item_id == WOOD_PICKAXE and block_id in {
            BlockRegistry.STONE,
            BlockRegistry.COBBLESTONE,
            BlockRegistry.COAL_ORE,
            BlockRegistry.IRON_ORE,
            BlockRegistry.BRICKS,
            BlockRegistry.CLAY,
        }:
            return 4.0
        if item_id == WOOD_AXE and block_id in {BlockRegistry.WOOD, BlockRegistry.PLANKS, BlockRegistry.DOOR_CLOSED, BlockRegistry.DOOR_OPEN}:
            return 4.0
        if item_id == WOOD_AXE and block_id in {BlockRegistry.CHEST, BlockRegistry.BED, BlockRegistry.BOOKSHELF, BlockRegistry.WOOD_STAIRS}:
            return 4.0
        if item_id == WOOD_SWORD and block_id in {BlockRegistry.LEAVES, BlockRegistry.CACTUS}:
            return 3.0
        if item_id == WOOD_PICKAXE and block_id in {BlockRegistry.FURNACE, BlockRegistry.STONE_SLAB}:
            return 4.0
        if item_id in TOOL_ITEMS:
            return 1.4
        return 1.0

    def craft(self, recipe_id: str) -> bool:
        """Craft a small survival recipe."""

        recipe = CRAFTING_RECIPES.get(recipe_id)
        if recipe is None:
            return False
        ingredients, result = recipe
        if any(self.count_item(item_id) < count for item_id, count in ingredients):
            return False
        if not self.can_accept(result[0], result[1]):
            return False
        for item_id, count in ingredients:
            self.remove_item(item_id, count)
        leftover = self.add_item(result[0], result[1])
        return leftover == 0

    def to_dict(self) -> dict[str, object]:
        """Serialize inventory state.

        Purpose:
            Persists hotbar contents and selection.

        Args:
            None.

        Returns:
            JSON-compatible inventory dictionary.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(n), where n is hotbar slot count.
        """

        return {
            "selected_index": self.selected_index,
            "slots": [{"item_id": stack.item_id, "count": stack.count} for stack in self.slots],
            "hotbar": [{"block_id": stack.item_id, "count": stack.count} for stack in self.hotbar],
        }

    def load_dict(self, data: dict[str, object]) -> None:
        """Load inventory state.

        Purpose:
            Restores hotbar contents from saved player data.

        Args:
            data: JSON-compatible inventory dictionary.

        Returns:
            None.

        Side Effects:
            Replaces hotbar and selection state.

        Raises:
            KeyError: If required fields are missing.

        Performance considerations:
            O(n), where n is saved hotbar slot count.
        """

        saved_slots = data.get("slots", data.get("hotbar", []))
        if saved_slots and all(int(item.get("count", 0)) >= 999 for item in saved_slots if int(item.get("block_id", item.get("item_id", 0))) != BlockRegistry.AIR):
            return
        loaded = []
        for item in saved_slots:
            item_id = int(item.get("item_id", item.get("block_id", BlockRegistry.AIR)))
            loaded.append(ItemStack(item_id, max(0, min(self.MAX_STACK, int(item["count"])))))
        self.slots = (loaded + [ItemStack(BlockRegistry.AIR, 0) for _ in range(self.INVENTORY_SIZE)])[: self.INVENTORY_SIZE]
        self.selected_index = max(0, min(int(data["selected_index"]), self.HOTBAR_SIZE - 1))
