import socket
import threading
import json
import time
import random
import sys

HOST = "0.0.0.0"

BOARD_WIDTH = 38
BOARD_HEIGHT = 24
FPS = 6
GAME_DURATION = 60

INITIAL_HEALTH = 100
NORMAL_PIE_HEALTH = 10
BONUS_PIE_HEALTH = 20
RABBIT_INVINCIBLE_SECONDS = 5

WALL_DAMAGE = 15
OBSTACLE_DAMAGE = 20
SPIKE_DAMAGE = 30
SNAKE_DAMAGE = 25

OBSTACLES = [
    (10, 5), (10, 6), (10, 7), (10, 8),
    (18, 12), (19, 12), (20, 12), (21, 12),
    (29, 4), (29, 5), (29, 6), (29, 7),
    (13, 18), (14, 18), (15, 18), (16, 18)
]

SPIKES = [
    (6, 6), (7, 6), (8, 6),
    (24, 17), (25, 17), (26, 17),
    (32, 9), (33, 9),
    (18, 5), (19, 5)
]

DIRECTION_VECTORS = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}

OPPOSITES = {
    "UP": "DOWN",
    "DOWN": "UP",
    "LEFT": "RIGHT",
    "RIGHT": "LEFT",
}


def send_json(sock, data):
    msg = json.dumps(data) + "\n"
    sock.sendall(msg.encode())


class JsonBuffer:
    def __init__(self):
        self.buffer = ""

    def feed(self, data_bytes):
        self.buffer += data_bytes.decode(errors="ignore")
        messages = []

        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        return messages


class Snake:
    def __init__(self, username, body, direction, color):
        self.username = username
        self.body = body[:]
        self.direction = direction
        self.pending_direction = direction
        self.health = INITIAL_HEALTH
        self.color = color
        self.grow_pending = 0
        self.started = False
        self.invincible_until = 0.0

    def set_direction(self, new_direction):
        if new_direction in DIRECTION_VECTORS:
            if not self.started:
                self.direction = new_direction
                self.pending_direction = new_direction
                self.started = True
            elif OPPOSITES[new_direction] != self.direction:
                self.pending_direction = new_direction

    def shrink(self, amount=1):
        for _ in range(amount):
            if len(self.body) > 1:
                self.body.pop()

    def is_invincible(self):
        return time.time() < self.invincible_until

    def invincible_left(self):
        return max(0.0, self.invincible_until - time.time())


