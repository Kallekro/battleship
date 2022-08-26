import curses
from enum import Enum, auto
from math import ceil
from typing import List, Tuple
from copy import deepcopy
import socket
import argparse
from itertools import chain
from random import randint

PORT = 8047


class Direction(Enum):
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()


def rotate_clockwise(direction: Direction):
    if direction == Direction.UP:
        return Direction.RIGHT
    elif direction == Direction.RIGHT:
        return Direction.DOWN
    elif direction == Direction.DOWN:
        return Direction.LEFT
    elif direction == Direction.LEFT:
        return Direction.UP


def pos_in_bounds(pos, bounds_y, bounds_x) -> bool:
    return (
        pos[0] > bounds_y[0]
        and pos[0] < bounds_y[1]
        and pos[1] > bounds_x[0]
        and pos[1] < bounds_x[1]
    )


class HitType(Enum):
    MISS = auto()
    HIT = auto()
    SUNK = auto()


class Hit:
    def __init__(
        self,
        target_pos: Tuple[int, int],
        hit_type: HitType,
        char: str,
        positions: List[Tuple[int, int]] = [],
    ):
        self.target_position = target_pos
        self.hit_type = hit_type
        self.character = char
        self.ship_positions = positions

    @staticmethod
    def miss(target_pos: Tuple[int, int]):
        return Hit(target_pos, HitType.MISS, "O")

    @staticmethod
    def hit(target_pos: Tuple[int, int]):
        return Hit(target_pos, HitType.HIT, "X")

    @staticmethod
    def sunk(
        target_pos: Tuple[int, int], ship_char: str, positions: List[Tuple[int, int]]
    ):
        return Hit(target_pos, HitType.SUNK, ship_char, positions)


class AI:
    def __init__(self, manager):
        self.manager = manager
        self.fleet = None

    def initialize(self):
        ...

    def place_ships(self):
        raise NotImplementedError("place_ships not implemented")

    def get_move(self, move: Tuple[int, int]) -> Hit:
        return self.fleet.check_hit(move)

    def send_move(self) -> Tuple[int, int]:
        raise NotImplementedError("send_move not implemented")


class CopyCatAI(AI):
    def __init__(self, manager):
        super().__init__(manager)
        self.last_player_move = None

    def place_ships(self):
        self.fleet = deepcopy(self.manager.fleet)

    def get_move(self, move: Tuple[int, int]) -> Hit:
        self.last_player_move = move
        return super().get_move(move)

    def send_move(self) -> Tuple[int, int]:
        return self.last_player_move


class CopyCatWithRandomMissilesAI(AI):
    def __init__(self, manager):
        super().__init__(manager)
        self.possible_moves = []

    def initialize(self):
        self.possible_moves = list(
            chain.from_iterable(
                [
                    list(
                        zip(
                            [i] * self.manager.player_bounds_x[1],
                            range(
                                self.manager.player_bounds_x[0] + 1,
                                self.manager.player_bounds_x[1],
                            ),
                        )
                    )
                    for i in range(
                        self.manager.player_bounds_y[0] + 1,
                        self.manager.player_bounds_y[1],
                    )
                ]
            )
        )

    def place_ships(self):
        self.fleet = deepcopy(self.manager.fleet)

    def send_move(self) -> Tuple[int, int]:
        move_idx = randint(0, len(self.possible_moves) - 1)
        return self.possible_moves.pop(move_idx)


class OmniscientAI(AI):
    def __init__(self, manager):
        super().__init__(manager)

    def place_ships(self):
        self.fleet = deepcopy(self.manager.fleet)

    def send_move(self) -> Tuple[int, int]:
        ...


class AIType(Enum):
    CopyCat = "copycat"
    CopyCatWithRandomMissiles = "copycat-random-missiles"
    Omniscient = "omniscient"

    @staticmethod
    def get_ai(ai_type):
        if ai_type == AIType.CopyCat:
            return CopyCatAI
        elif ai_type == AIType.CopyCatWithRandomMissiles:
            return CopyCatWithRandomMissilesAI
        elif ai_type == AIType.Omniscient:
            return OmniscientAI


