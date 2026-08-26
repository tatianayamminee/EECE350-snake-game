import socket
import threading
import json
import pygame
import math
import os


BOARD_WIDTH = 38
BOARD_HEIGHT = 24
CELL_SIZE = 21

BOARD_PIXEL_W = BOARD_WIDTH * CELL_SIZE
BOARD_PIXEL_H = BOARD_HEIGHT * CELL_SIZE

WINDOW_WIDTH = 1260
WINDOW_HEIGHT = 740
FPS = 60
NETWORK_REFRESH_MS = 1000

MARGIN = 24
BOARD_X = MARGIN
BOARD_Y = 58
RIGHT_PANEL_X = BOARD_X + BOARD_PIXEL_W + 24
RIGHT_PANEL_Y = BOARD_Y
RIGHT_PANEL_W = WINDOW_WIDTH - RIGHT_PANEL_X - MARGIN
RIGHT_PANEL_H = WINDOW_HEIGHT - RIGHT_PANEL_Y - 82

STATUS_BAR_H = 34

COLOR_OPTIONS = [
    {"name": "Green", "rgb": (0, 200, 0)},
    {"name": "Red", "rgb": (220, 60, 60)},
    {"name": "Blue", "rgb": (60, 140, 255)},
    {"name": "Orange", "rgb": (255, 180, 0)},
    {"name": "Purple", "rgb": (180, 70, 255)},
    {"name": "Cyan", "rgb": (0, 210, 200)},
    {"name": "Pink", "rgb": (255, 105, 180)},
    {"name": "White", "rgb": (240, 240, 240)},
    {"name": "Mint", "rgb": (120, 255, 120)},
    {"name": "Coral", "rgb": (255, 120, 120)},
]

DEFAULT_KEYS = {
    "UP": pygame.K_w,
    "DOWN": pygame.K_s,
    "LEFT": pygame.K_a,
    "RIGHT": pygame.K_d,
}
KEY_ORDER = ["UP", "DOWN", "LEFT", "RIGHT"]

TITLE_COLOR = (237, 216, 123)
TEXT_COLOR = (232, 235, 226)
SUBTEXT_COLOR = (182, 188, 173)
ACCENT_GREEN = (108, 217, 132)
ACCENT_RED = (224, 92, 92)
ACCENT_GOLD = (184, 140, 63)
PANEL_FILL = (24, 27, 24)
PANEL_BORDER = (92, 101, 86)
CARD_FILL = (32, 37, 33)
BOARD_DARK_1 = (38, 41, 37)
BOARD_DARK_2 = (33, 36, 33)


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


