#!/usr/bin/env python3
"""
Test database concurrency handling with multiple processes.
This simulates multiple game lobbies attempting to update player stats simultaneously.
"""

import multiprocessing
import random
import time
import os
from pathlib import Path

import config
from server import ServerDB

def worker_process(worker_id, test_users, iterations):
    """Simulate a game lobby process updating player stats."""
    print(f"Worker {worker_id} starting")
    
    # Use a separate test database for this test
    test_db_path = Path("test_concurrency.db")
    db = ServerDB(test_db_path)
    
    # Create test users if they don't exist
    for username in test_users:
        try:
            db.add_user(username, "test_password_hash")
        except ValueError:
            # User already exists, ignore
            pass
    
    # Simulate game results
    for i in range(iterations):
        # Random sleep to simulate varying workloads
        time.sleep(random.uniform(0.01, 0.05))
        
        # Pick a random user and record a win or loss
        username = random.choice(test_users)
        win = random.choice([True, False])
        try:
            db.record_game(username, win)
            print(f"Worker {worker_id}: Recorded {'win' if win else 'loss'} for {username}")
        except Exception as e:
            print(f"Worker {worker_id}: Error recording game: {e}")
    
    # Get final stats
    for username in test_users:
        stats = db.get_stats(username)
        print(f"Worker {worker_id}: Final stats for {username}: {stats}")
    
    print(f"Worker {worker_id} finished")

def main():
    """Run the concurrency test with multiple processes."""
    # Parameters
    num_processes = 5
    test_users = [f"test_user_{i}" for i in range(3)]
    iterations_per_process = 50
    
    # Delete test database if it exists
    test_db_path = Path("test_concurrency.db")
    if test_db_path.exists():
        os.remove(test_db_path)
        print(f"Deleted existing test database at {test_db_path}")
    
    # Create database and test users
    db = ServerDB(test_db_path)
    for username in test_users:
        db.add_user(username, "test_password_hash")
    print(f"Created test users: {test_users}")
    
    # Start worker processes
    processes = []
    for i in range(num_processes):
        p = multiprocessing.Process(
            target=worker_process,
            args=(i, test_users, iterations_per_process)
        )
        processes.append(p)
        p.start()
    
    # Wait for all processes to complete
    for p in processes:
        p.join()
    
    # Verify final stats
    db = ServerDB(test_db_path)
    for username in test_users:
        games, wins, losses = db.get_stats(username)
        print(f"Final stats for {username}: {games} games, {wins} wins, {losses} losses")
        # Verify that games = wins + losses
        assert games == wins + losses, f"Inconsistent stats for {username}: {games} != {wins} + {losses}"
    
    print("Database concurrency test completed successfully!")

if __name__ == "__main__":
    main() 