class Player:
    def __init__(self, first_turn):
        self.players_turn = first_turn
        self.manager = None
        self.ai_type = None

    def set_manager(self, manager):
        self.manager = manager


class Multiplayer(Player):
    def __init__(self, connection, opponent_addr, first_turn):
        self.connection: socket.socket = connection
        self.opponent_addr = opponent_addr
        super().__init__(first_turn)

    def ready(self):
        self.connection.send("ready".encode())
        while True:
            rec_msg = self.connection.recv(1024).decode()
            if rec_msg == "ready":
                break

    def send_move(self, pos) -> Hit:
        self.connection.send("move_%d_%d" % pos)

    def listen_for_move(self) -> str:
        while True:
            rec_msg = self.connection.recv(1024).decode()
            if rec_msg.starstwith("move_"):
                return rec_msg


class LocalPlayer(Player):
    def __init__(self, ai_type: AIType):
        super().__init__(True)
        self.ai_type = ai_type
        self.ai = None

    def set_manager(self, manager):
        self.ai = AIType.get_ai(self.ai_type)(manager)
        return super().set_manager(manager)

    def ready(self):
        self.ai.place_ships()

    def send_move(self, move: Tuple[int, int]) -> Hit:
        return self.ai.get_move(move)

    def listen_for_move(self) -> Hit:
        ai_move = self.ai.send_move()
        return self.manager.fleet.check_hit(ai_move)


class Host:
    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("", PORT))
        self.socket.listen(1)

    def wait_for_opponent(self) -> Multiplayer:
        connection, addr = self.socket.accept()
        print("Got connection from", addr)
        return Multiplayer(connection, addr, first_turn=True)


class Client:
    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def connect_to_host(self, host_ip) -> Multiplayer:
        self.socket.connect((host_ip, PORT))
        return Multiplayer(self.socket, host_ip, first_turn=False)


class ShipType(Enum):
    PatrolBoat = "P"
    Submarine = "S"
    Destroyer = "D"
    Battleship = "B"
    Carrier = "C"

    @staticmethod
    def size_of(ship_type):
        if ship_type == ShipType.PatrolBoat:
            return 2
        elif ship_type == ShipType.Submarine:
            return 3
        elif ship_type == ShipType.Destroyer:
            return 3
        elif ship_type == ShipType.Battleship:
            return 4
        elif ship_type == ShipType.Carrier:
            return 5


class Ship:
    def __init__(
        self,
        ship_type: ShipType,
        start_pos: Tuple[int, int],
        rotation: Direction,
        bounds_y: Tuple[int, int],
        bounds_x: Tuple[int, int],
    ):
        self.ship_type = ship_type
        self.size = ShipType.size_of(self.ship_type)
        self.hits = [False for _ in range(self.size)]
        self.start_pos = start_pos
        self.rotation = rotation
        self.bounds_y = bounds_y
        self.bounds_x = bounds_x
        self.positions: List[Tuple[int, int]] = []
        self.update_positions(self.start_pos)

    @staticmethod
    def generate_positions(
        start_pos: Tuple[int, int], rotation: Direction, ship_size: int
    ) -> List[Tuple[int, int]]:
        positions = []
        for i in range(ship_size):
            y, x = start_pos
            if rotation == Direction.RIGHT:
                x += i
            elif rotation == Direction.LEFT:
                x -= i
            elif rotation == Direction.UP:
                y -= i
            elif rotation == Direction.DOWN:
                y += i
            positions.append((y, x))
        return positions

    def in_bounds(self) -> bool:
        return pos_in_bounds(
            self.positions[0], self.bounds_y, self.bounds_x
        ) and pos_in_bounds(self.positions[-1], self.bounds_y, self.bounds_x)

    def update_positions(self, start_pos: Tuple[int, int]) -> bool:
        old_positions = self.positions
        self.positions = Ship.generate_positions(start_pos, self.rotation, self.size)
        if not self.in_bounds():
            self.positions = old_positions
            return False
        else:
            self.start_pos = start_pos
            return True

    def move(self, direction: Direction):
        if direction == Direction.RIGHT:
            self.update_positions((self.start_pos[0], self.start_pos[1] + 1))
        elif direction == Direction.LEFT:
            self.update_positions((self.start_pos[0], self.start_pos[1] - 1))
        elif direction == Direction.UP:
            self.update_positions((self.start_pos[0] - 1, self.start_pos[1]))
        elif direction == Direction.DOWN:
            self.update_positions((self.start_pos[0] + 1, self.start_pos[1]))

    def rotate(self):
        self.rotation = rotate_clockwise(self.rotation)
        while not self.update_positions(self.start_pos):
            self.rotation = rotate_clockwise(self.rotation)

    def check_hit(self, hit_pos: Tuple[int, int], is_missile: bool) -> Hit:
        for i, pos in enumerate(self.positions):
            if pos == hit_pos:
                self.hits[i] = is_missile
                # Check if ship has been sunk
                if is_missile and all(self.hits):
                    return Hit.sunk(hit_pos, self.ship_type.value, self.positions)
                else:
                    return Hit.hit(hit_pos)
        return Hit.miss(hit_pos)


