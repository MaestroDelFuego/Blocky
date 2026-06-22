#!/usr/bin/env python3
"""Multiplayer launcher for Voxel Sandbox.

Usage:
    python launch_multiplayer.py [--server] [--host HOST] [--port PORT] [--username USERNAME]

Examples:
    # Start dedicated server
    python launch_multiplayer.py --server
    
    # Connect to local server
    python launch_multiplayer.py --username MyPlayer
    
    # Connect to remote server
    python launch_multiplayer.py --host 192.168.1.100 --port 9999 --username Alice
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add game directory to path
sys.path.insert(0, str(Path(__file__).parent / "game"))


def run_server(host: str = "0.0.0.0", port: int = 9999) -> None:
    """Run dedicated multiplayer server."""
    from server import VoxelSandboxServer
    
    server = VoxelSandboxServer(host=host, port=port)
    server.start()


def run_client(username: str = "Player", server_host: str = "localhost", server_port: int = 9999) -> None:
    """Run client in multiplayer mode."""
    from main import AppConfig, create_game
    
    config = AppConfig()
    game = create_game(config)
    
    # Enable multiplayer mode
    game.multiplayer = True
    game.server_host = server_host
    game.server_port = server_port
    game.username = username
    
    # Initialize multiplayer after create_game
    game._init_multiplayer()
    
    game.run()


def main() -> int:
    """Parse arguments and launch server or client."""
    parser = argparse.ArgumentParser(
        description="Voxel Sandbox Multiplayer Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--server",
        action="store_true",
        help="Launch dedicated server instead of client"
    )
    
    parser.add_argument(
        "--host",
        default="localhost",
        help="Server host for client or bind address for server (default: localhost for client, 0.0.0.0 for server)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=9999,
        help="Server port (default: 9999)"
    )
    
    parser.add_argument(
        "-u",
        "--username",
        default="Player",
        help="Player username for client (default: Player)"
    )
    
    args = parser.parse_args()
    
    try:
        if args.server:
            # Override host for server (bind to all interfaces by default)
            server_host = args.host if args.host != "localhost" else "0.0.0.0"
            print(f"🌐 Starting Voxel Sandbox Server...")
            print(f"   Host: {server_host}")
            print(f"   Port: {args.port}")
            run_server(host=server_host, port=args.port)
        else:
            print(f"🎮 Starting Voxel Sandbox Client...")
            print(f"   Username: {args.username}")
            print(f"   Server: {args.host}:{args.port}")
            run_client(username=args.username, server_host=args.host, server_port=args.port)
        
        return 0
    except KeyboardInterrupt:
        print("\n👋 Exiting...")
        return 0
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
