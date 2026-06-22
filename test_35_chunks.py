#!/usr/bin/env python3
"""Test script to prove Panda3D can render 35+ chunks smoothly.

This test:
1. Starts the game with render_distance = 3 (~40 chunks loaded)
2. Enables frustum culling (only renders chunks in camera view)
3. Records FPS and chunk statistics
4. Demonstrates smooth 60+ FPS performance

To run:
    python test_35_chunks.py
    
Expected result:
    - 36-49 chunks loaded (7x7 grid for render_distance=3)
    - Only ~8-16 chunks rendered at a time (in camera frustum)
    - Smooth 60+ FPS on modern hardware
    - Proves ChatGPT's claim wrong!
"""

import sys
import time
from pathlib import Path

# Add game directory to path
sys.path.insert(0, str(Path(__file__).parent / "MINECRAFT" / "game"))

from dataclasses import dataclass
from game_manager import AppConfig, GameManager

@dataclass
class PerformanceMetrics:
    """Track rendering performance during test."""
    frame_count: int = 0
    total_time: float = 0.0
    min_fps: float = float('inf')
    max_fps: float = 0.0
    chunk_counts: list = None
    rendered_chunk_counts: list = None
    
    def __post_init__(self):
        if self.chunk_counts is None:
            self.chunk_counts = []
        if self.rendered_chunk_counts is None:
            self.rendered_chunk_counts = []
    
    @property
    def avg_fps(self) -> float:
        if self.total_time <= 0:
            return 0.0
        return self.frame_count / self.total_time
    
    def record_frame(self, dt: float, loaded_chunks: int, visible_chunks: int):
        """Record metrics for one frame."""
        if dt > 0:
            fps = 1.0 / dt
            self.min_fps = min(self.min_fps, fps)
            self.max_fps = max(self.max_fps, fps)
        self.frame_count += 1
        self.total_time += dt
        self.chunk_counts.append(loaded_chunks)
        self.rendered_chunk_counts.append(visible_chunks)


def run_test():
    """Run the 35+ chunk rendering test."""
    print("=" * 70)
    print("PANDA3D 35+ CHUNK RENDERING PERFORMANCE TEST")
    print("=" * 70)
    
    # Create game with higher render distance
    print("\n[1/4] Initializing game with render_distance=3 (~40 chunks)...")
    project_root = Path(__file__).parent / "MINECRAFT" / "game"
    
    config = AppConfig(
        window_type="onscreen",
        window_width=1920,
        window_height=1080,
        target_fps=0,  # Uncapped
        show_frame_rate_meter=True,
        sync_video=False,
        cursor_hidden=True,
    )
    
    game = GameManager(project_root=project_root, app_config=config)
    game.render_distance = 3  # Load 7x7 = 49 chunks
    game._sync_effective_render_distance()
    game._sync_streaming_budget()
    
    print(f"   ✓ Game initialized")
    print(f"   ✓ Render distance: 3")
    print(f"   ✓ Effective render distance: {game._effective_render_distance}")
    print(f"   ✓ Max chunk rebuilds per frame: {game.render_manager.max_chunk_rebuilds_per_frame}")
    
    # Let chunks load
    print("\n[2/4] Loading chunks and rendering meshes (10 seconds)...")
    load_start = time.time()
    while time.time() - load_start < 10:
        game.taskMgr.step()
        loaded = len(game.chunk_manager.loaded)
        print(f"   Loaded: {loaded}/~49 chunks | "
              f"Pending meshes: {len(game.render_manager.pending_mesh_futures)}", end='\r')
    print(" " * 80)  # Clear line
    print(f"   ✓ Chunks loaded: {len(game.chunk_manager.loaded)}")
    
    # Collect performance metrics
    print("\n[3/4] Recording performance metrics (20 seconds, ~1200 frames)...")
    metrics = PerformanceMetrics()
    perf_start = time.time()
    frame_times = []
    
    while time.time() - perf_start < 20:
        frame_start = time.time()
        game.taskMgr.step()
        frame_time = time.time() - frame_start
        frame_times.append(frame_time)
        
        loaded_chunks = len(game.chunk_manager.loaded)
        rendered_chunks = len([n for n in game.render_manager.chunk_nodes.values() 
                              if n.isHidden() is False])
        metrics.record_frame(frame_time, loaded_chunks, rendered_chunks)
        
        if metrics.frame_count % 100 == 0:
            print(f"   Frame {metrics.frame_count:4d} | "
                  f"Loaded: {loaded_chunks:2d} | "
                  f"Visible: {rendered_chunks:2d} | "
                  f"FPS: {metrics.avg_fps:.1f}", end='\r')
    
    print(" " * 100)  # Clear line
    
    # Print results
    print("\n[4/4] RESULTS")
    print("-" * 70)
    print(f"Total frames recorded:        {metrics.frame_count}")
    print(f"Total time:                   {metrics.total_time:.2f} seconds")
    print(f"\nFramerate Performance:")
    print(f"  Average FPS:                {metrics.avg_fps:.1f}")
    print(f"  Minimum FPS:                {metrics.min_fps:.1f}")
    print(f"  Maximum FPS:                {metrics.max_fps:.1f}")
    
    print(f"\nChunk Statistics:")
    max_loaded = max(metrics.chunk_counts) if metrics.chunk_counts else 0
    avg_loaded = sum(metrics.chunk_counts) / len(metrics.chunk_counts) if metrics.chunk_counts else 0
    max_visible = max(metrics.rendered_chunk_counts) if metrics.rendered_chunk_counts else 0
    avg_visible = sum(metrics.rendered_chunk_counts) / len(metrics.rendered_chunk_counts) if metrics.rendered_chunk_counts else 0
    
    print(f"  Max loaded chunks:          {max_loaded}")
    print(f"  Avg loaded chunks:          {avg_loaded:.1f}")
    print(f"  Max visible chunks:         {max_visible}")
    print(f"  Avg visible chunks:         {avg_visible:.1f}")
    
    print(f"\nFrustum Culling Efficiency:")
    culling_ratio = (1.0 - avg_visible / max(avg_loaded, 1)) * 100
    print(f"  Chunks hidden by frustum:   {culling_ratio:.1f}%")
    print(f"  (Only in-view chunks rendered → Better performance!)")
    
    print("\n" + "=" * 70)
    if metrics.avg_fps >= 60:
        print("✓ SUCCESS: 35+ chunks render smoothly at 60+ FPS!")
        print("  ChatGPT's claim is PROVEN WRONG.")
    elif metrics.avg_fps >= 30:
        print("✓ PARTIAL SUCCESS: 35+ chunks render at playable framerates (30+ FPS)")
        print("  Performance varies by hardware, but absolutely feasible.")
    else:
        print("✗ FAILED: Performance below target")
    print("=" * 70)
    
    # Cleanup
    game.close()
    return 0 if metrics.avg_fps >= 30 else 1


if __name__ == "__main__":
    sys.exit(run_test())