class GameSession:
    def __init__(self, player1, player2, style1=None, style2=None):
        self.player1 = player1
        self.player2 = player2

        self.snakes = {
            player1: Snake(player1, [(4, 12), (3, 12), (2, 12)], "RIGHT", (0, 200, 0)),
            player2: Snake(player2, [(33, 12), (34, 12), (35, 12)], "LEFT", (220, 60, 60)),
        }

        if style1 and "color" in style1:
            self.snakes[player1].color = tuple(style1["color"])
        if style2 and "color" in style2:
            self.snakes[player2].color = tuple(style2["color"])

        self.obstacles = list(OBSTACLES)
        self.spikes = list(SPIKES)
        self.pies = []
        self.rabbit = None
        self.rabbit_spawned = False

        self.start_time = time.time()
        self.finished = False
        self.winner = None
        self.viewers = set()
        self.cheers = []
        self.chat_log = []

        self.paused = False
        self.paused_by = None
        self.pause_started_at = None
        self.total_paused_seconds = 0.0

        self.spawn_pie_if_needed()
        self.spawn_pie_if_needed()

    def occupied_cells(self):
        cells = set(self.obstacles) | set(self.spikes)

        for snake in self.snakes.values():
            cells.update(snake.body)

        for pie in self.pies:
            cells.add((pie["x"], pie["y"]))

        if self.rabbit:
            cells.add((self.rabbit["x"], self.rabbit["y"]))

        return cells

    def random_empty_cell(self):
        occupied = self.occupied_cells()
        attempts = 0
        while attempts < 1000:
            x = random.randint(0, BOARD_WIDTH - 1)
            y = random.randint(0, BOARD_HEIGHT - 1)
            if (x, y) not in occupied:
                return x, y
            attempts += 1
        return None

    def spawn_pie_if_needed(self):
        while len(self.pies) < 2:
            pos = self.random_empty_cell()
            if pos is None:
                break
            x, y = pos
            pie_type = random.choice(["normal", "normal", "bonus"])
            self.pies.append({
                "x": x,
                "y": y,
                "type": pie_type
            })

    def spawn_rabbit_if_needed(self):
        if self.rabbit_spawned:
            return

        if self.effective_elapsed() >= GAME_DURATION // 2:
            pos = self.random_empty_cell()
            if pos is not None:
                x, y = pos
                self.rabbit = {"x": x, "y": y}
                self.rabbit_spawned = True

    def apply_move(self, username, direction):
        if username in self.snakes:
            self.snakes[username].set_direction(direction)

    def add_chat(self, username, text):
        if text:
            self.chat_log.append(f"{username}: {text}")
            self.chat_log = self.chat_log[-10:]

    def toggle_pause(self, username):
        if not self.paused:
            self.paused = True
            self.paused_by = username
            self.pause_started_at = time.time()
        else:
            self.paused = False
            self.paused_by = None
            if self.pause_started_at is not None:
                self.total_paused_seconds += time.time() - self.pause_started_at
            self.pause_started_at = None

    def effective_elapsed(self):
        paused_extra = self.total_paused_seconds
        if self.paused and self.pause_started_at is not None:
            paused_extra += time.time() - self.pause_started_at
        return int(time.time() - self.start_time - paused_extra)

    def time_left(self):
        return max(0, GAME_DURATION - self.effective_elapsed())

    def in_bounds(self, pos):
        x, y = pos
        return 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT

    def damage_and_shrink(self, snake, damage, shrink_amount=1):
        if snake.is_invincible():
            return
        snake.health = max(0, snake.health - damage)
        snake.shrink(shrink_amount)

    def handle_pie(self, snake, head):
        eaten = None
        for pie in self.pies:
            if (pie["x"], pie["y"]) == head:
                eaten = pie
                break

        if eaten:
            if eaten["type"] == "bonus":
                snake.health += BONUS_PIE_HEALTH
                snake.grow_pending += 2
            else:
                snake.health += NORMAL_PIE_HEALTH
                snake.grow_pending += 1

            self.pies.remove(eaten)
            self.spawn_pie_if_needed()

    def handle_rabbit(self, snake, head):
        if self.rabbit and (self.rabbit["x"], self.rabbit["y"]) == head:
            snake.invincible_until = time.time() + RABBIT_INVINCIBLE_SECONDS
            self.rabbit = None

    def move_snake(self, snake):
        if not snake.started:
            return

        snake.direction = snake.pending_direction
        dx, dy = DIRECTION_VECTORS[snake.direction]
        hx, hy = snake.body[0]
        nx, ny = hx + dx, hy + dy

        if not self.in_bounds((nx, ny)):
            self.damage_and_shrink(snake, WALL_DAMAGE, 1)
            return

        new_head = (nx, ny)
        snake.body.insert(0, new_head)

        if snake.grow_pending > 0:
            snake.grow_pending -= 1
        else:
            snake.body.pop()

        self.handle_pie(snake, new_head)
        self.handle_rabbit(snake, new_head)

    def handle_collisions(self):
        players = list(self.snakes.keys())
        s1 = self.snakes[players[0]]
        s2 = self.snakes[players[1]]

        for snake in [s1, s2]:
            head = snake.body[0]

            if head in self.obstacles:
                self.damage_and_shrink(snake, OBSTACLE_DAMAGE, 1)

            if head in self.spikes:
                self.damage_and_shrink(snake, SPIKE_DAMAGE, 2)

            if head in snake.body[1:]:
                self.damage_and_shrink(snake, SNAKE_DAMAGE, 1)

        if s1.body[0] == s2.body[0]:
            self.damage_and_shrink(s1, SNAKE_DAMAGE, 1)
            self.damage_and_shrink(s2, SNAKE_DAMAGE, 1)
        else:
            if s1.body[0] in s2.body:
                self.damage_and_shrink(s1, SNAKE_DAMAGE, 1)
            if s2.body[0] in s1.body:
                self.damage_and_shrink(s2, SNAKE_DAMAGE, 1)

    def decide_winner(self):
        players = list(self.snakes.keys())
        h1 = self.snakes[players[0]].health
        h2 = self.snakes[players[1]].health

        if h1 > h2:
            self.winner = players[0]
        elif h2 > h1:
            self.winner = players[1]
        else:
            self.winner = "DRAW"

    def update(self):
        if self.finished:
            return

        if self.paused:
            return

        self.spawn_rabbit_if_needed()

        for snake in self.snakes.values():
            self.move_snake(snake)

        self.handle_collisions()

        if self.time_left() <= 0:
            self.finished = True

        for snake in self.snakes.values():
            if snake.health <= 0:
                self.finished = True

        if self.finished:
            self.decide_winner()

    def state_dict(self):
        return {
            "type": "state",
            "time_left": self.time_left(),
            "game_duration": GAME_DURATION,
            "obstacles": self.obstacles,
            "spikes": self.spikes,
            "pies": self.pies,
            "rabbit": self.rabbit,
            "cheers": self.cheers[-5:],
            "chat_log": self.chat_log[-8:],
            "paused": self.paused,
            "paused_by": self.paused_by,
            "players": {
                username: {
                    "body": snake.body,
                    "direction": snake.direction,
                    "health": snake.health,
                    "color": list(snake.color),
                    "invincible": snake.is_invincible(),
                    "invincible_left": round(snake.invincible_left(), 1),
                }
                for username, snake in self.snakes.items()
            },
            "finished": self.finished,
            "winner": self.winner,
        }