class Button:
    def __init__(self, rect, text, on_click, bg=(55, 80, 180), fg=(255, 255, 255), radius=12):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.on_click = on_click
        self.bg = bg
        self.fg = fg
        self.radius = radius
        self.hovered = False
        self.visible = True
        self.enabled = True
        self.pressed_until = 0

    def draw(self, surface, font):
        if not self.visible:
            return

        now = pygame.time.get_ticks()
        color = self.bg

        if not self.enabled:
            color = tuple(max(30, c // 2) for c in self.bg)
        elif now < self.pressed_until:
            color = tuple(max(0, c - 35) for c in self.bg)
        elif self.hovered:
            color = tuple(min(255, c + 18) for c in self.bg)

        pygame.draw.rect(surface, color, self.rect, border_radius=self.radius)
        pygame.draw.rect(surface, (229, 229, 220), self.rect, 2, border_radius=self.radius)

        txt = font.render(self.text, True, self.fg if self.enabled else (180, 180, 180))
        surface.blit(txt, txt.get_rect(center=self.rect.center))

    def handle_event(self, event):
        if not self.visible:
            return False

        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.enabled and self.rect.collidepoint(event.pos):
                self.pressed_until = pygame.time.get_ticks() + 140
                self.on_click()
                return True
        return False


class InputField:
    def __init__(self, rect, text="", placeholder="", max_len=24):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.placeholder = placeholder
        self.active = False
        self.max_len = max_len

    def draw(self, surface, font, label=None):
        if label:
            lbl = font.render(label, True, TEXT_COLOR)
            surface.blit(lbl, (self.rect.x, self.rect.y - 24))

        bg = (26, 30, 27) if self.active else (21, 24, 22)
        border = (150, 171, 132) if self.active else (89, 96, 85)
        pygame.draw.rect(surface, bg, self.rect, border_radius=12)
        pygame.draw.rect(surface, border, self.rect, 2, border_radius=12)

        display = self.text if self.text else self.placeholder
        color = (248, 248, 243) if self.text else (125, 132, 121)
        txt = font.render(display, True, color)
        surface.blit(txt, (self.rect.x + 12, self.rect.y + 10))

        if self.active:
            show_cursor = (pygame.time.get_ticks() // 500) % 2 == 0
            if show_cursor:
                typed_width = font.size(self.text)[0]
                cursor_x = self.rect.x + 12 + typed_width + 2
                cursor_y = self.rect.y + 9
                pygame.draw.line(
                    surface,
                    (248, 248, 243),
                    (cursor_x, cursor_y),
                    (cursor_x, cursor_y + font.get_height()),
                    2
                )

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.active = self.rect.collidepoint(event.pos)

        elif event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_RETURN:
                pass
            else:
                if len(self.text) < self.max_len and event.unicode and event.unicode.isprintable():
                    self.text += event.unicode


class App:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        self.clock = pygame.time.Clock()
        pygame.display.set_caption("Πthon Arena")

        self.background_image = None
        self.load_background_image()

        self.font = pygame.font.SysFont("arial", 21)
        self.small_font = pygame.font.SysFont("arial", 17)
        self.tiny_font = pygame.font.SysFont("arial", 15)
        self.big_font = pygame.font.SysFont("arial", 40, bold=True)
        self.title_font = pygame.font.SysFont("arial", 50, bold=True)
        self.rule_title_font = pygame.font.SysFont("arial", 30, bold=True)
        self.emoji_font = pygame.font.SysFont("segoe ui emoji", 19)

        self.running = True
        self.sock = None
        self.recv_thread = None
        self.connected = False

        self.screen_name = "intro"
        self.status_message = ""
        self.status_color = TEXT_COLOR

        self.players_list = []
        self.current_state = None
        self.previous_state = None
        self.last_state_time = pygame.time.get_ticks()
        self.current_state_time = pygame.time.get_ticks()

        self.game_duration = 60
        self.invite_from = None
        self.rematch_from = None
        self.last_winner = None
        self.role = "lobby"
        self.my_username = ""
        self.current_opponent = ""
        self.last_players_request = 0

        self.selected_player = None
        self.selected_color_index = 0
        self.selected_color = COLOR_OPTIONS[0]["rgb"]
        self.selected_color_name = COLOR_OPTIONS[0]["name"]

        self.keymap = dict(DEFAULT_KEYS)
        self.awaiting_key_for = None

        self.ip_field = InputField((60, 190, 320, 46), text="127.0.0.1", placeholder="Server IP")
        self.port_field = InputField((60, 275, 320, 46), text="5000", placeholder="Port")
        self.name_field = InputField((60, 360, 320, 46), text="", placeholder="Username")
        self.chat_input = InputField((0, 0, 100, 40), text="", placeholder="Type here...", max_len=80)

        self.inputs = [self.ip_field, self.port_field, self.name_field]
        self.active_input_index = 0
        self.inputs[0].active = True

        self.rebuild_buttons()

    def load_background_image(self):
        """Load the jungle background image from the same folder as this client file."""
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            image_path = os.path.join(base_dir, "jungle_bg.png")
            raw = pygame.image.load(image_path).convert()
            self.background_image = pygame.transform.smoothscale(raw, (WINDOW_WIDTH, WINDOW_HEIGHT))
        except Exception:
            self.background_image = None

    def draw_image_background(self, overlay=(0, 0, 0, 90)):
        """Draw the jungle image background with a transparent dark overlay for readability."""
        if self.background_image:
            self.screen.blit(self.background_image, (0, 0))
        else:
            self.draw_gradient_background()

        shade = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        shade.fill(overlay)
        self.screen.blit(shade, (0, 0))

    def set_status(self, message, color=TEXT_COLOR):
        self.status_message = message
        self.status_color = color

    def center_text(self, text, font, color, center_x, y):
        surf = font.render(text, True, color)
        rect = surf.get_rect(center=(center_x, y))
        self.screen.blit(surf, rect)

    def draw_wrapped_text(self, text, font, color, rect, line_spacing=4):
        words = text.split()
        lines = []
        current = ""

        for word in words:
            test = word if current == "" else current + " " + word
            if font.size(test)[0] <= rect.width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word

        if current:
            lines.append(current)

        y = rect.y
        line_h = font.get_height()

        for line in lines:
            if y + line_h > rect.bottom:
                break
            surf = font.render(line, True, color)
            self.screen.blit(surf, (rect.x, y))
            y += line_h + line_spacing

    def draw_info_card(self, rect, border_color, title, lines, icon=None, icon_drawer=None):
        pygame.draw.rect(self.screen, (20, 36, 62), rect, border_radius=16)
        pygame.draw.rect(self.screen, border_color, rect, 2, border_radius=16)

        icon_x = rect.x + 14
        title_x = rect.x + 18

        if icon_drawer:
            icon_drawer(rect.x + 18, rect.y + 18)
            title_x = rect.x + 56
        elif icon:
            icon_surf = self.emoji_font.render(icon, True, (255, 255, 255))
            self.screen.blit(icon_surf, (icon_x, rect.y + 12))
            title_x = rect.x + 48

        title_surf = self.small_font.render(title, True, (245, 245, 255))
        self.screen.blit(title_surf, (title_x, rect.y + 12))

        y = rect.y + 38
        for line in lines:
            pygame.draw.circle(self.screen, (205, 225, 255), (rect.x + 18, y + 8), 2)
            line_rect = pygame.Rect(rect.x + 28, y, rect.w - 38, 22)
            self.draw_wrapped_text(line, self.tiny_font, (218, 226, 236), line_rect, line_spacing=1)
            y += 20

    def draw_intro_spikes_icon(self, x, y):
        for i in range(3):
            px = x + i * 14
            pygame.draw.polygon(
                self.screen,
                (224, 92, 92),
                [(px, y + 16), (px + 6, y), (px + 12, y + 16)]
            )

    def draw_intro_wall_icon(self, x, y):
        for row in range(2):
            for col in range(2):
                brick = pygame.Rect(x + col * 11, y + row * 9, 10, 8)
                pygame.draw.rect(self.screen, (135, 140, 135), brick, border_radius=2)

    def draw_decorative_snake(self, points, body_color, head_color=None, alpha=85, radius=14):
        if head_color is None:
            head_color = body_color

        snake_surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)

        for i, (x, y) in enumerate(points):
            fade = max(35, alpha - (len(points) - i) * 2)
            color = (*body_color, fade)
            pygame.draw.circle(snake_surface, color, (x, y), radius)

            if i > 0:
                px, py = points[i - 1]
                pygame.draw.line(
                    snake_surface,
                    (*body_color, fade),
                    (px, py),
                    (x, y),
                    radius * 2 - 4
                )

        for i, (x, y) in enumerate(points[1::2]):
            pygame.draw.circle(snake_surface, (255, 255, 255, 28), (x - 3, y - 3), max(3, radius // 4))

        hx, hy = points[-1]
        pygame.draw.circle(snake_surface, (*head_color, min(255, alpha + 40)), (hx, hy), radius + 2)

        pygame.draw.circle(snake_surface, (255, 255, 255, 180), (hx - 5, hy - 4), 2)
        pygame.draw.circle(snake_surface, (255, 255, 255, 180), (hx + 5, hy - 4), 2)
        pygame.draw.circle(snake_surface, (30, 30, 30, 220), (hx - 5, hy - 4), 1)
        pygame.draw.circle(snake_surface, (30, 30, 30, 220), (hx + 5, hy - 4), 1)

        pygame.draw.line(snake_surface, (255, 90, 120, 180), (hx, hy + 6), (hx, hy + 16), 2)
        pygame.draw.line(snake_surface, (255, 90, 120, 180), (hx, hy + 16), (hx - 5, hy + 20), 2)
        pygame.draw.line(snake_surface, (255, 90, 120, 180), (hx, hy + 16), (hx + 5, hy + 20), 2)

        self.screen.blit(snake_surface, (0, 0))

    def rebuild_buttons(self):
        self.intro_buttons = [
            Button((WINDOW_WIDTH // 2 - 110, 650, 220, 54), "Continue", self.open_setup, bg=(89, 160, 98)),
        ]

        self.setup_buttons = [
            Button((60, 450, 150, 48), "Customize", self.open_customize, bg=(93, 88, 60)),
            Button((230, 450, 150, 48), "Connect", self.connect, bg=(89, 127, 84)),
        ]

        self.customize_buttons = [
            Button((60, 620, 130, 44), "Back", self.open_setup, bg=(89, 96, 85)),
            Button((210, 620, 160, 44), "Reset Keys", self.reset_keys, bg=(125, 92, 61)),
        ]

        self.lobby_buttons = [
            Button((100, 565, 120, 40), "Invite", self.invite_selected_player, bg=(89, 127, 84)),
            Button((882, 100, 320, 44), "Watch Current Game", self.watch_game, bg=(110, 98, 70)),
            Button((882, 156, 320, 44), "Back to Setup", self.disconnect_and_return, bg=(89, 96, 85)),
        ]

        self.invite_response_buttons = [
            Button((882, 455, 145, 38), "Accept", self.accept_invite, bg=(89, 127, 84)),
            Button((1042, 455, 145, 38), "Dismiss", self.dismiss_invite, bg=(145, 77, 77)),
        ]

        self.pause_button = Button((0, 0, 115, 34), "Pause", self.toggle_pause_game, bg=(184, 140, 63))
        self.send_button = Button((0, 0, 72, 40), "Send", self.send_game_message, bg=(89, 127, 84))
        self.cheer_button = Button((0, 0, 118, 34), "Go Go Go!", self.send_cheer_message, bg=(89, 127, 84))

        self.result_buttons = [
            Button((WINDOW_WIDTH // 2 - 180, 585, 150, 46), "Play Again", self.request_rematch, bg=(89, 127, 84)),
            Button((WINDOW_WIDTH // 2 + 20, 585, 150, 46), "Back to Lobby", self.back_to_lobby_from_result, bg=(89, 96, 85)),
        ]

        self.rematch_buttons = [
            Button((WINDOW_WIDTH // 2 - 130, 530, 115, 40), "Accept", self.accept_rematch, bg=(89, 127, 84)),
            Button((WINDOW_WIDTH // 2 + 20, 530, 115, 40), "Decline", self.decline_rematch, bg=(145, 77, 77)),
        ]

    def connect(self):
        host = self.ip_field.text.strip() or "127.0.0.1"
        port_text = self.port_field.text.strip()
        username = self.name_field.text.strip()

        if not port_text.isdigit():
            self.set_status("Port must be a number.", ACCENT_RED)
            return

        if not username:
            self.set_status("Choose a username first.", ACCENT_RED)
            return

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            sock.connect((host, int(port_text)))
            self.set_status("Checking username...", TITLE_COLOR)

            send_json(sock, {"type": "login", "username": username})

            login_buffer = JsonBuffer()
            login_response = None

            while login_response is None:
                data = sock.recv(4096)
                if not data:
                    raise Exception("Server closed the connection.")

                for msg in login_buffer.feed(data):
                    if msg.get("type") in ("login_ok", "login_error"):
                        login_response = msg
                        break

            if login_response.get("type") == "login_error":
                reason = login_response.get("reason", login_response.get("message", "Username already in use."))
                try:
                    sock.close()
                except Exception:
                    pass
                self.sock = None
                self.connected = False
                self.set_status(reason, ACCENT_RED)
                self.screen_name = "setup"
                return

            sock.settimeout(None)
            self.sock = sock
            self.connected = True
            self.my_username = username
            self.role = "lobby"
            self.current_state = None
            self.last_winner = None
            self.selected_player = None
            self.invite_from = None
            self.rematch_from = None
            self.current_opponent = ""

            self.set_status(f"Welcome, {username}", ACCENT_GREEN)

            send_json(self.sock, {"type": "select_style", "color": list(self.selected_color)})
            send_json(self.sock, {"type": "get_players"})

            self.recv_thread = threading.Thread(target=self.recv_loop, daemon=True)
            self.recv_thread.start()

            self.screen_name = "lobby"

        except Exception as e:
            try:
                sock.close()
            except Exception:
                pass
            self.set_status(f"Could not connect: {e}", ACCENT_RED)
            self.connected = False
            self.sock = None
            self.screen_name = "setup"

    def disconnect_after_login_error(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass

        self.sock = None
        self.connected = False
        self.players_list = []
        self.current_state = None
        self.invite_from = None
        self.rematch_from = None
        self.last_winner = None
        self.selected_player = None
        self.current_opponent = ""
        self.screen_name = "setup"

    def disconnect_and_return(self):
        try:
            if self.sock:
                send_json(self.sock, {"type": "quit"})
        except Exception:
            pass

        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass

        self.sock = None
        self.connected = False
        self.players_list = []
        self.current_state = None
        self.invite_from = None
        self.rematch_from = None
        self.last_winner = None
        self.selected_player = None
        self.current_opponent = ""
        self.screen_name = "setup"
        self.set_status("Returned to setup.")

    def recv_loop(self):
        buf = JsonBuffer()

        try:
            while self.connected and self.sock:
                data = self.sock.recv(4096)
                if not data:
                    break

                messages = buf.feed(data)

                for msg in messages:
                    t = msg.get("type")

                    if t == "login_ok":
                        self.set_status(f"Welcome, {msg.get('username')}", ACCENT_GREEN)

                    elif t == "login_error":
                        self.set_status(msg.get("reason", "Login failed."), ACCENT_RED)
                        self.disconnect_after_login_error()

                    elif t == "players_list":
                        self.players_list = msg.get("players", [])
                        if self.selected_player not in self.players_list:
                            self.selected_player = None

                    elif t == "invite_received":
                        self.invite_from = msg.get("from")
                        self.set_status(f"{self.invite_from} invited you.", TITLE_COLOR)

                    elif t == "match_start":
                        self.current_opponent = msg.get("opponent", "")
                        self.role = msg.get("role", "player")
                        self.screen_name = "game"
                        self.invite_from = None
                        self.rematch_from = None
                        self.chat_input.text = ""
                        self.chat_input.active = False
                        self.set_status(f"Match started vs {self.current_opponent}", ACCENT_GREEN)

                    elif t == "state":
                        self.previous_state = self.current_state
                        self.current_state = msg

                        self.last_state_time = self.current_state_time
                        self.current_state_time = pygame.time.get_ticks()

                        if "game_duration" in msg:
                            self.game_duration = msg["game_duration"]

                    elif t == "game_over":
                        self.current_state = msg.get("final_state")
                        self.last_winner = msg.get("winner")
                        self.screen_name = "result"
                        self.role = "lobby"
                        self.chat_input.text = ""
                        self.chat_input.active = False
                        self.set_status(f"Game over. Winner: {self.last_winner}", TITLE_COLOR)

                    elif t == "watch_ok":
                        self.role = "viewer"
                        self.screen_name = "game"
                        self.chat_input.text = ""
                        self.chat_input.active = False
                        self.set_status("You are now watching the match.", ACCENT_GREEN)

                    elif t == "rematch_offer":
                        self.rematch_from = msg.get("from")
                        self.set_status(f"{self.rematch_from} wants to play again.", TITLE_COLOR)

                    elif t == "system":
                        self.set_status(msg.get("message", ""))

        except Exception:
            if self.running:
                self.set_status("Disconnected from server.", ACCENT_RED)

        finally:
            self.connected = False

    def open_customize(self):
        self.screen_name = "customize"
        self.set_status("Choose a color and controls.")

    def open_setup(self):
        self.screen_name = "setup"
        self.awaiting_key_for = None

    def reset_keys(self):
        self.keymap = dict(DEFAULT_KEYS)
        self.set_status("Controls reset to W A S D.")

    def invite_selected_player(self):
        if not self.selected_player:
            self.set_status("Select a player first.", ACCENT_RED)
            return

        if self.sock:
            try:
                send_json(self.sock, {"type": "select_style", "color": list(self.selected_color)})
                send_json(self.sock, {"type": "invite_player", "target": self.selected_player})
                self.set_status(f"Invite sent to {self.selected_player}.", ACCENT_GREEN)
            except Exception:
                self.set_status("Could not send invite.", ACCENT_RED)

    def accept_invite(self):
        if self.sock and self.invite_from:
            try:
                send_json(self.sock, {"type": "accept_invite", "from": self.invite_from})
                self.set_status(f"Accepted invite from {self.invite_from}.", ACCENT_GREEN)
                self.invite_from = None
            except Exception:
                self.set_status("Could not accept invite.", ACCENT_RED)

    def dismiss_invite(self):
        self.invite_from = None
        self.set_status("Invite dismissed.")

    def watch_game(self):
        if self.sock:
            try:
                send_json(self.sock, {"type": "watch_game"})
            except Exception:
                self.set_status("Could not watch game.", ACCENT_RED)

    def toggle_pause_game(self):
        if self.sock and self.role == "player":
            try:
                send_json(self.sock, {"type": "pause_toggle"})
            except Exception:
                self.set_status("Could not pause game.", ACCENT_RED)

    def send_game_message(self):
        if not self.sock or self.role != "player":
            return

        text = self.chat_input.text.strip()
        if not text:
            return

        try:
            send_json(self.sock, {"type": "chat", "message": text})
            self.chat_input.text = ""
        except Exception:
            self.set_status("Could not send message.", ACCENT_RED)

    def send_cheer_message(self):
        if self.sock and self.role == "viewer":
            try:
                send_json(self.sock, {"type": "cheer", "message": "Go go go!"})
                self.set_status("Cheer sent!", ACCENT_GREEN)
            except Exception:
                self.set_status("Could not send cheer.", ACCENT_RED)

    def request_rematch(self):
        if self.sock and self.current_opponent:
            try:
                send_json(self.sock, {"type": "rematch_request", "target": self.current_opponent})
                self.set_status(f"Play again request sent to {self.current_opponent}.", ACCENT_GREEN)
            except Exception:
                self.set_status("Could not send play again request.", ACCENT_RED)

    def accept_rematch(self):
        if self.sock and self.rematch_from:
            try:
                send_json(self.sock, {"type": "accept_rematch", "from": self.rematch_from})
                self.set_status(f"Accepted play again request from {self.rematch_from}.", ACCENT_GREEN)
                self.rematch_from = None
            except Exception:
                self.set_status("Could not accept play again request.", ACCENT_RED)

    def decline_rematch(self):
        if self.sock and self.rematch_from:
            try:
                send_json(self.sock, {"type": "decline_rematch", "from": self.rematch_from})
                self.set_status("Play again request declined.")
                self.rematch_from = None
            except Exception:
                self.set_status("Could not decline play again request.", ACCENT_RED)

    def back_to_lobby_from_result(self):
        self.screen_name = "lobby"
        self.current_state = None
        self.last_winner = None
        self.rematch_from = None

    def draw_gradient_background(self, top=(18, 40, 30), bottom=(4, 14, 10)):
        for y in range(WINDOW_HEIGHT):
            t = y / max(1, WINDOW_HEIGHT - 1)
            color = (
                int(top[0] * (1 - t) + bottom[0] * t),
                int(top[1] * (1 - t) + bottom[1] * t),
                int(top[2] * (1 - t) + bottom[2] * t),
            )
            pygame.draw.line(self.screen, color, (0, y), (WINDOW_WIDTH, y))

        glow = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (40, 110, 70, 32), (-80, 60, 500, 220))
        pygame.draw.ellipse(glow, (30, 90, 60, 26), (760, 420, 430, 220))
        pygame.draw.ellipse(glow, (55, 140, 85, 22), (250, 500, 450, 180))
        self.screen.blit(glow, (0, 0))

    def _with_alpha(self, color, alpha):
        if len(color) == 4:
            return color
        return (color[0], color[1], color[2], alpha)

    def draw_glass_panel(self, rect, fill=(0, 28, 18, 145), border=(104, 215, 136), radius=22, shadow=True):
        if shadow:
            shadow_surf = pygame.Surface((rect.w + 18, rect.h + 18), pygame.SRCALPHA)
            pygame.draw.rect(
                shadow_surf,
                (0, 0, 0, 80),
                pygame.Rect(9, 9, rect.w, rect.h),
                border_radius=radius + 2
            )
            self.screen.blit(shadow_surf, (rect.x - 9, rect.y - 9))

        panel = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        pygame.draw.rect(panel, self._with_alpha(fill, 145), pygame.Rect(0, 0, rect.w, rect.h), border_radius=radius)
        pygame.draw.rect(panel, self._with_alpha(border, 255), pygame.Rect(0, 0, rect.w, rect.h), 2, border_radius=radius)
        pygame.draw.line(panel, (255, 255, 255, 35), (18, 10), (rect.w - 18, 10), 1)
        self.screen.blit(panel, rect.topleft)

    def draw_card(self, rect, color=(0, 24, 16, 150), border=(104, 180, 125), radius=18):
        panel = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        pygame.draw.rect(panel, self._with_alpha(color, 150), pygame.Rect(0, 0, rect.w, rect.h), border_radius=radius)
        pygame.draw.rect(panel, self._with_alpha(border, 230), pygame.Rect(0, 0, rect.w, rect.h), 2, border_radius=radius)
        pygame.draw.line(panel, (255, 255, 255, 28), (16, 9), (rect.w - 16, 9), 1)
        self.screen.blit(panel, rect.topleft)

    def draw_status_bar(self):
        bar = pygame.Rect(16, WINDOW_HEIGHT - 46, WINDOW_WIDTH - 32, STATUS_BAR_H)
        pygame.draw.rect(self.screen, (16, 18, 17), bar, border_radius=10)
        pygame.draw.rect(self.screen, (85, 91, 82), bar, 1, border_radius=10)

        txt = self.small_font.render(self.status_message[:140], True, self.status_color)
        self.screen.blit(txt, (bar.x + 12, bar.y + 8))

    def draw_pie(self, x, y, pie_type, board_rect):
        cx = board_rect.x + x * CELL_SIZE + CELL_SIZE // 2
        cy = board_rect.y + y * CELL_SIZE + CELL_SIZE // 2

        crust = (165, 110, 60)
        filling = (235, 90, 90) if pie_type == "normal" else (180, 90, 255)
        cream = (255, 240, 220)

        pygame.draw.circle(self.screen, crust, (cx, cy), 8)
        pygame.draw.circle(self.screen, filling, (cx, cy), 6)
        pygame.draw.arc(self.screen, cream, (cx - 6, cy - 6, 12, 12), 0.5, 2.6, 2)
        pygame.draw.line(self.screen, cream, (cx - 3, cy + 1), (cx + 3, cy - 2), 2)

    def draw_rabbit(self, x, y, board_rect):
        cx = board_rect.x + x * CELL_SIZE + CELL_SIZE // 2
        cy = board_rect.y + y * CELL_SIZE + CELL_SIZE // 2

        pygame.draw.ellipse(self.screen, (235, 235, 235), (cx - 6, cy - 10, 5, 11))
        pygame.draw.ellipse(self.screen, (235, 235, 235), (cx + 1, cy - 10, 5, 11))
        pygame.draw.ellipse(self.screen, (255, 182, 193), (cx - 5, cy - 8, 2, 7))
        pygame.draw.ellipse(self.screen, (255, 182, 193), (cx + 2, cy - 8, 2, 7))

        pygame.draw.circle(self.screen, (242, 242, 242), (cx, cy), 7)
        pygame.draw.circle(self.screen, (0, 0, 0), (cx - 2, cy - 1), 1)
        pygame.draw.circle(self.screen, (0, 0, 0), (cx + 2, cy - 1), 1)
        pygame.draw.circle(self.screen, (255, 122, 122), (cx, cy + 2), 2)

    def update_game_widget_positions(self):
        input_y = RIGHT_PANEL_Y + RIGHT_PANEL_H - 66
        self.chat_input.rect.x = RIGHT_PANEL_X + 16
        self.chat_input.rect.y = input_y
        self.chat_input.rect.w = RIGHT_PANEL_W - 112
        self.chat_input.rect.h = 40

        self.send_button.rect.x = self.chat_input.rect.right + 8
        self.send_button.rect.y = input_y
        self.send_button.rect.w = 72
        self.send_button.rect.h = 40

    def draw_simple_snake_intro(self, points, color, thickness=26, tongue=False, tail=False):
        if len(points) < 2:
            return

        pygame.draw.lines(self.screen, color, False, points, thickness)

        for px, py in points[1:-1]:
            pygame.draw.circle(self.screen, color, (int(px), int(py)), thickness // 2)

        hx, hy = points[0]
        head_color = tuple(min(255, c + 18) for c in color)
        pygame.draw.circle(self.screen, head_color, (int(hx), int(hy)), thickness // 2 + 2)
        pygame.draw.circle(self.screen, (255, 255, 255), (int(hx + 6), int(hy - 4)), 3)
        pygame.draw.circle(self.screen, (255, 255, 255), (int(hx + 6), int(hy + 4)), 3)
        pygame.draw.circle(self.screen, (5, 20, 12), (int(hx + 6), int(hy - 4)), 1)
        pygame.draw.circle(self.screen, (5, 20, 12), (int(hx + 6), int(hy + 4)), 1)

        if tongue:
            pygame.draw.line(
                self.screen,
                (255, 92, 130),
                (int(hx + thickness // 2 - 2), int(hy)),
                (int(hx + thickness // 2 + 10), int(hy)),
                2,
            )

        if tail:
            tx, ty = points[-1]
            tail_color = tuple(max(0, c - 20) for c in color)
            pygame.draw.circle(self.screen, tail_color, (int(tx), int(ty)), thickness // 2)

    def draw_intro_background_friend_style_green(self):
        self.draw_image_background((0, 30, 15, 35))
    def draw_intro_chip_icon(self, kind, x, y):
        if kind == "normal":
            self.draw_pie(0, 0, "normal", pygame.Rect(x, y, 30, 30))
        elif kind == "bonus":
            self.draw_pie(0, 0, "bonus", pygame.Rect(x, y, 30, 30))
        elif kind == "spike":
            self.draw_intro_spikes_icon(x, y + 5)
        elif kind in ("wall", "obstacle"):
            pygame.draw.rect(self.screen, (135, 145, 135), (x + 4, y + 9, 28, 20), border_radius=4)
        elif kind == "rabbit":
            self.draw_rabbit(0, 0, pygame.Rect(x, y, 30, 30))
        elif kind == "time":
            pygame.draw.circle(self.screen, (255, 217, 107), (x + 18, y + 18), 13, 2)

    def draw_intro(self):
        self.draw_intro_background_friend_style_green()

        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 18, 10, 35))
        self.screen.blit(overlay, (0, 0))

        title_shadow = self.title_font.render("How to Play", True, (0, 0, 0))
        self.screen.blit(title_shadow, title_shadow.get_rect(center=(WINDOW_WIDTH // 2 + 3, 82 + 3)))

        title = self.title_font.render("How to Play", True, (248, 252, 250))
        self.screen.blit(title, title.get_rect(center=(WINDOW_WIDTH // 2, 82)))

        subtitle = self.font.render("Welcome to Πthon Arena", True, (215, 239, 222))
        self.screen.blit(subtitle, subtitle.get_rect(center=(WINDOW_WIDTH // 2, 132)))

        left_box = pygame.Rect(70, 185, 530, 300)
        right_box = pygame.Rect(660, 185, 530, 300)

        self.draw_glass_panel(left_box, fill=(0, 35, 20, 145), border=(105, 225, 145), radius=28)
        self.draw_glass_panel(right_box, fill=(0, 35, 20, 145), border=(105, 225, 145), radius=28)

        self.screen.blit(
            self.rule_title_font.render("Game Rules", True, (248, 252, 250)),
            (left_box.x + 30, left_box.y + 24)
        )

        rules = [
            "Snake moves after your first direction key",
            "Use your chosen keys to move the snake",
            "Normal pie: +10 health, bonus pie: +20",
            "Wall, obstacle, and spike collisions reduce health",
            "Rabbit gives shield power",
            "Invite another player from the lobby",
        ]

        ry = left_box.y + 85
        for line in rules:
            bullet_x = left_box.x + 30
            text_x = left_box.x + 52
            pygame.draw.circle(self.screen, (120, 235, 155), (bullet_x, ry + 11), 4)
            txt = self.small_font.render(line, True, (238, 246, 241))
            self.screen.blit(txt, (text_x, ry))
            ry += 36

        self.screen.blit(
            self.rule_title_font.render("Special Features", True, (248, 252, 250)),
            (right_box.x + 30, right_box.y + 24)
        )

        features = [
            ("💬", "Text Chat", "Players chat during battle."),
            ("📣", "Fans", "Fans use preset cheers only."),
            ("🐇", "Rabbit Shield", "Rabbit appears mid-game and gives 5s shield."),
        ]

        fy = right_box.y + 82
        for icon, feature_title, body in features:
            row = pygame.Rect(right_box.x + 25, fy, right_box.w - 50, 62)
            self.draw_glass_panel(row, fill=(0, 45, 25, 100), border=(100, 205, 135), radius=18, shadow=False)

            self.screen.blit(self.emoji_font.render(icon, True, (255, 255, 255)), (row.x + 18, row.y + 11))
            self.screen.blit(self.small_font.render(feature_title, True, (248, 252, 250)), (row.x + 64, row.y + 10))
            self.screen.blit(self.tiny_font.render(body, True, (205, 230, 212)), (row.x + 18, row.y + 38))
            fy += 76

        chips = [
            ("normal", "Normal pie: +10", (106, 208, 120)),
            ("bonus", "Bonus pie: +20", (245, 205, 92)),
            ("spike", "Spikes: -30", (255, 110, 110)),
            ("wall", "Wall: -15", (170, 176, 186)),
            ("obstacle", "Obstacle: -20", (170, 176, 186)),
            ("rabbit", "5s shield", (204, 160, 255)),
            ("time", f"Time: {self.game_duration}s", (245, 205, 92)),
        ]

        chip_rects = [
            pygame.Rect(138, 515, 205, 52),
            pygame.Rect(368, 515, 205, 52),
            pygame.Rect(598, 515, 180, 52),
            pygame.Rect(803, 515, 160, 52),
            pygame.Rect(300, 575, 205, 52),
            pygame.Rect(530, 575, 170, 52),
            pygame.Rect(725, 575, 170, 52),
        ]

        for (kind, text, outline), rect in zip(chips, chip_rects):
            self.draw_glass_panel(rect, fill=(0, 28, 18, 135), border=outline, radius=20, shadow=True)
            self.draw_intro_chip_icon(kind, rect.x + 10, rect.y + 8)
            self.screen.blit(self.small_font.render(text, True, (248, 252, 250)), (rect.x + 57, rect.y + 15))

        if self.intro_buttons:
            btn = self.intro_buttons[0]
            btn.rect.w = 220
            btn.rect.h = 54
            btn.rect.centerx = WINDOW_WIDTH // 2
            btn.rect.y = 650
            btn.bg = (100, 180, 105)

        for btn in self.intro_buttons:
            btn.draw(self.screen, self.font)

    def draw_setup(self):
        self.draw_image_background((0, 25, 15, 110))
        self.screen.blit(self.title_font.render("Πthon Arena", True, TITLE_COLOR), (50, 52))
        self.screen.blit(self.small_font.render("Enter server information and join the lobby.", True, SUBTEXT_COLOR), (56, 105))

        left = pygame.Rect(38, 155, 390, 360)
        right = pygame.Rect(470, 155, 540, 360)
        self.draw_card(left)
        self.draw_card(right, color=(21, 24, 21))

        self.ip_field.draw(self.screen, self.font, "Server IP")
        self.port_field.draw(self.screen, self.font, "Port")
        self.name_field.draw(self.screen, self.font, "Username")

        for btn in self.setup_buttons:
            btn.draw(self.screen, self.font)

        self.screen.blit(self.big_font.render("Preview", True, TEXT_COLOR), (498, 185))
        self.screen.blit(self.small_font.render(f"Selected color: {self.selected_color_name}", True, SUBTEXT_COLOR), (503, 245))

        preview_box = pygame.Rect(503, 285, 320, 82)
        pygame.draw.rect(self.screen, CARD_FILL, preview_box, border_radius=14)

        for i in range(6):
            seg = pygame.Rect(526 + i * 40, 310, 30, 30)
            pygame.draw.rect(self.screen, self.selected_color, seg, border_radius=8)
            if i == 0:
                pygame.draw.rect(self.screen, (255, 255, 255), seg, 2, border_radius=8)

        key_text = "   ".join([f"{d}: {pygame.key.name(self.keymap[d]).upper()}" for d in KEY_ORDER])
        self.screen.blit(self.small_font.render("Controls", True, SUBTEXT_COLOR), (503, 405))
        self.screen.blit(self.font.render(key_text, True, TEXT_COLOR), (503, 435))

        self.draw_status_bar()

    def draw_customize(self):
        self.draw_image_background((8, 12, 8, 125))
        self.screen.blit(self.big_font.render("Customize", True, TITLE_COLOR), (52, 42))
        self.screen.blit(self.small_font.render("Pick a color and set your movement keys.", True, SUBTEXT_COLOR), (56, 88))

        left = pygame.Rect(36, 130, 410, 520)
        right = pygame.Rect(485, 130, 570, 520)
        self.draw_card(left)
        self.draw_card(right)

        self.screen.blit(self.font.render("Snake Colors", True, TEXT_COLOR), (58, 160))

        for idx, entry in enumerate(COLOR_OPTIONS):
            color = entry["rgb"]
            x = 60 + (idx % 2) * 165
            y = 205 + (idx // 2) * 68

            swatch = pygame.Rect(x, y, 128, 44)
            pygame.draw.rect(self.screen, color, swatch, border_radius=12)
            border = (255, 255, 255) if idx == self.selected_color_index else (70, 80, 110)
            pygame.draw.rect(self.screen, border, swatch, 3, border_radius=12)

            label_color = (18, 18, 18) if sum(color) > 500 else (255, 255, 255)
            name = self.small_font.render(entry["name"], True, label_color)
            self.screen.blit(name, name.get_rect(center=swatch.center))

        self.screen.blit(self.font.render("Controls", True, TEXT_COLOR), (516, 160))

        for i, direction in enumerate(KEY_ORDER):
            row = pygame.Rect(516, 205 + i * 76, 490, 52)
            bg = (105, 96, 67) if self.awaiting_key_for == direction else (42, 48, 44)
            pygame.draw.rect(self.screen, bg, row, border_radius=14)
            pygame.draw.rect(self.screen, (126, 137, 114), row, 2, border_radius=14)

            self.screen.blit(self.font.render(direction.title(), True, TEXT_COLOR), (540, row.y + 13))
            value = "Press any key..." if self.awaiting_key_for == direction else pygame.key.name(self.keymap[direction]).upper()
            self.screen.blit(self.font.render(value, True, TITLE_COLOR), (760, row.y + 13))

        preview = pygame.Rect(516, 540, 220, 66)
        pygame.draw.rect(self.screen, CARD_FILL, preview, border_radius=14)
        for i in range(4):
            seg = pygame.Rect(540 + i * 34, 558, 27, 27)
            pygame.draw.rect(self.screen, self.selected_color, seg, border_radius=8)
        self.screen.blit(self.small_font.render(f"Preview - {self.selected_color_name}", True, SUBTEXT_COLOR), (516, 515))

        for btn in self.customize_buttons:
            btn.draw(self.screen, self.font)

        self.draw_status_bar()

    def draw_lobby(self):
        self.draw_image_background((5, 15, 8, 115))

        self.screen.blit(self.big_font.render("Lobby", True, TITLE_COLOR), (46, 36))
        self.screen.blit(self.small_font.render(f"Connected as {self.my_username}", True, SUBTEXT_COLOR), (50, 82))

        left = pygame.Rect(36, 115, 800, 520)
        right = pygame.Rect(866, 80, 360, 555)
        self.draw_card(left)
        self.draw_card(right)

        self.screen.blit(self.font.render("Online Players", True, TEXT_COLOR), (56, 140))
        self.screen.blit(self.small_font.render("Select one player, then press Invite.", True, SUBTEXT_COLOR), (56, 170))

        y = 210
        if not self.players_list:
            self.screen.blit(self.font.render("No other players online yet.", True, SUBTEXT_COLOR), (66, y))
        else:
            for idx, player in enumerate(self.players_list[:8]):
                card = pygame.Rect(58, y + idx * 52, 720, 40)
                selected = player == self.selected_player

                fill = (57, 70, 54) if selected else (29, 34, 30)
                border = (145, 176, 126) if selected else (81, 88, 78)

                pygame.draw.rect(self.screen, fill, card, border_radius=10)
                pygame.draw.rect(self.screen, border, card, 2, border_radius=10)
                self.screen.blit(self.font.render(player, True, TEXT_COLOR), (74, card.y + 8))

        for btn in self.lobby_buttons:
            btn.draw(self.screen, self.font)

        self.screen.blit(self.font.render("Your Snake", True, TEXT_COLOR), (888, 245))
        preview_card = pygame.Rect(888, 282, 310, 115)
        pygame.draw.rect(self.screen, CARD_FILL, preview_card, border_radius=14)
        self.screen.blit(self.small_font.render(f"Color: {self.selected_color_name}", True, SUBTEXT_COLOR), (906, 305))

        for i in range(5):
            seg = pygame.Rect(910 + i * 40, 340, 30, 30)
            pygame.draw.rect(self.screen, self.selected_color, seg, border_radius=8)
            if i == 0:
                pygame.draw.rect(self.screen, (255, 255, 255), seg, 2, border_radius=8)

        if self.invite_from:
            self.screen.blit(self.font.render("Incoming Invite", True, TITLE_COLOR), (888, 430))
            self.screen.blit(self.small_font.render(f"From: {self.invite_from}", True, TEXT_COLOR), (888, 460))

            for btn in self.invite_response_buttons:
                btn.draw(self.screen, self.small_font)

        self.draw_status_bar()
    def get_smooth_body(self, username, pdata):
        """
        Original movement style: no interpolation.
        The snake draws exactly where the server says it is.
        """
        current_body = pdata.get("body", [])
        return [(float(x), float(y)) for x, y in current_body]

    def draw_game(self):
        self.draw_image_background((8, 12, 8, 145))
        self.update_game_widget_positions()

        board_rect = pygame.Rect(BOARD_X, BOARD_Y, BOARD_PIXEL_W, BOARD_PIXEL_H)
        panel_rect = pygame.Rect(RIGHT_PANEL_X, RIGHT_PANEL_Y, RIGHT_PANEL_W, RIGHT_PANEL_H)

        self.draw_card(board_rect.inflate(8, 8), color=(18, 22, 18), border=(73, 84, 69), radius=16)
        self.draw_card(panel_rect, color=(20, 23, 20), border=(84, 94, 79), radius=18)

        pygame.draw.rect(self.screen, (25, 28, 25), board_rect, border_radius=12)

        for x in range(BOARD_WIDTH):
            for y in range(BOARD_HEIGHT):
                r = pygame.Rect(board_rect.x + x * CELL_SIZE, board_rect.y + y * CELL_SIZE, CELL_SIZE, CELL_SIZE)
                shade = BOARD_DARK_1 if (x + y) % 2 == 0 else BOARD_DARK_2
                pygame.draw.rect(self.screen, shade, r)

        state = self.current_state or {}

        for ox, oy in state.get("obstacles", []):
            rect = pygame.Rect(board_rect.x + ox * CELL_SIZE, board_rect.y + oy * CELL_SIZE, CELL_SIZE, CELL_SIZE)
            pygame.draw.rect(self.screen, (121, 126, 118), rect, border_radius=6)

        for sx, sy in state.get("spikes", []):
            px = board_rect.x + sx * CELL_SIZE
            py = board_rect.y + sy * CELL_SIZE
            points = [
                (px + 2, py + CELL_SIZE - 3),
                (px + 7, py + 5),
                (px + 12, py + CELL_SIZE - 3),
                (px + 17, py + 5),
                (px + 20, py + CELL_SIZE - 3),
            ]
            pygame.draw.polygon(self.screen, (214, 88, 88), points)

        rabbit = state.get("rabbit")
        if rabbit:
            self.draw_rabbit(rabbit["x"], rabbit["y"], board_rect)

        for pie in state.get("pies", []):
            self.draw_pie(pie["x"], pie["y"], pie["type"], board_rect)

        players = state.get("players", {})

        leader = None
        lead_health = -1
        for username, pdata in players.items():
            if pdata["health"] > lead_health:
                lead_health = pdata["health"]
                leader = username

        for username, pdata in players.items():
            color = tuple(pdata["color"])
            smooth_body = self.get_smooth_body(username, pdata)

            for i, (x, y) in enumerate(smooth_body):
                if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT:
                    px = board_rect.x + x * CELL_SIZE
                    py = board_rect.y + y * CELL_SIZE

                    rect = pygame.Rect(
                        int(px),
                        int(py),
                        CELL_SIZE,
                        CELL_SIZE
                    )

                    pygame.draw.rect(self.screen, color, rect, border_radius=8)

                    if i == 0:
                        pygame.draw.rect(self.screen, (255, 255, 255), rect, 2, border_radius=8)

                        pygame.draw.circle(self.screen, (255, 255, 255), (rect.x + 7, rect.y + 7), 2)
                        pygame.draw.circle(self.screen, (255, 255, 255), (rect.x + 14, rect.y + 7), 2)
                        pygame.draw.circle(self.screen, (20, 20, 20), (rect.x + 7, rect.y + 7), 1)
                        pygame.draw.circle(self.screen, (20, 20, 20), (rect.x + 14, rect.y + 7), 1)

            if smooth_body:
                hx, hy = smooth_body[0]

                if 0 <= hx < BOARD_WIDTH and 0 <= hy < BOARD_HEIGHT:
                    head_center_x = board_rect.x + hx * CELL_SIZE + CELL_SIZE // 2
                    head_top_y = board_rect.y + hy * CELL_SIZE

                    name_surf = self.tiny_font.render(username, True, color)
                    label_rect = name_surf.get_rect()
                    label_rect.centerx = int(head_center_x)
                    label_rect.bottom = int(head_top_y) - 5

                    label_rect.x = max(
                        board_rect.x + 2,
                        min(label_rect.x, board_rect.right - label_rect.w - 2)
                    )

                    if label_rect.y < board_rect.y + 2:
                        label_rect.y = int(head_top_y) + CELL_SIZE + 5

                    self.screen.blit(name_surf, label_rect)

        px = RIGHT_PANEL_X + 16
        py = RIGHT_PANEL_Y + 12
        section_w = RIGHT_PANEL_W - 32

        self.screen.blit(self.font.render(f"Time Left: {state.get('time_left', 0)}", True, TITLE_COLOR), (px, py))
        self.screen.blit(self.small_font.render(f"Role: {self.role.upper()}", True, SUBTEXT_COLOR), (px, py + 28))
        if leader:
            self.screen.blit(self.font.render(f"Leader: {leader}", True, ACCENT_GREEN), (px, py + 52))

        card_y = py + 88
        card_h = 56
        for username, pdata in players.items():
            card = pygame.Rect(px, card_y, section_w, card_h)
            border_col = ACCENT_GOLD if pdata.get("invincible") else tuple(pdata["color"])
            pygame.draw.rect(self.screen, CARD_FILL, card, border_radius=14)
            pygame.draw.rect(self.screen, border_col, card, 2, border_radius=14)

            self.screen.blit(self.font.render(username, True, TEXT_COLOR), (card.x + 14, card.y + 7))
            self.screen.blit(self.emoji_font.render("❤", True, (255, 80, 100)), (card.x + 14, card.y + 30))
            self.screen.blit(self.small_font.render(f"Health: {pdata['health']}", True, TEXT_COLOR), (card.x + 38, card.y + 32))

            if pdata.get("invincible"):
                inv_line = f"Shield: {pdata.get('invincible_left', 0):.1f}s"
                rendered = self.tiny_font.render(inv_line, True, TITLE_COLOR)
                self.screen.blit(rendered, (card.right - rendered.get_width() - 12, card.y + 33))

            card_y += card_h + 8

        controls_y = card_y + 2
        self.pause_button.visible = (self.role == "player")
        self.pause_button.text = "Resume" if state.get("paused") else "Pause"
        self.pause_button.rect.x = px
        self.pause_button.rect.y = controls_y
        self.pause_button.rect.w = 110
        self.pause_button.rect.h = 34

        if self.role == "player":
            self.pause_button.draw(self.screen, self.small_font)

        rabbit_text = self.small_font.render("Rabbit = 5s shield", True, SUBTEXT_COLOR)
        self.screen.blit(rabbit_text, (px + 126, controls_y + 8))

        chat_title_y = controls_y + 46
        self.screen.blit(self.font.render("Live Chat", True, TEXT_COLOR), (px, chat_title_y))

        chat_box = pygame.Rect(px, chat_title_y + 26, section_w, 74)
        pygame.draw.rect(self.screen, (22, 25, 22), chat_box, border_radius=12)
        pygame.draw.rect(self.screen, (86, 94, 81), chat_box, 2, border_radius=12)

        cy = chat_box.y + 8
        for line in state.get("chat_log", [])[-3:]:
            rendered = self.tiny_font.render(line[:42], True, TEXT_COLOR)
            self.screen.blit(rendered, (chat_box.x + 10, cy))
            cy += 20

        fans_title_y = chat_box.bottom + 12
        self.screen.blit(self.font.render("Fans", True, TITLE_COLOR), (px, fans_title_y))

        fans_box = pygame.Rect(px, fans_title_y + 26, section_w, 78)
        pygame.draw.rect(self.screen, (22, 25, 22), fans_box, border_radius=12)
        pygame.draw.rect(self.screen, (86, 94, 81), fans_box, 2, border_radius=12)

        if self.role == "viewer":
            self.cheer_button.visible = True
            self.cheer_button.rect.x = fans_box.x + 12
            self.cheer_button.rect.y = fans_box.y + 12
            self.cheer_button.rect.w = 118
            self.cheer_button.rect.h = 34
            self.cheer_button.draw(self.screen, self.tiny_font)

            self.screen.blit(self.tiny_font.render("Press the button to cheer for players.", True, SUBTEXT_COLOR), (fans_box.x + 12, fans_box.y + 52))
        else:
            self.cheer_button.visible = False
            self.screen.blit(self.tiny_font.render("Only viewers can send cheers.", True, SUBTEXT_COLOR), (fans_box.x + 12, fans_box.y + 12))
            cheers = state.get("cheers", [])
            preview = cheers[-1][:40] if cheers else "No cheers yet."
            self.screen.blit(self.tiny_font.render(preview, True, TEXT_COLOR), (fans_box.x + 12, fans_box.y + 40))

        if self.role == "player":
            self.chat_input.draw(self.screen, self.small_font, "Message")
            self.send_button.draw(self.screen, self.small_font)
        else:
            note_y = RIGHT_PANEL_Y + RIGHT_PANEL_H - 54
            self.screen.blit(self.tiny_font.render("Viewers watch and use Go Go Go!", True, SUBTEXT_COLOR), (px, note_y))

        if state.get("paused"):
            overlay = pygame.Surface((board_rect.w, board_rect.h), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 120))
            self.screen.blit(overlay, (board_rect.x, board_rect.y))

            paused_by = state.get("paused_by") or "a player"
            self.center_text("PAUSED", self.big_font, TITLE_COLOR, board_rect.centerx, board_rect.centery - 20)
            self.center_text(f"by {paused_by}", self.font, TEXT_COLOR, board_rect.centerx, board_rect.centery + 20)

        self.draw_status_bar()

    def draw_result(self):
        self.draw_image_background((12, 10, 8, 130))

        center = pygame.Rect(150, 78, 960, 560)
        self.draw_card(center, color=(23, 24, 21), border=(99, 105, 89), radius=18)

        title = "Victory" if self.last_winner == self.my_username else ("Draw" if self.last_winner == "DRAW" else "Match Over")
        self.center_text(title, self.big_font, TITLE_COLOR, center.centerx, 130)

        winner_line = f"Winner: {self.last_winner}" if self.last_winner else "Winner: -"
        self.center_text(winner_line, self.font, TEXT_COLOR, center.centerx, 175)
        self.center_text("Final Results", self.small_font, SUBTEXT_COLOR, center.centerx, 210)

        if self.current_state:
            players = self.current_state.get("players", {})
            row_y = 255

            for username, pdata in players.items():
                is_draw = self.last_winner == "DRAW"
                is_winner = username == self.last_winner

                border = ACCENT_GREEN if is_winner else (ACCENT_RED if not is_draw else (120, 130, 170))
                bg = (20, 44, 24) if is_winner else ((50, 24, 24) if not is_draw else (33, 36, 42))

                row = pygame.Rect((WINDOW_WIDTH - 660) // 2, row_y, 660, 82)
                pygame.draw.rect(self.screen, bg, row, border_radius=16)
                pygame.draw.rect(self.screen, border, row, 3, border_radius=16)

                color_box = pygame.Rect(row.x + 22, row.y + 22, 42, 36)
                pygame.draw.rect(self.screen, tuple(pdata["color"]), color_box, border_radius=8)

                self.screen.blit(self.font.render(username, True, TEXT_COLOR), (row.x + 86, row.y + 14))
                self.screen.blit(self.emoji_font.render("❤", True, (255, 80, 100)), (row.x + 86, row.y + 42))
                self.screen.blit(self.small_font.render(f"Final Health: {pdata['health']}", True, TEXT_COLOR), (row.x + 110, row.y + 44))

                tag = "WINNER" if is_winner else ("DRAW" if is_draw else "LOSER")
                tag_surf = self.font.render(tag, True, border)
                tag_rect = tag_surf.get_rect(center=(row.right - 110, row.centery))
                self.screen.blit(tag_surf, tag_rect)

                row_y += 105

        if self.rematch_from:
            self.center_text(f"{self.rematch_from} wants to play again", self.small_font, TITLE_COLOR, center.centerx, 505)
            for btn in self.rematch_buttons:
                btn.draw(self.screen, self.font)

        for btn in self.result_buttons:
            btn.draw(self.screen, self.font)

        self.draw_status_bar()

    def draw(self):
        if self.screen_name == "intro":
            self.draw_intro()
        elif self.screen_name == "setup":
            self.draw_setup()
        elif self.screen_name == "customize":
            self.draw_customize()
        elif self.screen_name == "lobby":
            self.draw_lobby()
        elif self.screen_name == "game":
            self.draw_game()
        elif self.screen_name == "result":
            self.draw_result()

        pygame.display.flip()

    def cycle_input_focus(self):
        for field in self.inputs:
            field.active = False
        self.active_input_index = (self.active_input_index + 1) % len(self.inputs)
        self.inputs[self.active_input_index].active = True

    def handle_intro_events(self, event):
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self.open_setup()

        for btn in self.intro_buttons:
            btn.handle_event(event)

    def handle_setup_events(self, event):
        for field in self.inputs:
            field.handle_event(event)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_TAB:
                self.cycle_input_focus()
            elif event.key == pygame.K_RETURN:
                self.connect()

        for btn in self.setup_buttons:
            btn.handle_event(event)

    def handle_customize_events(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for idx, entry in enumerate(COLOR_OPTIONS):
                x = 60 + (idx % 2) * 165
                y = 205 + (idx // 2) * 68
                if pygame.Rect(x, y, 128, 44).collidepoint(event.pos):
                    self.selected_color_index = idx
                    self.selected_color = entry["rgb"]
                    self.selected_color_name = entry["name"]
                    self.set_status(f"Selected color: {entry['name']}.")

            for i, direction in enumerate(KEY_ORDER):
                row = pygame.Rect(516, 205 + i * 76, 490, 52)
                if row.collidepoint(event.pos):
                    self.awaiting_key_for = direction
                    self.set_status(f"Press a key for {direction}.")

        elif event.type == pygame.KEYDOWN:
            if self.awaiting_key_for:
                self.keymap[self.awaiting_key_for] = event.key
                self.set_status(f"{self.awaiting_key_for} set to {pygame.key.name(event.key).upper()}")
                self.awaiting_key_for = None
            elif event.key == pygame.K_ESCAPE:
                self.open_setup()

        for btn in self.customize_buttons:
            btn.handle_event(event)

    def handle_lobby_events(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            y = 210
            for idx, player in enumerate(self.players_list[:8]):
                card = pygame.Rect(58, y + idx * 52, 720, 40)
                if card.collidepoint(event.pos):
                    self.selected_player = player
                    self.set_status(f"Selected player: {player}")

        for btn in self.lobby_buttons:
            btn.handle_event(event)

        if self.invite_from:
            for btn in self.invite_response_buttons:
                btn.handle_event(event)

    def handle_game_events(self, event):
        self.update_game_widget_positions()

        if self.role == "player":
            self.chat_input.handle_event(event)

        if event.type == pygame.KEYDOWN:
            if self.role == "player" and self.chat_input.active:
                if event.key == pygame.K_RETURN:
                    self.send_game_message()
                return

            if self.role == "player" and self.sock:
                for direction in KEY_ORDER:
                    if event.key == self.keymap[direction]:
                        try:
                            send_json(self.sock, {"type": "move", "direction": direction})
                        except Exception:
                            self.set_status("Move failed.", ACCENT_RED)

                if event.key == pygame.K_t:
                    self.chat_input.active = True

                if event.key in (pygame.K_p, pygame.K_SPACE):
                    self.toggle_pause_game()

            elif self.role == "viewer" and self.sock:
                if event.key == pygame.K_c:
                    self.send_cheer_message()

        if self.role == "player":
            self.send_button.handle_event(event)
            self.pause_button.handle_event(event)
        if self.role == "viewer":
            self.cheer_button.handle_event(event)

    def handle_result_events(self, event):
        for btn in self.result_buttons:
            btn.handle_event(event)

        if self.rematch_from:
            for btn in self.rematch_buttons:
                btn.handle_event(event)

    def update(self):
        now = pygame.time.get_ticks()

        if self.connected and self.screen_name == "lobby" and now - self.last_players_request > NETWORK_REFRESH_MS:
            try:
                send_json(self.sock, {"type": "get_players"})
                self.last_players_request = now
            except Exception:
                self.set_status("Could not refresh players.", ACCENT_RED)

    def run(self):
        while self.running:
            self.clock.tick(FPS)
            self.update()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    break

                if self.screen_name == "intro":
                    self.handle_intro_events(event)
                elif self.screen_name == "setup":
                    self.handle_setup_events(event)
                elif self.screen_name == "customize":
                    self.handle_customize_events(event)
                elif self.screen_name == "lobby":
                    self.handle_lobby_events(event)
                elif self.screen_name == "game":
                    self.handle_game_events(event)
                elif self.screen_name == "result":
                    self.handle_result_events(event)

            self.draw()

        self.shutdown()

    def shutdown(self):
        try:
            if self.sock:
                send_json(self.sock, {"type": "quit"})
        except Exception:
            pass

        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass

        pygame.quit()


if __name__ == "__main__":
    App().run()
