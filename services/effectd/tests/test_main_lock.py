"""Tests for the singleton startup lock in effectd.main."""

from __future__ import annotations

import os

import pytest

from effectd.main import SingletonLockError, acquire_singleton_lock


def test_acquire_lock_succeeds_first_time(tmp_path):
    """acquire_singleton_lock returns an int fd on first acquisition."""
    lock_path = str(tmp_path / "test.lock")
    fd = acquire_singleton_lock(lock_path)
    assert isinstance(fd, int)
    os.close(fd)


def test_second_acquire_raises_singleton_lock_error(tmp_path):
    """Second acquire on the same path raises SingletonLockError."""
    lock_path = str(tmp_path / "test.lock")
    fd1 = acquire_singleton_lock(lock_path)
    try:
        with pytest.raises(SingletonLockError):
            acquire_singleton_lock(lock_path)
    finally:
        os.close(fd1)


def test_lock_released_after_close_allows_reacquire(tmp_path):
    """After closing the fd, a new acquire on the same path succeeds."""
    lock_path = str(tmp_path / "test.lock")
    fd1 = acquire_singleton_lock(lock_path)
    os.close(fd1)
    fd2 = acquire_singleton_lock(lock_path)
    assert isinstance(fd2, int)
    os.close(fd2)


def test_acquire_writes_pid_to_file(tmp_path):
    """acquire_singleton_lock writes the process PID to the lock file."""
    lock_path = str(tmp_path / "test.lock")
    fd = acquire_singleton_lock(lock_path)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        content = os.read(fd, 32).decode()
        assert str(os.getpid()) in content
    finally:
        os.close(fd)
