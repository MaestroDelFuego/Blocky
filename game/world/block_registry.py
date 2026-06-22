"""File: block_registry.py

Purpose:
    Defines every block type and stable block identifier used by the game.

Responsibilities:
    * Store immutable block metadata.
    * Provide lookup by numeric ID and string name.
    * Mark collision, transparency, liquid, and render color rules.
    * Keep block IDs stable for saves and future network payloads.

Dependencies:
    * dataclasses for immutable block definitions.

Systems that depend on it:
    * TerrainGenerator chooses block IDs from this registry.
    * Chunk stores block IDs from this registry.
    * WorldManager validates block placement and destruction.
    * RenderManager colors and culls block faces using registry metadata.
    * InventoryManager exposes placeable block IDs in the hotbar.

Future multiplayer considerations:
    Numeric block IDs are protocol-facing data. Once saves or network messages
    exist, IDs must not be reordered. A future server can use the same registry
    to validate client block placement requests.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BlockDefinition:
    """Immutable metadata for one block type.

    Purpose:
        Describes simulation and rendering behavior for a block ID.

    Responsibilities:
        * Identify the block with a stable ID and name.
        * Describe whether the block collides, occludes faces, or behaves as a
          liquid.
        * Provide a simple RGBA color for the current offline renderer.

    Lifecycle:
        Created when BlockRegistry is constructed and then treated as read-only
        for the lifetime of the process.

    Dependencies:
        Uses only built-in scalar values and tuples.

    Threading considerations:
        Immutable, so it is safe for future worker threads to read.

    Future networking considerations:
        The id field is the value that should be serialized in chunk payloads.
        The name is useful for tools and debugging but should not replace the
        stable numeric ID in future protocols.
    """

    id: int
    name: str
    display_name: str
    solid: bool
    transparent: bool
    liquid: bool
    color: tuple[float, float, float, float]


class BlockRegistry:
    """Central catalog of all known block types.

    Purpose:
        Provides a stable source of block metadata to all systems.

    Responsibilities:
        * Register built-in block definitions.
        * Resolve blocks by ID and name.
        * Expose convenience IDs for common block types.

    Lifecycle:
        Constructed once by GameManager and shared with terrain, world,
        inventory, and rendering systems.

    Dependencies:
        Depends on BlockDefinition.

    Threading considerations:
        Read-only after construction. Future dynamic mod loading must create a
        synchronized registration phase before worker threads start.

    Future networking considerations:
        Both client and server must share the same registry version. New blocks
        should append IDs rather than changing existing values.
    """

    AIR = 0
    GRASS = 1
    DIRT = 2
    STONE = 3
    SAND = 4
    WOOD = 5
    LEAVES = 6
    WATER = 7
    COBBLESTONE = 8
    COAL_ORE = 9
    IRON_ORE = 10
    PLANKS = 11
    GLASS = 12
    BRICKS = 13
    CLAY = 14
    SNOW = 15
    CACTUS = 16
    DOOR_CLOSED = 17
    DOOR_OPEN = 18
    TORCH = 19
    BED = 20
    FURNACE = 21
    LADDER = 22
    CHEST = 23
    BOOKSHELF = 24
    STONE_SLAB = 25
    WOOD_STAIRS = 26

    def __init__(self) -> None:
        """Create the built-in block catalog.

        Purpose:
            Registers the default Minecraft-inspired block set.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Populates internal dictionaries.

        Raises:
            ValueError: If duplicate IDs or names are registered.

        Performance considerations:
            O(n), where n is the number of registered block types.
        """

        self._by_id: dict[int, BlockDefinition] = {}
        self._by_name: dict[str, BlockDefinition] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register the built-in block types.

        Purpose:
            Keeps constructor logic compact and makes default registration easy
            to audit.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            Adds block definitions to lookup tables.

        Raises:
            ValueError: If a definition conflicts with an existing ID or name.

        Performance considerations:
            O(1), because the default block list is fixed.
        """

        self.register(BlockDefinition(0, "air", "Air", False, True, False, (0, 0, 0, 0)))
        self.register(BlockDefinition(1, "grass", "Grass", True, False, False, (0.26, 0.62, 0.22, 1)))
        self.register(BlockDefinition(2, "dirt", "Dirt", True, False, False, (0.45, 0.28, 0.13, 1)))
        self.register(BlockDefinition(3, "stone", "Stone", True, False, False, (0.46, 0.48, 0.50, 1)))
        self.register(BlockDefinition(4, "sand", "Sand", True, False, False, (0.82, 0.75, 0.48, 1)))
        self.register(BlockDefinition(5, "wood", "Wood", True, False, False, (0.43, 0.24, 0.10, 1)))
        self.register(BlockDefinition(6, "leaves", "Leaves", True, True, False, (0.16, 0.45, 0.14, 0.88)))
        self.register(BlockDefinition(7, "water", "Water", False, True, True, (0.14, 0.36, 0.75, 0.62)))
        self.register(BlockDefinition(8, "cobblestone", "Cobble", True, False, False, (0.36, 0.37, 0.38, 1)))
        self.register(BlockDefinition(9, "coal_ore", "Coal Ore", True, False, False, (0.28, 0.29, 0.30, 1)))
        self.register(BlockDefinition(10, "iron_ore", "Iron Ore", True, False, False, (0.58, 0.47, 0.36, 1)))
        self.register(BlockDefinition(11, "planks", "Planks", True, False, False, (0.66, 0.46, 0.22, 1)))
        self.register(BlockDefinition(12, "glass", "Glass", True, True, False, (0.68, 0.87, 0.92, 0.38)))
        self.register(BlockDefinition(13, "bricks", "Bricks", True, False, False, (0.55, 0.20, 0.15, 1)))
        self.register(BlockDefinition(14, "clay", "Clay", True, False, False, (0.48, 0.55, 0.58, 1)))
        self.register(BlockDefinition(15, "snow", "Snow", True, False, False, (0.92, 0.96, 1.00, 1)))
        self.register(BlockDefinition(16, "cactus", "Cactus", True, False, False, (0.12, 0.42, 0.16, 1)))
        self.register(BlockDefinition(17, "door_closed", "Door", True, False, False, (0.50, 0.29, 0.12, 1)))
        self.register(BlockDefinition(18, "door_open", "Open Door", False, True, False, (0.50, 0.29, 0.12, 0.50)))
        self.register(BlockDefinition(19, "torch", "Torch", False, True, False, (0.96, 0.80, 0.28, 1.0)))
        self.register(BlockDefinition(20, "bed", "Bed", True, False, False, (0.77, 0.24, 0.26, 1.0)))
        self.register(BlockDefinition(21, "furnace", "Furnace", True, False, False, (0.33, 0.34, 0.36, 1.0)))
        self.register(BlockDefinition(22, "ladder", "Ladder", False, True, False, (0.61, 0.44, 0.21, 1.0)))
        self.register(BlockDefinition(23, "chest", "Chest", True, False, False, (0.58, 0.34, 0.11, 1.0)))
        self.register(BlockDefinition(24, "bookshelf", "Bookshelf", True, False, False, (0.63, 0.48, 0.25, 1.0)))
        self.register(BlockDefinition(25, "stone_slab", "Stone Slab", True, False, False, (0.49, 0.50, 0.52, 1.0)))
        self.register(BlockDefinition(26, "wood_stairs", "Wood Stairs", True, False, False, (0.46, 0.26, 0.12, 1.0)))

    def register(self, definition: BlockDefinition) -> None:
        """Add one block definition to the registry.

        Purpose:
            Provides one validation point for built-in and future modded blocks.

        Args:
            definition: Block metadata to register.

        Returns:
            None.

        Side Effects:
            Mutates registry lookup tables during setup.

        Raises:
            ValueError: If the block ID or name is already used.

        Performance considerations:
            O(1) dictionary insertion.
        """

        if definition.id in self._by_id:
            raise ValueError(f"Duplicate block id: {definition.id}")
        if definition.name in self._by_name:
            raise ValueError(f"Duplicate block name: {definition.name}")
        self._by_id[definition.id] = definition
        self._by_name[definition.name] = definition

    def get(self, block_id: int) -> BlockDefinition:
        """Return block metadata by numeric ID.

        Purpose:
            Converts stored chunk IDs into simulation/render metadata.

        Args:
            block_id: Stable numeric block identifier.

        Returns:
            BlockDefinition for the ID, or air for unknown IDs.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(1) dictionary lookup.
        """

        return self._by_id.get(block_id, self._by_id[self.AIR])

    def get_by_name(self, name: str) -> BlockDefinition:
        """Return block metadata by string name.

        Purpose:
            Supports developer tools and future data-driven content.

        Args:
            name: Registered block name.

        Returns:
            Matching BlockDefinition.

        Side Effects:
            None.

        Raises:
            KeyError: If the name is unknown.

        Performance considerations:
            O(1) dictionary lookup.
        """

        return self._by_name[name]

    def all_blocks(self) -> tuple[BlockDefinition, ...]:
        """Return all registered blocks sorted by ID.

        Purpose:
            Supports documentation, UI, inventory setup, and debugging.

        Args:
            None.

        Returns:
            Tuple of block definitions sorted by numeric ID.

        Side Effects:
            None.

        Raises:
            No expected exceptions.

        Performance considerations:
            O(n log n), where n is block type count.
        """

        return tuple(sorted(self._by_id.values(), key=lambda block: block.id))