clients_lock = threading.Lock()
clients = {}
styles = {}
pending_invites = {}
pending_rematches = {}

session_lock = threading.Lock()
active_session = None


def safe_send(username, message):
    with clients_lock:
        sock = clients.get(username)

    if sock:
        try:
            send_json(sock, message)
        except Exception:
            pass


def broadcast_players():
    with clients_lock:
        snapshot = list(clients.items())
        names = [username for username, _ in snapshot]

    for username, sock in snapshot:
        try:
            send_json(sock, {
                "type": "players_list",
                "players": [n for n in names if n != username]
            })
        except Exception:
            pass


def broadcast_to_session(session, message):
    recipients = [session.player1, session.player2] + list(session.viewers)
    for username in recipients:
        safe_send(username, message)


def remove_pending_entries_for(username):
    pending_invites.pop(username, None)
    pending_rematches.pop(username, None)

    invite_targets = [k for k, v in pending_invites.items() if v == username]
    for k in invite_targets:
        pending_invites.pop(k, None)

    rematch_targets = [k for k, v in pending_rematches.items() if v == username]
    for k in rematch_targets:
        pending_rematches.pop(k, None)


def end_active_game_if_player_left(left_username):
    global active_session

    with session_lock:
        if active_session is None:
            return

        if left_username in [active_session.player1, active_session.player2]:
            other = (
                active_session.player2
                if active_session.player1 == left_username
                else active_session.player1
            )

            active_session.finished = True
            active_session.winner = other

            state = active_session.state_dict()
            game_over = {
                "type": "game_over",
                "winner": active_session.winner,
                "final_state": state,
            }
            broadcast_to_session(active_session, game_over)
            active_session = None


def start_match(player1, player2):
    global active_session

    active_session = GameSession(
        player1,
        player2,
        styles.get(player1),
        styles.get(player2),
    )

    safe_send(player1, {
        "type": "match_start",
        "opponent": player2,
        "role": "player"
    })
    safe_send(player2, {
        "type": "match_start",
        "opponent": player1,
        "role": "player"
    })

    broadcast_to_session(active_session, active_session.state_dict())


def game_loop():
    global active_session

    while True:
        time.sleep(1 / FPS)

        with session_lock:
            session = active_session

        if session is None:
            continue

        session.update()
        state = session.state_dict()
        broadcast_to_session(session, state)

        if session.finished:
            game_over = {
                "type": "game_over",
                "winner": session.winner,
                "final_state": state,
            }
            broadcast_to_session(session, game_over)

            with session_lock:
                active_session = None

            broadcast_players()