class Fleet:
    def __init__(self):
        self.ships: List[Ship] = []

    def add_ship(self, ship: Ship):
        self.ships.append(ship)

    def check_hit(self, hit_pos: Tuple[int, int], is_missile: bool = True) -> Hit:
        for ship in self.ships:
            hit_object = ship.check_hit(hit_pos, is_missile)
            if hit_object.hit_type != HitType.MISS:
                return hit_object
        return Hit.miss(hit_pos)


class GameState(Enum):
    SETUP = auto()
    READY = auto()
    PLAYING = auto()
    PLAYER_WON = auto()
    OPPONENT_WON = auto()


class Manager:
    MIN_WINDOW_WIDTH = 85
    MIN_WINDOW_HEIGHT = 30

    def __init__(self):
        ...

    def start(self, stdscr, player):
        self.stdscr = stdscr
        self.player = player
        self.__initialize()
        self.__loop()

    def __initialize(self):
        self.__set_bounds()
        self.__create_board()
        Information.disambiguation(self)
        if isinstance(self.player, LocalPlayer):
            self.player.ai.initialize()
            Information.ai_info(self)

        self.game_state = GameState.SETUP
        self.guesses: List[Tuple[Tuple[int, int], Hit]] = []
        self.fleet = Fleet()
        self.player_ships_left = len(ShipType)
        self.opponent_ships_left = len(ShipType)

    def __set_bounds(self):
        self.scrheight, self.scrwidth = self.stdscr.getmaxyx()
        if (
            self.scrheight < Manager.MIN_WINDOW_HEIGHT
            or self.scrwidth < Manager.MIN_WINDOW_WIDTH
        ):
            self.__await_resize()

        self.window_center = (round(self.scrheight / 2), (round(self.scrwidth / 2)))

        gameboard_width = 40
        half_width = ceil(gameboard_width / 2)
        self.bounds_x = (
            self.window_center[1] - half_width,
            self.window_center[1] + half_width,
        )
        gameboard_height = 20
        half_height = ceil(gameboard_height / 2)
        self.bounds_y = (
            self.window_center[0] - half_height,
            self.window_center[0] + half_height,
        )

        # Players side
        self.player_board_center = (
            self.window_center[0],
            self.window_center[1] - round(gameboard_width / 4),
        )
        self.player_bounds_y = (self.bounds_y[0], self.bounds_y[1])
        self.player_bounds_x = (self.bounds_x[0], self.window_center[1])

        # Opponents side
        self.opponent_board_center = (
            self.window_center[0],
            self.window_center[1] + round(gameboard_width / 4),
        )
        self.opponent_bounds_y = (self.bounds_y[0], self.bounds_y[1])
        self.opponent_bounds_x = (self.window_center[1], self.bounds_x[1])

    def __await_resize(self):
        self.stdscr.clear()
        self.stdscr.addstr(0, 0, "Window is too small. Please resize.")
        while (
            self.scrheight < Manager.MIN_WINDOW_HEIGHT
            or self.scrwidth < Manager.MIN_WINDOW_WIDTH
        ):
            self.scrheight, self.scrwidth = self.stdscr.getmaxyx()
            _ = self.stdscr.getkey()
        self.stdscr.clear()

    def __create_board(self):
        for x in range(self.bounds_x[0], self.bounds_x[1] + 1):
            self.stdscr.addstr(self.bounds_y[0], x, "-")
            self.stdscr.addstr(self.bounds_y[1], x, "-")
        for y in range(self.bounds_y[0] + 1, self.bounds_y[1]):
            self.stdscr.addstr(y, self.bounds_x[0], "|")
            self.stdscr.addstr(y, self.window_center[1], "|")
            self.stdscr.addstr(y, self.bounds_x[1], "|")

    def __loop(self):
        while True:
            Information.status(self)
            if self.game_state == GameState.SETUP:
                self.__place_ships()
            elif self.game_state == GameState.READY:
                self.__ready()
            elif self.game_state == GameState.PLAYING:
                if self.player.players_turn:
                    self.__take_turn()
                else:
                    self.__opponents_turn()
            elif self.game_state in [GameState.PLAYER_WON, GameState.OPPONENT_WON]:
                self.__game_over()

    def __ready(self):
        self.stdscr.refresh()
        self.player.ready()
        Information.shooting(self)
        self.game_state = GameState.PLAYING

    def __take_turn(self):
        target_pos = self.opponent_board_center
        old_pos = target_pos
        while True:
            self.stdscr.addstr(old_pos[0], old_pos[1], " ")
            if not pos_in_bounds(
                target_pos, self.opponent_bounds_y, self.opponent_bounds_x
            ):
                target_pos = old_pos

            # Redraw the old position if it was a previous guess
            previous_guess_result_old_pos = self.__get_previous_guess_result(old_pos)
            if previous_guess_result_old_pos is not None:
                self.stdscr.addstr(
                    old_pos[0], old_pos[1], previous_guess_result_old_pos
                )
            # Draw the target
            previous_guess_result_target_pos = self.__get_previous_guess_result(
                target_pos
            )
            if previous_guess_result_target_pos is None:
                target_char = "#"
            else:
                target_char = "-"

            self.stdscr.addstr(target_pos[0], target_pos[1], target_char)

            old_pos = target_pos
            key = self.stdscr.getch()
            if key == ord(" "):
                # Space pressed
                if previous_guess_result_target_pos is None:
                    self.__fire_missile(target_pos)
                    self.player.players_turn = False
                    break
                else:
                    # Already guessed this position
                    continue
            elif key == curses.KEY_RIGHT:
                target_pos = (target_pos[0], target_pos[1] + 1)
            elif key == curses.KEY_LEFT:
                target_pos = (target_pos[0], target_pos[1] - 1)
            elif key == curses.KEY_UP:
                target_pos = (target_pos[0] - 1, target_pos[1])
            elif key == curses.KEY_DOWN:
                target_pos = (target_pos[0] + 1, target_pos[1])

    def __opponents_turn(self):
        self.stdscr.refresh()
        hit: Hit = self.player.listen_for_move()
        char = "X" if hit.hit_type != HitType.MISS else "O"
        self.stdscr.addstr(hit.target_position[0], hit.target_position[1], char)
        self.player.players_turn = True

        if hit.hit_type == HitType.SUNK:
            self.__check_game_over()

    def __fire_missile(self, target_pos: Tuple[int, int]):
        # Offset the position to the players side
        offset = self.opponent_board_center[1] - target_pos[1]
        offset_target_pos = (target_pos[0], self.player_board_center[1] - offset)
        # Check for hit
        hit: Hit = self.player.send_move(offset_target_pos)
        self.guesses.append((target_pos, hit))

        self.stdscr.addstr(target_pos[0], target_pos[1], hit.character)
        if hit.hit_type == HitType.SUNK:
            # Sunk opponent ship
            self.__reveal_sunk_ship(hit)
            self.opponent_ships_left -= 1
            self.__check_game_over()

    def __get_previous_guess_result(self, target: Tuple[int, int]):
        for (pos, hit) in self.guesses:
            if target == pos:
                return hit.character
        return None

    def __reveal_sunk_ship(self, hit: Hit):
        for hit_pos in hit.ship_positions:
            # Offset the position to the opponents side
            offset = self.player_board_center[1] - hit_pos[1]
            offset_hit_pos = (hit_pos[0], self.opponent_board_center[1] - offset)
            for i, (pos, _) in enumerate(self.guesses):
                if offset_hit_pos == pos:
                    self.guesses[i] = (offset_hit_pos, hit)
                    self.stdscr.addstr(
                        offset_hit_pos[0], offset_hit_pos[1], hit.character
                    )
                    break

    def __check_game_over(self):
        if self.opponent_ships_left == 0:
            self.game_state = GameState.PLAYER_WON
        elif self.player_ships_left == 0:
            self.game_state = GameState.OPPONENT_WON

    def __place_ships(self):
        Information.placing_ships(self)
        for ship_type in ShipType:
            self.__place_ship_loop(ship_type)
        Information.placing_ships(self, clear=True)
        self.game_state = GameState.READY

    def __place_ship_loop(self, ship_type: ShipType):
        ship = Ship(
            ship_type,
            self.player_board_center,
            Direction.RIGHT,
            self.player_bounds_y,
            self.player_bounds_x,
        )
        old_positions = ship.positions
        while True:
            self.__clear_positions(old_positions)
            old_positions = ship.positions

            self.__draw_all_ships()
            overlaps = self.__draw_ship(ship, check_overlap=True)

            key = self.stdscr.getch()
            if key == ord(" "):
                # Space pressed
                if not overlaps:
                    self.fleet.add_ship(ship)
                    return
            elif key == curses.KEY_RIGHT:
                ship.move(Direction.RIGHT)
            elif key == curses.KEY_LEFT:
                ship.move(Direction.LEFT)
            elif key == curses.KEY_UP:
                ship.move(Direction.UP)
            elif key == curses.KEY_DOWN:
                ship.move(Direction.DOWN)
            elif key == ord("r"):
                ship.rotate()

    def __draw_all_ships(self):
        for ship in self.fleet.ships:
            self.__draw_ship(ship)

    def __draw_ship(self, ship: Ship, check_overlap=False) -> bool:
        overlaps = False
        for y, x in ship.positions:
            char = ship.ship_type.value
            if (
                check_overlap
                and self.fleet.check_hit((y, x), False).hit_type != HitType.MISS
            ):
                overlaps = True
                char = "X"
            self.stdscr.addstr(y, x, char)
        return overlaps

    def __clear_positions(self, positions):
        for y, x in positions:
            self.stdscr.addstr(y, x, " ")

    def __game_over(self):
        Information.game_over(self)
        self.stdscr.getch()

