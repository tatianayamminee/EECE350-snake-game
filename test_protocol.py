"""
Headless protocol test for the Snake Arena server.

This is a small test harness (NO pygame, NO window) that pretends to be two
players. It connects to the running server, logs both in over TCP, has one
player invite the other, accepts the match, sends a few moves, and confirms the
server sends back proper JSON game-state messages and a final game_over.

Run the server first, then run this:
    python3 server.py 5000        # terminal 1
    python3 test_protocol.py 5000 # terminal 2
"""
import socket
import json
import time
import sys
import threading


class Client:
    """A tiny fake player that speaks the same JSON-over-TCP protocol."""

    def __init__(self, host, port, username):
        self.username = username
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.buffer = ""
        self.inbox = []               # every decoded message the server sent us
        self.lock = threading.Lock()
        self.running = True
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def send(self, data):
        self.sock.sendall((json.dumps(data) + "\n").encode())

    def _recv_loop(self):
        while self.running:
            try:
                data = self.sock.recv(4096)
            except OSError:
                break
            if not data:
                break
            self.buffer += data.decode(errors="ignore")
            while "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                line = line.strip()
                if line:
                    with self.lock:
                        self.inbox.append(json.loads(line))

    def mark(self):
        """Remember how many messages we've seen, so we can wait only for NEW ones."""
        with self.lock:
            return len(self.inbox)

    def wait_for(self, msg_type, timeout=5.0, start=0):
        """Wait until a message of the given type arrives at/after index `start`."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                for m in self.inbox[start:]:
                    if m.get("type") == msg_type:
                        return m
            time.sleep(0.05)
        return None

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


def ok(label):
    print(f"  PASS  {label}")


def fail(label):
    print(f"  FAIL  {label}")
    sys.exit(1)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    host = "127.0.0.1"

    print(f"Connecting two test players to {host}:{port} ...")
    alice = Client(host, port, "alice")
    bob = Client(host, port, "bob")

    # --- 1. login ---
    alice.send({"type": "login", "username": "alice"})
    bob.send({"type": "login", "username": "bob"})
    if alice.wait_for("login_ok"):
        ok("alice logged in")
    else:
        fail("alice did not get login_ok")
    if bob.wait_for("login_ok"):
        ok("bob logged in")
    else:
        fail("bob did not get login_ok")

    # --- 2. duplicate username is rejected ---
    dup = Client(host, port, "alice")
    dup.send({"type": "login", "username": "alice"})
    if dup.wait_for("login_error"):
        ok("duplicate username correctly rejected")
    else:
        fail("duplicate username was NOT rejected")
    dup.close()

    # --- 3. lobby player list ---
    m = alice.mark()
    alice.send({"type": "get_players"})
    plist = alice.wait_for("players_list", start=m)
    if plist and "bob" in plist.get("players", []):
        ok("alice sees bob in the lobby")
    else:
        fail("alice did not see bob in players_list")

    # --- 4. invite + accept starts a match ---
    alice.send({"type": "invite_player", "target": "bob"})
    if bob.wait_for("invite_received"):
        ok("bob received the invite")
    else:
        fail("bob never received the invite")

    bob.send({"type": "accept_invite", "from": "alice"})
    if alice.wait_for("match_start") and bob.wait_for("match_start"):
        ok("match started for both players")
    else:
        fail("match_start not received by both")

    # --- 5. game state flows over the network ---
    state = alice.wait_for("state")
    if state and "players" in state and "alice" in state["players"]:
        ok("server is broadcasting game state (JSON)")
    else:
        fail("no valid game state received")

    # --- 6. moves are accepted and the snake actually moves ---
    m = alice.mark()
    before = alice.wait_for("state", start=m)["players"]["alice"]["body"][0]
    for _ in range(6):
        alice.send({"type": "move", "direction": "UP"})
        time.sleep(0.2)
    m = alice.mark()
    after = alice.wait_for("state", start=m)["players"]["alice"]["body"][0]
    if after != before:
        ok(f"alice's snake moved: head {before} -> {after}")
    else:
        fail("snake head never changed after sending moves")

    # --- 7. match ends and a winner is declared ---
    print("  ...  waiting for the 60s match to finish (this takes a moment)")
    over = alice.wait_for("game_over", timeout=75)
    if over and over.get("winner"):
        ok(f"game_over received, winner = {over.get('winner')}")
    else:
        fail("game never ended with a game_over message")

    alice.close()
    bob.close()
    print("\nAll protocol tests PASSED ✅  Server and networking work correctly.")


if __name__ == "__main__":
    main()