def handle_client(sock, addr):
    global active_session

    username = None
    buf = JsonBuffer()

    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break

            messages = buf.feed(data)

            for msg in messages:
                msg_type = msg.get("type")

                if msg_type == "login":
                    requested = msg.get("username", "").strip()

                    if not requested:
                        send_json(sock, {
                            "type": "login_error",
                            "reason": "Username is empty."
                        })
                        continue

                    login_success = False

                    with clients_lock:
                        if requested in clients:
                            send_json(sock, {
                                "type": "login_error",
                                "reason": "Username is already in use."
                            })
                        else:
                            username = requested
                            clients[username] = sock
                            login_success = True

                    if login_success:
                        print(f"{username} logged in from {addr}")
                        send_json(sock, {"type": "login_ok", "username": username})
                        broadcast_players()

                elif msg_type == "get_players":
                    if username:
                        with clients_lock:
                            names = [n for n in clients.keys() if n != username]
                        send_json(sock, {"type": "players_list", "players": names})

                elif msg_type == "select_style":
                    if username:
                        color = msg.get("color", [0, 200, 0])
                        if isinstance(color, list) and len(color) == 3:
                            styles[username] = {"color": color}

                elif msg_type == "invite_player":
                    target = msg.get("target")
                    if username and target:
                        with clients_lock:
                            target_exists = target in clients

                        if not target_exists:
                            safe_send(username, {
                                "type": "system",
                                "message": "That player is no longer online."
                            })
                            continue

                        pending_invites[target] = username
                        safe_send(target, {
                            "type": "invite_received",
                            "from": username
                        })
                        safe_send(username, {
                            "type": "system",
                            "message": f"Invite sent to {target}."
                        })

                elif msg_type == "accept_invite":
                    challenger = msg.get("from")
                    if username and challenger and pending_invites.get(username) == challenger:
                        with session_lock:
                            if active_session is None:
                                start_match(challenger, username)
                                pending_invites.pop(username, None)
                            else:
                                safe_send(username, {
                                    "type": "system",
                                    "message": "A game is already active."
                                })

                elif msg_type == "move":
                    direction = msg.get("direction")
                    with session_lock:
                        if active_session and username in active_session.snakes:
                            active_session.apply_move(username, direction)

                elif msg_type == "chat":
                    text = msg.get("message", "").strip()[:200]
                    with session_lock:
                        if active_session and username in [active_session.player1, active_session.player2]:
                            active_session.add_chat(username, text)

                elif msg_type == "watch_game":
                    with session_lock:
                        if active_session and username:
                            active_session.viewers.add(username)
                            safe_send(username, {"type": "watch_ok"})
                            safe_send(username, active_session.state_dict())
                        else:
                            safe_send(username, {
                                "type": "system",
                                "message": "No active game to watch."
                            })

                elif msg_type == "cheer":
                    cheer_text = msg.get("message", "").strip()[:80]
                    with session_lock:
                        if active_session and username in active_session.viewers and cheer_text:
                            active_session.cheers.append(f"{username}: {cheer_text}")

                elif msg_type == "pause_toggle":
                    with session_lock:
                        if active_session and username in active_session.snakes:
                            active_session.toggle_pause(username)
                            if active_session.paused:
                                broadcast_to_session(active_session, {
                                    "type": "system",
                                    "message": f"Game paused by {username}."
                                })
                            else:
                                broadcast_to_session(active_session, {
                                    "type": "system",
                                    "message": f"Game resumed by {username}."
                                })

                elif msg_type == "rematch_request":
                    target = msg.get("target")
                    if username and target:
                        with clients_lock:
                            target_exists = target in clients

                        if not target_exists:
                            safe_send(username, {
                                "type": "system",
                                "message": "That player is no longer online."
                            })
                            continue

                        pending_rematches[target] = username
                        safe_send(target, {
                            "type": "rematch_offer",
                            "from": username
                        })
                        safe_send(username, {
                            "type": "system",
                            "message": f"Play again request sent to {target}."
                        })

                elif msg_type == "accept_rematch":
                    challenger = msg.get("from")
                    if username and challenger and pending_rematches.get(username) == challenger:
                        with session_lock:
                            if active_session is None:
                                start_match(challenger, username)
                                pending_rematches.pop(username, None)
                            else:
                                safe_send(username, {
                                    "type": "system",
                                    "message": "A game is already active."
                                })

                elif msg_type == "decline_rematch":
                    challenger = msg.get("from")
                    if username and challenger and pending_rematches.get(username) == challenger:
                        pending_rematches.pop(username, None)
                        safe_send(challenger, {
                            "type": "system",
                            "message": f"{username} declined the play again request."
                        })

                elif msg_type == "quit":
                    raise ConnectionResetError()

    except Exception:
        pass

    finally:
        if username:
            with clients_lock:
                clients.pop(username, None)

            remove_pending_entries_for(username)

            with session_lock:
                if active_session:
                    active_session.viewers.discard(username)

            end_active_game_if_player_left(username)
            broadcast_players()

        try:
            sock.close()
        except Exception:
            pass


def main():
    if len(sys.argv) != 2:
        print("Usage: python server.py <port>")
        return

    port = int(sys.argv[1])

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, port))
    server.listen()

    print(f"Server listening on {HOST}:{port}")

    threading.Thread(target=game_loop, daemon=True).start()

    while True:
        sock, addr = server.accept()
        print(f"Client connected from {addr}")
        threading.Thread(target=handle_client, args=(sock, addr), daemon=True).start()


if __name__ == "__main__":
    main()