class TextAlignment(Enum):
    CENTER = auto()
    LEFT = auto()

    def align(x: int, text: str, alignment):
        if alignment == TextAlignment.CENTER:
            return x - round(len(text) / 2)
        elif alignment == TextAlignment.LEFT:
            return x


class Information:
    @staticmethod
    def __add_text(stdscr, y, x, text, alignment: TextAlignment = TextAlignment.CENTER):
        stdscr.addstr(y, TextAlignment.align(x, text, alignment), text)

    @staticmethod
    def __clear_text(
        stdscr, y, x, text, alignment: TextAlignment = TextAlignment.CENTER
    ):
        stdscr.addstr(y, TextAlignment.align(x, text, alignment), " " * len(text))

    @staticmethod
    def __update_info(
        stdscr, y, x, text, clear, alignment: TextAlignment = TextAlignment.CENTER
    ):
        if not clear:
            Information.__add_text(stdscr, y, x, text, alignment)
        else:
            Information.__clear_text(stdscr, y, x, text, alignment)

    @staticmethod
    def __clear_status(manager: Manager):
        text = " " * (manager.scrwidth - 1)
        Information.__add_text(
            manager.stdscr,
            manager.bounds_y[0] - 2,
            manager.window_center[1],
            text,
        )

    @staticmethod
    def status(manager: Manager):
        if manager.game_state == GameState.SETUP:
            text = "PLACE YOUR SHIPS"
        elif manager.game_state == GameState.READY:
            text = "WAITING FOR OPPONENT"
        elif manager.game_state == GameState.PLAYING:
            if manager.player.players_turn:
                text = "YOUR TURN"
            else:
                text = "OPPONENTS TURN"
        elif manager.game_state == GameState.PLAYER_WON:
            text = "YOU WON!"
        elif manager.game_state == GameState.OPPONENT_WON:
            text = "YOU LOST."

        Information.__clear_status(manager)
        Information.__update_info(
            manager.stdscr,
            manager.bounds_y[0] - 2,
            manager.window_center[1],
            text,
            False,
        )

    @staticmethod
    def placing_ships(manager: Manager, clear=False):
        Information.__update_info(
            manager.stdscr,
            manager.bounds_y[1] + 2,
            manager.window_center[1],
            "Move: Arrow keys",
            clear,
        )
        Information.__update_info(
            manager.stdscr,
            manager.bounds_y[1] + 3,
            manager.window_center[1],
            "Rotate: R key",
            clear,
        )
        Information.__update_info(
            manager.stdscr,
            manager.bounds_y[1] + 4,
            manager.window_center[1],
            "Confirm: Space",
            clear,
        )

    @staticmethod
    def shooting(manager: Manager, clear=False):
        Information.__update_info(
            manager.stdscr,
            manager.bounds_y[1] + 2,
            manager.window_center[1],
            "Move: Arrow keys",
            clear,
        )
        Information.__update_info(
            manager.stdscr,
            manager.bounds_y[1] + 3,
            manager.window_center[1],
            "Fire: Space",
            clear,
        )

    @staticmethod
    def game_over(manager: Manager, clear=False):
        Information.status(manager)

    @staticmethod
    def disambiguation(manager: Manager, clear=False):
        Information.__update_info(
            manager.stdscr,
            manager.window_center[0] - 8,
            manager.bounds_x[1] + 5,
            "Disambiguation",
            clear,
            alignment=TextAlignment.LEFT,
        )
        Information.__update_info(
            manager.stdscr,
            manager.window_center[0] - 6,
            manager.bounds_x[1] + 5,
            "P: Patrol boat (2)",
            clear,
            alignment=TextAlignment.LEFT,
        )
        Information.__update_info(
            manager.stdscr,
            manager.window_center[0] - 5,
            manager.bounds_x[1] + 5,
            "S: Submarine (3)",
            clear,
            alignment=TextAlignment.LEFT,
        )
        Information.__update_info(
            manager.stdscr,
            manager.window_center[0] - 4,
            manager.bounds_x[1] + 5,
            "D: Destroyer (3)",
            clear,
            alignment=TextAlignment.LEFT,
        )
        Information.__update_info(
            manager.stdscr,
            manager.window_center[0] - 3,
            manager.bounds_x[1] + 5,
            "B: Battleship (4)",
            clear,
            alignment=TextAlignment.LEFT,
        )
        Information.__update_info(
            manager.stdscr,
            manager.window_center[0] - 2,
            manager.bounds_x[1] + 5,
            "C: Carrier (5)",
            clear,
            alignment=TextAlignment.LEFT,
        )

    @staticmethod
    def ai_info(manager: Manager, clear=False):
        Information.__update_info(
            manager.stdscr,
            manager.window_center[0] + 2,
            manager.bounds_x[1] + 5,
            "AI: %s" % manager.player.ai_type.value,
            clear,
            alignment=TextAlignment.LEFT,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", action="store_true")
    parser.add_argument("--local", action="store_true")
    parser.add_argument(
        "--ai",
        choices=[
            AIType.CopyCat.value,
            AIType.CopyCatWithRandomMissiles.value,
            AIType.Omniscient.value,
        ],
        default=AIType.CopyCat.value,
    )
    args = parser.parse_args()

    if args.local:
        player = LocalPlayer(AIType(args.ai))
    elif args.host:
        host = Host()
        player = host.wait_for_opponent()
    else:
        client = Client()
        player = client.connect_to_host("127.0.0.1")

    manager = Manager()
    player.set_manager(manager)

    def main(stdscr):
        manager.start(stdscr, player)

    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        ...
