"""File: main.py

Purpose:
    Local client entry point for the Panda3D voxel sandbox.

Responsibilities:
    * Store immutable startup configuration in AppConfig.
    * Apply Panda3D process configuration before ShowBase is constructed.
    * Create the top-level GameManager.
    * Provide a smoke-test path that verifies startup without entering the
      interactive render loop.

Dependencies:
    * dataclasses for immutable configuration.
    * pathlib for stable project-root discovery.
    * panda3d.core.loadPrcFileData for engine configuration.
    * game_manager.GameManager for client orchestration.

Systems that depend on it:
    * Command-line launch workflows.
    * Local development smoke tests.
    * Future desktop packaging scripts.

Future multiplayer considerations:
    This file is intentionally client-only. A future dedicated server should
    have a separate entry point that does not import Panda3D rendering systems.
    Shared simulation systems must live outside this module so they can be used
    by both the client and the eventual server process.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import sys
from pathlib import Path

from panda3d.core import loadPrcFileData


PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class AppConfig:
    """Static application configuration applied before Panda3D starts.

    Purpose:
        Defines the local client settings that must be known before Panda3D's
        ShowBase object is created.

    Responsibilities:
        * Keep startup settings immutable for predictable initialization.
        * Describe window, frame pacing, texture filtering, and cursor behavior.
        * Allow tests to request an offscreen window type.

    Lifecycle:
        Created once by main() and passed into create_game(). It is then held by
        GameManager for diagnostics and future settings screens.

    Dependencies:
        Uses only dataclasses. It deliberately does not import gameplay systems.

    Threading considerations:
        Immutable after construction, so it can be safely read by future worker
        tasks without locking.

    Future networking considerations:
        Client startup settings should remain separate from future server
        settings. Network-relevant configuration such as ports, tick rates, and
        authentication should be introduced in a dedicated server config type.
    """

    window_title: str = "Voxel Sandbox"
    window_width: int = 1920
    window_height: int = 1080
    target_fps: int = 0
    show_frame_rate_meter: bool = True
    sync_video: bool = False
    cursor_hidden: bool = True
    window_type: str = "onscreen"


def apply_engine_config(config: AppConfig) -> None:
    """Apply Panda3D configuration before ShowBase is constructed.

    Purpose:
        Converts AppConfig values into Panda3D PRC options before any Panda3D
        window or graphics pipe is initialized.

    Args:
        config: Immutable startup settings for the local game client.

    Returns:
        None.

    Side Effects:
        Updates Panda3D's process-level configuration registry.

    Raises:
        No expected runtime exceptions.

    Performance considerations:
        O(1), because the number of configuration keys is fixed.
    """

    cursor_hidden = "#t" if config.cursor_hidden else "#f"
    show_fps = "#t" if config.show_frame_rate_meter else "#f"
    sync_video = "#t" if config.sync_video else "#f"

    loadPrcFileData(
        "",
        "\n".join(
            tuple(
                line
                for line in (
                    f"window-title {config.window_title}",
                    f"win-size {config.window_width} {config.window_height}",
                    f"window-type {config.window_type}",
                    f"show-frame-rate-meter {show_fps}",
                    f"sync-video {sync_video}",
                    f"cursor-hidden {cursor_hidden}",
                    "textures-power-2 none",
                    "texture-minfilter nearest",
                    "texture-magfilter nearest",
                    "gl-coordinate-system default",
                )
            )
            + ((f"clock-frame-rate {config.target_fps}",) if config.target_fps > 0 else ())
        ),
    )


def create_game(config: AppConfig):
    """Create the GameManager after engine configuration is in place.

    Purpose:
        Builds the top-level client coordinator after low-level engine settings
        have been applied.

    Args:
        config: Startup settings passed to the top-level game manager.

    Returns:
        An initialized GameManager instance.

    Side Effects:
        Imports and constructs the client game stack.

    Raises:
        ModuleNotFoundError: If game_manager.py is missing.

    Performance considerations:
        O(1) for the entry point; subsystem work is delegated to GameManager.
    """

    apply_engine_config(config)

    from game_manager import GameManager

    return GameManager(project_root=PROJECT_ROOT, app_config=config)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for local development.

    Purpose:
        Provides a small command-line surface for smoke testing without opening
        a persistent game window.

    Args:
        argv: Optional argument list. When None, argparse reads sys.argv.

    Returns:
        Parsed argparse namespace.

    Side Effects:
        Reads process command-line arguments when argv is None.

    Raises:
        SystemExit: If invalid arguments are supplied.

    Performance considerations:
        O(n), where n is the number of command-line tokens.
    """

    parser = argparse.ArgumentParser(description="Run the voxel sandbox client.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Create and tear down the game shell without entering the main loop.",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Start with the performance debug overlay enabled.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the local Panda3D client.

    Purpose:
        Starts the interactive client or performs a one-shot startup smoke test.

    Args:
        argv: Optional command-line argument list for tests and launch scripts.

    Returns:
        Process exit code. Returns 0 after the Panda3D loop exits normally.

    Side Effects:
        Starts the Panda3D application loop and opens the game window.

    Raises:
        Propagates startup errors from Panda3D or generated systems.

    Performance considerations:
        O(1) outside the engine loop.
    """

    args = parse_args(argv)
    window_type = "offscreen" if args.smoke_test else "onscreen"
    game = create_game(AppConfig(window_type=window_type))

    if args.debug:
        game.debug_on()

    if args.smoke_test:
        game.close()
        return 0

    game.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
