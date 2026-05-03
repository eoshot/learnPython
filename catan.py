"""
Catan - a single-file pygame implementation of Settlers of Catan.

Hot-seat, 3 or 4 players. Standard 19-hex board, random terrain & numbers,
9 ports, dev cards, robber, longest road, largest army.

Controls:
  - Click highlighted spots / buttons.
  - Right-click anywhere to cancel the current build/place action.
  - Number keys 1-5 in trade dialog cycle resources.
  - ESC quits.

Run:  python catan.py            (3 players)
      python catan.py 4          (4 players)
"""

from __future__ import annotations

import math
import random
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pygame

# ============================================================
# CONSTANTS
# ============================================================

SCREEN_W, SCREEN_H = 1400, 860
BOARD_CX, BOARD_CY = 430, 430
HEX_SIZE = 58
PANEL_X = 880
FPS = 60

BG_COLOR = (40, 90, 140)
WATER_COLOR = (60, 120, 180)
PANEL_COLOR = (35, 35, 45)
PANEL_BORDER = (120, 120, 140)
TEXT_COLOR = (240, 240, 240)
DIM_TEXT = (170, 170, 180)
BUTTON_COLOR = (70, 70, 95)
BUTTON_HOVER = (100, 100, 130)
BUTTON_DISABLED = (50, 50, 60)
HIGHLIGHT_COLOR = (255, 255, 100)

RESOURCES = ['wood', 'brick', 'sheep', 'wheat', 'ore']

TERRAIN_RESOURCE = {
    'forest': 'wood', 'hills': 'brick', 'pasture': 'sheep',
    'fields': 'wheat', 'mountains': 'ore', 'desert': None,
}

TERRAIN_COLORS = {
    'forest':    (34, 100, 30),
    'hills':     (170, 90, 50),
    'pasture':   (130, 200, 80),
    'fields':    (240, 200, 70),
    'mountains': (130, 130, 130),
    'desert':    (230, 210, 150),
}

RESOURCE_COLORS = {
    'wood':  (34, 100, 30),
    'brick': (170, 90, 50),
    'sheep': (130, 200, 80),
    'wheat': (240, 200, 70),
    'ore':   (130, 130, 130),
}

TERRAIN_COUNTS = {
    'forest': 4, 'pasture': 4, 'fields': 4,
    'hills': 3, 'mountains': 3, 'desert': 1,
}

NUMBER_TOKENS = [2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]
NUMBER_PIPS = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}

# 19 hex axial coords, 3-4-5-4-3 layout
HEX_COORDS = [
    (0, -2),  (1, -2),  (2, -2),
    (-1, -1), (0, -1),  (1, -1),  (2, -1),
    (-2, 0),  (-1, 0),  (0, 0),   (1, 0),   (2, 0),
    (-2, 1),  (-1, 1),  (0, 1),   (1, 1),
    (-2, 2),  (-1, 2),  (0, 2),
]
HEX_COORD_SET = set(HEX_COORDS)

PLAYER_COLORS = [(220, 40, 40), (40, 70, 200), (240, 240, 245), (240, 140, 30)]
PLAYER_NAMES  = ['Red', 'Blue', 'White', 'Orange']

BUILD_COSTS = {
    'road':       {'wood': 1, 'brick': 1},
    'settlement': {'wood': 1, 'brick': 1, 'wheat': 1, 'sheep': 1},
    'city':       {'ore': 3, 'wheat': 2},
    'dev_card':   {'ore': 1, 'wheat': 1, 'sheep': 1},
}

DEV_CARD_COUNTS = {
    'knight': 14, 'vp': 5, 'road_building': 2, 'year_of_plenty': 2, 'monopoly': 2,
}

DEV_CARD_NAMES = {
    'knight': 'Knight',
    'vp': 'Victory Point',
    'road_building': 'Road Building',
    'year_of_plenty': 'Year of Plenty',
    'monopoly': 'Monopoly',
}

MAX_BUILDINGS = {'settlement': 5, 'city': 4, 'road': 15}
WIN_VP = 10

# Axial neighbor offsets (pointy-top, in clockwise order starting upper-right)
HEX_DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]

# Port placement - 9 ports around the coast.
# Each entry = (hex coord, direction index for the edge facing the sea, kind)
# kind in {'3:1', 'wood', 'brick', 'sheep', 'wheat', 'ore'}
# Edges of an outer hex on directions whose neighbor is outside HEX_COORD_SET
# are coast edges; we hand-pick a balanced spread.
PORT_PLACEMENTS = [
    ((0, -2),  2, '3:1'),
    ((2, -2),  1, 'wheat'),
    ((2, -1),  0, 'ore'),
    ((2, 0),   0, '3:1'),
    ((1, 1),   5, 'sheep'),
    ((-1, 2),  5, '3:1'),
    ((-2, 2),  4, 'brick'),
    ((-2, 1),  3, 'wood'),
    ((-2, 0),  3, '3:1'),
]


# ============================================================
# HEX GEOMETRY
# ============================================================

SQRT3 = math.sqrt(3)

def hex_to_pixel(q: int, r: int) -> tuple[float, float]:
    x = HEX_SIZE * (SQRT3 * q + SQRT3 / 2 * r)
    y = HEX_SIZE * (3 / 2 * r)
    return BOARD_CX + x, BOARD_CY + y


def hex_corners(cx: float, cy: float) -> list[tuple[float, float]]:
    """Return the 6 corner points of a pointy-top hex centered at (cx, cy).

    Corner index 0 is the top vertex; goes clockwise.
    """
    pts = []
    for i in range(6):
        angle = math.radians(60 * i - 90)
        pts.append((cx + HEX_SIZE * math.cos(angle),
                    cy + HEX_SIZE * math.sin(angle)))
    return pts


def vkey(x: float, y: float) -> tuple[int, int]:
    """Canonical key for a vertex pixel position (rounded to 2px)."""
    return (round(x / 2) * 2, round(y / 2) * 2)


def ekey(v1: tuple[int, int], v2: tuple[int, int]) -> frozenset:
    return frozenset({v1, v2})


def hex_neighbor(coord: tuple[int, int], d: int) -> tuple[int, int]:
    return (coord[0] + HEX_DIRS[d][0], coord[1] + HEX_DIRS[d][1])


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class Hex:
    coord: tuple[int, int]
    terrain: str
    number: Optional[int]
    cx: float
    cy: float
    corners: list[tuple[float, float]]   # 6 pixel positions
    vkeys: list[tuple[int, int]]         # 6 vertex keys


@dataclass
class Vertex:
    key: tuple[int, int]
    pos: tuple[float, float]
    adjacent_hexes: set = field(default_factory=set)
    neighbors: set = field(default_factory=set)   # vkeys connected by an edge
    building: Optional[str] = None                # None, 'settlement', 'city'
    owner: Optional[int] = None                   # player index
    port: Optional[str] = None                    # port kind if any


@dataclass
class Edge:
    key: frozenset
    v1: tuple[int, int]
    v2: tuple[int, int]
    pos: tuple[float, float]
    adjacent_hexes: set = field(default_factory=set)
    road_owner: Optional[int] = None


# ============================================================
# BOARD
# ============================================================

class Board:
    def __init__(self):
        self.hexes: dict[tuple[int, int], Hex] = {}
        self.vertices: dict[tuple[int, int], Vertex] = {}
        self.edges: dict[frozenset, Edge] = {}
        self.robber: tuple[int, int] = (0, 0)
        self._build()

    def _build(self):
        # Randomize terrain and numbers
        terrain_pool = []
        for t, n in TERRAIN_COUNTS.items():
            terrain_pool += [t] * n
        random.shuffle(terrain_pool)

        tokens = NUMBER_TOKENS.copy()
        random.shuffle(tokens)

        for coord in HEX_COORDS:
            terrain = terrain_pool.pop()
            number = None if terrain == 'desert' else tokens.pop()
            cx, cy = hex_to_pixel(*coord)
            corners = hex_corners(cx, cy)
            vkeys = [vkey(*c) for c in corners]

            self.hexes[coord] = Hex(coord, terrain, number, cx, cy, corners, vkeys)

            if terrain == 'desert':
                self.robber = coord

            # vertices
            for vk, pos in zip(vkeys, corners):
                if vk not in self.vertices:
                    self.vertices[vk] = Vertex(vk, pos)
                self.vertices[vk].adjacent_hexes.add(coord)

            # edges: between consecutive corners
            for i in range(6):
                v1, v2 = vkeys[i], vkeys[(i + 1) % 6]
                k = ekey(v1, v2)
                if k not in self.edges:
                    midx = (corners[i][0] + corners[(i + 1) % 6][0]) / 2
                    midy = (corners[i][1] + corners[(i + 1) % 6][1]) / 2
                    self.edges[k] = Edge(k, v1, v2, (midx, midy))
                self.edges[k].adjacent_hexes.add(coord)

        # vertex adjacency (via edges)
        for k, e in self.edges.items():
            self.vertices[e.v1].neighbors.add(e.v2)
            self.vertices[e.v2].neighbors.add(e.v1)

        self._add_ports()

    def _add_ports(self):
        for coord, dir_idx, kind in PORT_PLACEMENTS:
            h = self.hexes[coord]
            v1k = h.vkeys[dir_idx]
            v2k = h.vkeys[(dir_idx + 1) % 6]
            self.vertices[v1k].port = kind
            self.vertices[v2k].port = kind

    # ---- queries ----

    def vertices_of_hex(self, coord) -> list[tuple[int, int]]:
        return self.hexes[coord].vkeys

    def players_on_hex(self, coord) -> set[int]:
        out = set()
        for vk in self.vertices_of_hex(coord):
            v = self.vertices[vk]
            if v.owner is not None:
                out.add(v.owner)
        return out


# ============================================================
# PLAYER
# ============================================================

class Player:
    def __init__(self, idx: int, name: str, color: tuple[int, int, int]):
        self.idx = idx
        self.name = name
        self.color = color
        self.resources: dict[str, int] = {r: 0 for r in RESOURCES}
        self.dev_cards: dict[str, int] = {c: 0 for c in DEV_CARD_COUNTS}
        self.dev_cards_new: dict[str, int] = {c: 0 for c in DEV_CARD_COUNTS}
        self.played_knights = 0
        self.has_largest_army = False
        self.has_longest_road = False
        self.longest_road_length = 0
        self.settlements: set = set()
        self.cities: set = set()
        self.roads: set = set()
        self.played_dev_this_turn = False

    def total_resources(self) -> int:
        return sum(self.resources.values())

    def total_dev_cards(self) -> int:
        return sum(self.dev_cards.values()) + sum(self.dev_cards_new.values())

    def can_afford(self, cost: dict[str, int]) -> bool:
        return all(self.resources[r] >= n for r, n in cost.items())

    def pay(self, cost: dict[str, int]):
        for r, n in cost.items():
            self.resources[r] -= n

    def gain(self, res: str, amount: int = 1):
        self.resources[res] += amount

    def victory_points(self) -> int:
        vp = len(self.settlements) + 2 * len(self.cities)
        vp += self.dev_cards['vp'] + self.dev_cards_new['vp']
        if self.has_largest_army:
            vp += 2
        if self.has_longest_road:
            vp += 2
        return vp

    def public_victory_points(self) -> int:
        vp = len(self.settlements) + 2 * len(self.cities)
        if self.has_largest_army:
            vp += 2
        if self.has_longest_road:
            vp += 2
        return vp


# ============================================================
# GAME STATE
# ============================================================

class Phase(Enum):
    SETUP_PLACE_SETTLEMENT = 1
    SETUP_PLACE_ROAD = 2
    ROLL = 3
    MAIN = 4
    DISCARD = 5
    MOVE_ROBBER = 6
    STEAL = 7
    PLACE_ROAD = 8           # while building/placing a road
    PLACE_SETTLEMENT = 9
    PLACE_CITY = 10
    ROAD_BUILDING = 11       # dev card free roads (track count_left)
    YEAR_OF_PLENTY = 12
    MONOPOLY = 13
    GAME_OVER = 14


class Game:
    def __init__(self, num_players: int = 3):
        assert 3 <= num_players <= 4
        self.board = Board()
        self.players = [Player(i, PLAYER_NAMES[i], PLAYER_COLORS[i])
                        for i in range(num_players)]
        self.current = 0
        self.phase = Phase.SETUP_PLACE_SETTLEMENT
        self.dev_deck = self._make_dev_deck()
        self.dice = (0, 0)
        self.has_rolled = False

        # setup tracking
        self.setup_round = 1   # 1 -> forward, 2 -> reverse, then play
        self.setup_last_settlement: Optional[tuple[int, int]] = None

        # robber / discard
        self.discard_needed: dict[int, int] = {}
        self.steal_targets: list[int] = []

        # dev card sub-states
        self.road_building_left = 0
        self.yop_picks_left = 0

        # bookkeeping
        self.largest_army_holder: Optional[int] = None
        self.longest_road_holder: Optional[int] = None
        self.message = "Setup: Red, place your first settlement."
        self.winner: Optional[int] = None
        self.log: list[str] = []

    def _make_dev_deck(self):
        deck = []
        for c, n in DEV_CARD_COUNTS.items():
            deck += [c] * n
        random.shuffle(deck)
        return deck

    def cur(self) -> Player:
        return self.players[self.current]

    def add_log(self, msg: str):
        self.log.append(msg)
        if len(self.log) > 9:
            self.log.pop(0)

    # ------------------------------------------------------------
    # VALIDITY CHECKS
    # ------------------------------------------------------------

    def can_place_settlement_here(self, vk, player_idx, setup=False) -> bool:
        v = self.board.vertices.get(vk)
        if v is None or v.building is not None:
            return False
        # distance rule
        for nb in v.neighbors:
            if self.board.vertices[nb].building is not None:
                return False
        if setup:
            return True
        # must connect to one of player's roads
        for nb in v.neighbors:
            e = self.board.edges[ekey(vk, nb)]
            if e.road_owner == player_idx:
                return True
        return False

    def can_place_road_here(self, ek, player_idx, setup_after_vertex=None) -> bool:
        e = self.board.edges.get(ek)
        if e is None or e.road_owner is not None:
            return False
        if setup_after_vertex is not None:
            return setup_after_vertex in (e.v1, e.v2)
        # connect to own road or own settlement/city,
        # but not "through" an opponent's settlement/city
        for v in (e.v1, e.v2):
            vert = self.board.vertices[v]
            if vert.owner == player_idx:
                return True
            if vert.owner is None:
                # connected via another road owned by player
                for nb in vert.neighbors:
                    if nb == (e.v1 if v == e.v2 else e.v2):
                        continue
                    other_e = self.board.edges[ekey(v, nb)]
                    if other_e.road_owner == player_idx:
                        return True
        return False

    def can_upgrade_to_city(self, vk, player_idx) -> bool:
        v = self.board.vertices.get(vk)
        return v is not None and v.building == 'settlement' and v.owner == player_idx

    def valid_settlement_spots(self, player_idx, setup=False) -> list:
        return [vk for vk in self.board.vertices
                if self.can_place_settlement_here(vk, player_idx, setup)]

    def valid_road_spots(self, player_idx, setup_after_vertex=None) -> list:
        return [ek for ek in self.board.edges
                if self.can_place_road_here(ek, player_idx, setup_after_vertex)]

    def valid_city_spots(self, player_idx) -> list:
        return [vk for vk in self.board.vertices
                if self.can_upgrade_to_city(vk, player_idx)]

    # ------------------------------------------------------------
    # SETUP PHASE
    # ------------------------------------------------------------

    def setup_place_settlement(self, vk):
        if not self.can_place_settlement_here(vk, self.current, setup=True):
            return
        v = self.board.vertices[vk]
        v.building = 'settlement'
        v.owner = self.current
        self.cur().settlements.add(vk)
        self.setup_last_settlement = vk
        # In the second round, gain resources from adjacent hexes
        if self.setup_round == 2:
            for hc in v.adjacent_hexes:
                h = self.board.hexes[hc]
                if h.terrain != 'desert':
                    self.cur().gain(TERRAIN_RESOURCE[h.terrain])
        self.phase = Phase.SETUP_PLACE_ROAD
        self.message = f"{self.cur().name}: place a road touching that settlement."

    def setup_place_road(self, ek):
        if not self.can_place_road_here(ek, self.current,
                                        setup_after_vertex=self.setup_last_settlement):
            return
        self.board.edges[ek].road_owner = self.current
        self.cur().roads.add(ek)
        self.cur().longest_road_length = self._longest_road_for(self.current)
        self.setup_last_settlement = None

        # Advance setup turn order
        n = len(self.players)
        if self.setup_round == 1:
            if self.current == n - 1:
                self.setup_round = 2  # stay on same player, reverse
            else:
                self.current += 1
            self.phase = Phase.SETUP_PLACE_SETTLEMENT
            self.message = f"Setup: {self.cur().name}, place your settlement."
        else:
            if self.current == 0:
                # done with setup
                self.current = 0
                self.phase = Phase.ROLL
                self.has_rolled = False
                self.message = f"{self.cur().name}: roll the dice."
            else:
                self.current -= 1
                self.phase = Phase.SETUP_PLACE_SETTLEMENT
                self.message = f"Setup (round 2): {self.cur().name}, place your settlement."

    # ------------------------------------------------------------
    # DICE + RESOURCES
    # ------------------------------------------------------------

    def roll_dice(self):
        if self.phase != Phase.ROLL:
            return
        d1 = random.randint(1, 6)
        d2 = random.randint(1, 6)
        self.dice = (d1, d2)
        total = d1 + d2
        self.has_rolled = True
        self.add_log(f"{self.cur().name} rolled {d1}+{d2} = {total}")
        if total == 7:
            self._handle_seven()
        else:
            self._distribute(total)
            self.phase = Phase.MAIN
            self.message = f"{self.cur().name}: build, trade, or end turn."

    def _distribute(self, total: int):
        gained_by = defaultdict(lambda: defaultdict(int))
        for coord, h in self.board.hexes.items():
            if h.number != total:
                continue
            if coord == self.board.robber:
                continue
            res = TERRAIN_RESOURCE[h.terrain]
            if res is None:
                continue
            for vk in h.vkeys:
                v = self.board.vertices[vk]
                if v.building == 'settlement':
                    gained_by[v.owner][res] += 1
                elif v.building == 'city':
                    gained_by[v.owner][res] += 2
        for pidx, gains in gained_by.items():
            for res, n in gains.items():
                self.players[pidx].gain(res, n)
        if gained_by:
            parts = []
            for pidx, gains in gained_by.items():
                gs = ", ".join(f"+{n} {r}" for r, n in gains.items())
                parts.append(f"{self.players[pidx].name}: {gs}")
            self.add_log("  " + " | ".join(parts))

    def _handle_seven(self):
        self.discard_needed = {}
        for p in self.players:
            if p.total_resources() > 7:
                self.discard_needed[p.idx] = p.total_resources() // 2
        if self.discard_needed:
            self.phase = Phase.DISCARD
            first = next(iter(self.discard_needed))
            self.message = (f"{self.players[first].name} must discard "
                            f"{self.discard_needed[first]} cards.")
        else:
            self.phase = Phase.MOVE_ROBBER
            self.message = f"{self.cur().name}: move the robber."

    def discard_card(self, player_idx: int, resource: str):
        if self.phase != Phase.DISCARD:
            return
        if player_idx not in self.discard_needed:
            return
        p = self.players[player_idx]
        if p.resources[resource] <= 0:
            return
        p.resources[resource] -= 1
        self.discard_needed[player_idx] -= 1
        if self.discard_needed[player_idx] <= 0:
            del self.discard_needed[player_idx]
        if not self.discard_needed:
            self.phase = Phase.MOVE_ROBBER
            self.message = f"{self.cur().name}: move the robber."
        else:
            nxt = next(iter(self.discard_needed))
            self.message = (f"{self.players[nxt].name} must discard "
                            f"{self.discard_needed[nxt]} cards.")

    def move_robber(self, coord):
        if coord == self.board.robber:
            return
        if coord not in self.board.hexes:
            return
        self.board.robber = coord
        # find players to steal from
        targets = set()
        for vk in self.board.vertices_of_hex(coord):
            v = self.board.vertices[vk]
            if v.owner is not None and v.owner != self.current:
                if self.players[v.owner].total_resources() > 0:
                    targets.add(v.owner)
        self.steal_targets = sorted(targets)
        if not self.steal_targets:
            self._post_robber()
        else:
            self.phase = Phase.STEAL
            self.message = (f"{self.cur().name}: choose a player to steal from "
                            f"({', '.join(self.players[i].name for i in self.steal_targets)}).")

    def steal_from(self, target_idx: int):
        if self.phase != Phase.STEAL:
            return
        if target_idx not in self.steal_targets:
            return
        target = self.players[target_idx]
        pool = []
        for r, n in target.resources.items():
            pool += [r] * n
        if pool:
            r = random.choice(pool)
            target.resources[r] -= 1
            self.cur().gain(r)
            self.add_log(f"{self.cur().name} stole 1 {r} from {target.name}.")
        self._post_robber()

    def _post_robber(self):
        # If robber was triggered before rolling (knight), allow rolling next.
        if not self.has_rolled:
            self.phase = Phase.ROLL
            self.message = f"{self.cur().name}: roll the dice."
        else:
            self.phase = Phase.MAIN
            self.message = f"{self.cur().name}: build, trade, or end turn."

    # ------------------------------------------------------------
    # BUILDING
    # ------------------------------------------------------------

    def start_build_road(self):
        p = self.cur()
        if len(p.roads) >= MAX_BUILDINGS['road']:
            return
        if not p.can_afford(BUILD_COSTS['road']):
            return
        if not self.valid_road_spots(p.idx):
            return
        self.phase = Phase.PLACE_ROAD
        self.message = f"{p.name}: click an edge to place a road. (Right-click to cancel)"

    def place_road(self, ek):
        p = self.cur()
        if not self.can_place_road_here(ek, p.idx):
            return
        if not p.can_afford(BUILD_COSTS['road']):
            return
        p.pay(BUILD_COSTS['road'])
        self.board.edges[ek].road_owner = p.idx
        p.roads.add(ek)
        self._recompute_longest_road()
        self.phase = Phase.MAIN
        self.message = f"{p.name}: build, trade, or end turn."
        self._check_win()

    def start_build_settlement(self):
        p = self.cur()
        if len(p.settlements) >= MAX_BUILDINGS['settlement']:
            return
        if not p.can_afford(BUILD_COSTS['settlement']):
            return
        if not self.valid_settlement_spots(p.idx):
            return
        self.phase = Phase.PLACE_SETTLEMENT
        self.message = f"{p.name}: click a vertex to place a settlement. (Right-click to cancel)"

    def place_settlement(self, vk):
        p = self.cur()
        if not self.can_place_settlement_here(vk, p.idx):
            return
        if not p.can_afford(BUILD_COSTS['settlement']):
            return
        p.pay(BUILD_COSTS['settlement'])
        v = self.board.vertices[vk]
        v.building = 'settlement'
        v.owner = p.idx
        p.settlements.add(vk)
        self._recompute_longest_road()  # opponent road may be cut
        self.phase = Phase.MAIN
        self.message = f"{p.name}: build, trade, or end turn."
        self._check_win()

    def start_build_city(self):
        p = self.cur()
        if len(p.cities) >= MAX_BUILDINGS['city']:
            return
        if not p.can_afford(BUILD_COSTS['city']):
            return
        if not self.valid_city_spots(p.idx):
            return
        self.phase = Phase.PLACE_CITY
        self.message = f"{p.name}: click one of your settlements to upgrade. (Right-click to cancel)"

    def place_city(self, vk):
        p = self.cur()
        if not self.can_upgrade_to_city(vk, p.idx):
            return
        if not p.can_afford(BUILD_COSTS['city']):
            return
        p.pay(BUILD_COSTS['city'])
        v = self.board.vertices[vk]
        v.building = 'city'
        p.settlements.discard(vk)
        p.cities.add(vk)
        self.phase = Phase.MAIN
        self.message = f"{p.name}: build, trade, or end turn."
        self._check_win()

    def buy_dev_card(self):
        if self.phase != Phase.MAIN:
            return
        p = self.cur()
        if not self.dev_deck:
            return
        if not p.can_afford(BUILD_COSTS['dev_card']):
            return
        p.pay(BUILD_COSTS['dev_card'])
        c = self.dev_deck.pop()
        p.dev_cards_new[c] += 1
        self.add_log(f"{p.name} bought a dev card.")
        self._check_win()

    # ------------------------------------------------------------
    # DEV CARDS
    # ------------------------------------------------------------

    def play_dev_card(self, kind: str):
        p = self.cur()
        if p.played_dev_this_turn and kind != 'vp':
            return
        if p.dev_cards.get(kind, 0) <= 0:
            return
        if kind == 'knight':
            p.dev_cards['knight'] -= 1
            p.played_knights += 1
            p.played_dev_this_turn = True
            self.add_log(f"{p.name} played a Knight.")
            self._update_largest_army()
            self.phase = Phase.MOVE_ROBBER
            self.message = f"{p.name}: move the robber."
        elif kind == 'road_building':
            p.dev_cards['road_building'] -= 1
            p.played_dev_this_turn = True
            self.road_building_left = 2
            self.phase = Phase.ROAD_BUILDING
            self.message = f"{p.name}: place 2 free roads."
            self.add_log(f"{p.name} played Road Building.")
        elif kind == 'year_of_plenty':
            p.dev_cards['year_of_plenty'] -= 1
            p.played_dev_this_turn = True
            self.yop_picks_left = 2
            self.phase = Phase.YEAR_OF_PLENTY
            self.message = f"{p.name}: pick 2 resources from the bank."
            self.add_log(f"{p.name} played Year of Plenty.")
        elif kind == 'monopoly':
            p.dev_cards['monopoly'] -= 1
            p.played_dev_this_turn = True
            self.phase = Phase.MONOPOLY
            self.message = f"{p.name}: choose a resource to monopolize."
            self.add_log(f"{p.name} played Monopoly.")
        self._check_win()

    def road_building_place(self, ek):
        p = self.cur()
        if not self.can_place_road_here(ek, p.idx):
            return
        if len(p.roads) >= MAX_BUILDINGS['road']:
            return
        self.board.edges[ek].road_owner = p.idx
        p.roads.add(ek)
        self.road_building_left -= 1
        self._recompute_longest_road()
        if self.road_building_left <= 0 or len(p.roads) >= MAX_BUILDINGS['road']:
            self.phase = Phase.MAIN
            self.message = f"{p.name}: build, trade, or end turn."
        else:
            self.message = f"{p.name}: place {self.road_building_left} more free road."
        self._check_win()

    def year_of_plenty_pick(self, resource: str):
        p = self.cur()
        p.gain(resource)
        self.yop_picks_left -= 1
        if self.yop_picks_left <= 0:
            self.phase = Phase.MAIN
            self.message = f"{p.name}: build, trade, or end turn."
        else:
            self.message = f"{p.name}: pick {self.yop_picks_left} more resource."

    def monopoly_pick(self, resource: str):
        p = self.cur()
        total = 0
        for other in self.players:
            if other.idx == p.idx:
                continue
            n = other.resources[resource]
            other.resources[resource] = 0
            p.gain(resource, n)
            total += n
        self.add_log(f"{p.name} monopolized {resource} (+{total}).")
        self.phase = Phase.MAIN
        self.message = f"{p.name}: build, trade, or end turn."

    # ------------------------------------------------------------
    # TRADING (with bank/ports)
    # ------------------------------------------------------------

    def best_ratio(self, player: Player, resource: str) -> int:
        """Best trade ratio the player has access to for selling 'resource'."""
        ratio = 4
        # check ports at any of player's settlement/city vertices
        owned_vs = list(player.settlements) + list(player.cities)
        for vk in owned_vs:
            port = self.board.vertices[vk].port
            if port == '3:1':
                ratio = min(ratio, 3)
            elif port == resource:
                ratio = min(ratio, 2)
        return ratio

    def bank_trade(self, give: str, receive: str):
        if self.phase != Phase.MAIN:
            return
        if give == receive:
            return
        p = self.cur()
        ratio = self.best_ratio(p, give)
        if p.resources[give] < ratio:
            return
        p.resources[give] -= ratio
        p.gain(receive)
        self.add_log(f"{p.name} traded {ratio} {give} -> 1 {receive} (bank).")

    # ------------------------------------------------------------
    # END TURN
    # ------------------------------------------------------------

    def end_turn(self):
        if self.phase != Phase.MAIN:
            return
        if not self.has_rolled:
            return
        p = self.cur()
        # newly bought dev cards become playable next turn
        for c, n in p.dev_cards_new.items():
            p.dev_cards[c] += n
            p.dev_cards_new[c] = 0
        p.played_dev_this_turn = False
        self.current = (self.current + 1) % len(self.players)
        self.has_rolled = False
        self.phase = Phase.ROLL
        self.message = f"{self.cur().name}: roll the dice."

    # ------------------------------------------------------------
    # ARMY + ROAD
    # ------------------------------------------------------------

    def _update_largest_army(self):
        best = 2
        holder = self.largest_army_holder
        if holder is not None:
            best = max(best, self.players[holder].played_knights)
        new_holder = holder
        for p in self.players:
            if p.played_knights >= 3 and p.played_knights > best:
                best = p.played_knights
                new_holder = p.idx
        if new_holder != holder:
            if holder is not None:
                self.players[holder].has_largest_army = False
            self.players[new_holder].has_largest_army = True
            self.largest_army_holder = new_holder
            self.add_log(f"{self.players[new_holder].name} now holds Largest Army.")

    def _recompute_longest_road(self):
        for p in self.players:
            p.longest_road_length = self._longest_road_for(p.idx)
        # Determine holder. Must be >= 5; ties: keep current holder, else nobody new.
        holder = self.longest_road_holder
        best = 0
        if holder is not None:
            best = self.players[holder].longest_road_length
        new_holder = holder
        new_best = best
        for p in self.players:
            if p.longest_road_length >= 5 and p.longest_road_length > new_best:
                new_best = p.longest_road_length
                new_holder = p.idx
        # check if current holder still qualifies
        if holder is not None and self.players[holder].longest_road_length < 5:
            self.players[holder].has_longest_road = False
            holder = None
            new_holder = None
            new_best = 0
            for p in self.players:
                if p.longest_road_length >= 5 and p.longest_road_length > new_best:
                    new_best = p.longest_road_length
                    new_holder = p.idx
        if new_holder != holder:
            if holder is not None:
                self.players[holder].has_longest_road = False
            if new_holder is not None:
                self.players[new_holder].has_longest_road = True
                self.add_log(f"{self.players[new_holder].name} now holds Longest Road ({new_best}).")
            self.longest_road_holder = new_holder

    def _longest_road_for(self, pidx: int) -> int:
        # Build adjacency: vertex -> list of (neighbor_vertex, edge_key) for player's roads.
        edges = [self.board.edges[ek] for ek in self.players[pidx].roads]
        if not edges:
            return 0
        adj: dict = defaultdict(list)
        for e in edges:
            # Roads can be traversed unless an opponent's settlement/city is on the
            # vertex we're passing through. (Endpoints of the road may belong to
            # opponent — but we still can't continue past them.)
            adj[e.v1].append((e.v2, e.key))
            adj[e.v2].append((e.v1, e.key))
        best = 0

        def dfs(node, prev_vertex, used_edges):
            nonlocal best
            if len(used_edges) > best:
                best = len(used_edges)
            v = self.board.vertices[node]
            # If this is not the starting vertex and an opponent owns it, can't continue.
            if prev_vertex is not None and v.owner is not None and v.owner != pidx:
                return
            for nb, ek in adj[node]:
                if ek in used_edges:
                    continue
                used_edges.add(ek)
                dfs(nb, node, used_edges)
                used_edges.remove(ek)

        # Start DFS from every vertex that has at least one of player's roads.
        for v in list(adj.keys()):
            dfs(v, None, set())
        return best

    # ------------------------------------------------------------
    # WIN
    # ------------------------------------------------------------

    def _check_win(self):
        for p in self.players:
            if p.victory_points() >= WIN_VP:
                self.winner = p.idx
                self.phase = Phase.GAME_OVER
                self.message = f"{p.name} wins with {p.victory_points()} VP!"
                return


# ============================================================
# UI
# ============================================================

class UI:
    def __init__(self, game: Game):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Catan")
        self.clock = pygame.time.Clock()
        self.font_sm = pygame.font.SysFont('arial', 14)
        self.font = pygame.font.SysFont('arial', 17)
        self.font_md = pygame.font.SysFont('arial', 20, bold=True)
        self.font_lg = pygame.font.SysFont('arial', 28, bold=True)
        self.game = game
        self.buttons: list[Button] = []
        self.trade_open = False
        self.trade_give: Optional[str] = None
        self.trade_receive: Optional[str] = None
        self._build_buttons()

    # ---------- buttons ----------
    def _build_buttons(self):
        x = PANEL_X + 14
        y = 410
        w = 235
        h = 32
        self.buttons = []
        def add(label, action, key=None):
            nonlocal y
            self.buttons.append(Button(x, y, w, h, label, action, key))
            y += h + 6
        add("Roll Dice", "roll")
        add("Build Road (1w 1b)", "build_road")
        add("Build Settlement (1w 1b 1sh 1wh)", "build_settlement")
        add("Build City (3o 2wh)", "build_city")
        add("Buy Dev Card (1o 1wh 1sh)", "buy_dev")
        add("Bank/Port Trade", "open_trade")
        add("End Turn", "end_turn")

    # ---------- main loop ----------
    def run(self):
        running = True
        while running:
            mouse = pygame.mouse.get_pos()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        if self.trade_open:
                            self.trade_open = False
                        elif self.game.phase in (Phase.PLACE_ROAD, Phase.PLACE_SETTLEMENT,
                                                 Phase.PLACE_CITY):
                            self.game.phase = Phase.MAIN
                            self.game.message = f"{self.game.cur().name}: build, trade, or end turn."
                        else:
                            running = False
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        self.handle_click(ev.pos)
                    elif ev.button == 3:
                        self.handle_right_click(ev.pos)
            self.draw(mouse)
            pygame.display.flip()
            self.clock.tick(FPS)
        pygame.quit()

    # ---------- input ----------
    def handle_right_click(self, pos):
        # cancel current build action
        g = self.game
        if g.phase in (Phase.PLACE_ROAD, Phase.PLACE_SETTLEMENT, Phase.PLACE_CITY):
            g.phase = Phase.MAIN
            g.message = f"{g.cur().name}: build, trade, or end turn."
        elif self.trade_open:
            self.trade_open = False

    def handle_click(self, pos):
        g = self.game
        if g.phase == Phase.GAME_OVER:
            return

        # Trade dialog has top priority when open
        if self.trade_open:
            self._handle_trade_click(pos)
            return

        # Discard dialog: click resource icons in a player's hand to discard
        if g.phase == Phase.DISCARD:
            self._handle_discard_click(pos)
            return

        # Steal: click a player's panel
        if g.phase == Phase.STEAL:
            self._handle_steal_click(pos)
            return

        # Move robber: click a hex
        if g.phase == Phase.MOVE_ROBBER:
            hc = self._hex_at_pixel(pos)
            if hc is not None:
                g.move_robber(hc)
            return

        # Year of plenty / monopoly: pick resource via buttons in panel
        if g.phase == Phase.YEAR_OF_PLENTY:
            picked = self._pick_resource_at(pos)
            if picked:
                g.year_of_plenty_pick(picked)
            return
        if g.phase == Phase.MONOPOLY:
            picked = self._pick_resource_at(pos)
            if picked:
                g.monopoly_pick(picked)
            return

        # Place actions
        if g.phase in (Phase.SETUP_PLACE_SETTLEMENT, Phase.PLACE_SETTLEMENT):
            vk = self._vertex_at_pixel(pos)
            if vk is not None:
                if g.phase == Phase.SETUP_PLACE_SETTLEMENT:
                    g.setup_place_settlement(vk)
                else:
                    g.place_settlement(vk)
            return
        if g.phase in (Phase.SETUP_PLACE_ROAD, Phase.PLACE_ROAD, Phase.ROAD_BUILDING):
            ek = self._edge_at_pixel(pos)
            if ek is not None:
                if g.phase == Phase.SETUP_PLACE_ROAD:
                    g.setup_place_road(ek)
                elif g.phase == Phase.ROAD_BUILDING:
                    g.road_building_place(ek)
                else:
                    g.place_road(ek)
            return
        if g.phase == Phase.PLACE_CITY:
            vk = self._vertex_at_pixel(pos)
            if vk is not None:
                g.place_city(vk)
            return

        # Dev card buttons in panel (when in MAIN)
        if g.phase == Phase.MAIN:
            dev_clicked = self._dev_card_at(pos)
            if dev_clicked:
                g.play_dev_card(dev_clicked)
                return

        # Action buttons on the right panel
        for b in self.buttons:
            if b.rect.collidepoint(pos) and self._button_enabled(b):
                self._do_action(b.action)
                return

    def _do_action(self, action: str):
        g = self.game
        if action == "roll":
            g.roll_dice()
        elif action == "build_road":
            g.start_build_road()
        elif action == "build_settlement":
            g.start_build_settlement()
        elif action == "build_city":
            g.start_build_city()
        elif action == "buy_dev":
            g.buy_dev_card()
        elif action == "open_trade":
            if g.phase == Phase.MAIN:
                self.trade_open = True
                self.trade_give = None
                self.trade_receive = None
        elif action == "end_turn":
            g.end_turn()

    def _button_enabled(self, b) -> bool:
        g = self.game
        p = g.cur()
        if g.phase == Phase.GAME_OVER:
            return False
        if b.action == "roll":
            return g.phase == Phase.ROLL
        if g.phase != Phase.MAIN:
            return False
        if b.action == "build_road":
            return (p.can_afford(BUILD_COSTS['road'])
                    and len(p.roads) < MAX_BUILDINGS['road']
                    and bool(g.valid_road_spots(p.idx)))
        if b.action == "build_settlement":
            return (p.can_afford(BUILD_COSTS['settlement'])
                    and len(p.settlements) < MAX_BUILDINGS['settlement']
                    and bool(g.valid_settlement_spots(p.idx)))
        if b.action == "build_city":
            return (p.can_afford(BUILD_COSTS['city'])
                    and len(p.cities) < MAX_BUILDINGS['city']
                    and bool(g.valid_city_spots(p.idx)))
        if b.action == "buy_dev":
            return p.can_afford(BUILD_COSTS['dev_card']) and bool(g.dev_deck)
        if b.action == "open_trade":
            return True
        if b.action == "end_turn":
            return g.has_rolled
        return True

    # ---------- pixel -> game element ----------
    def _hex_at_pixel(self, pos):
        for c, h in self.game.board.hexes.items():
            dx = pos[0] - h.cx
            dy = pos[1] - h.cy
            if dx * dx + dy * dy < (HEX_SIZE * 0.85) ** 2:
                return c
        return None

    def _vertex_at_pixel(self, pos):
        best = None
        best_d = 14 ** 2
        for vk, v in self.game.board.vertices.items():
            dx = pos[0] - v.pos[0]
            dy = pos[1] - v.pos[1]
            d = dx * dx + dy * dy
            if d < best_d:
                best_d = d
                best = vk
        return best

    def _edge_at_pixel(self, pos):
        best = None
        best_d = 14 ** 2
        for ek, e in self.game.board.edges.items():
            dx = pos[0] - e.pos[0]
            dy = pos[1] - e.pos[1]
            d = dx * dx + dy * dy
            if d < best_d:
                best_d = d
                best = ek
        return best

    # ---------- discard handling ----------
    def _handle_discard_click(self, pos):
        g = self.game
        if not g.discard_needed:
            return
        pidx = next(iter(g.discard_needed))
        # icons drawn at bottom of screen
        rects = self._discard_icon_rects()
        for r, res in rects:
            if r.collidepoint(pos):
                g.discard_card(pidx, res)
                return

    def _discard_icon_rects(self):
        g = self.game
        if not g.discard_needed:
            return []
        pidx = next(iter(g.discard_needed))
        p = g.players[pidx]
        rects = []
        x0 = 30
        y0 = SCREEN_H - 80
        for i, r in enumerate(RESOURCES):
            rect = pygame.Rect(x0 + i * 70, y0, 60, 60)
            rects.append((rect, r))
        return rects

    def _handle_steal_click(self, pos):
        g = self.game
        # click on the highlighted player panels
        for i, rect in self._player_panel_rects():
            if rect.collidepoint(pos) and i in g.steal_targets:
                g.steal_from(i)
                return

    def _player_panel_rects(self):
        rects = []
        n = len(self.game.players)
        h = 90
        for i in range(n):
            r = pygame.Rect(PANEL_X + 6, 10 + i * (h + 4), SCREEN_W - PANEL_X - 12, h)
            rects.append((i, r))
        return rects

    # ---------- resource picker (YOP / monopoly) ----------
    def _resource_picker_rects(self):
        rects = []
        x0 = PANEL_X + 14
        y0 = 730
        for i, r in enumerate(RESOURCES):
            rects.append((pygame.Rect(x0 + i * 50, y0, 44, 44), r))
        return rects

    def _pick_resource_at(self, pos):
        for rect, r in self._resource_picker_rects():
            if rect.collidepoint(pos):
                return r
        return None

    # ---------- dev card click ----------
    def _dev_card_rects(self):
        rects = []
        x0 = PANEL_X + 14
        y0 = 660
        i = 0
        p = self.game.cur()
        for c in ['knight', 'road_building', 'year_of_plenty', 'monopoly']:
            if p.dev_cards[c] > 0:
                rect = pygame.Rect(x0 + i * 60, y0, 54, 54)
                rects.append((rect, c, p.dev_cards[c]))
                i += 1
        return rects

    def _dev_card_at(self, pos):
        for rect, c, n in self._dev_card_rects():
            if rect.collidepoint(pos):
                return c
        return None

    # ---------- trade dialog ----------
    def _trade_rects(self):
        # centered dialog
        w, h = 520, 320
        x = (SCREEN_W - w) // 2
        y = (SCREEN_H - h) // 2
        outer = pygame.Rect(x, y, w, h)
        give_row = []
        recv_row = []
        for i, r in enumerate(RESOURCES):
            give_row.append((pygame.Rect(x + 30 + i * 90, y + 80, 70, 70), r))
            recv_row.append((pygame.Rect(x + 30 + i * 90, y + 180, 70, 70), r))
        confirm = pygame.Rect(x + w // 2 - 60, y + h - 50, 120, 36)
        return outer, give_row, recv_row, confirm

    def _handle_trade_click(self, pos):
        outer, give_row, recv_row, confirm = self._trade_rects()
        if not outer.collidepoint(pos):
            self.trade_open = False
            return
        for r, res in give_row:
            if r.collidepoint(pos):
                self.trade_give = res
                return
        for r, res in recv_row:
            if r.collidepoint(pos):
                self.trade_receive = res
                return
        if confirm.collidepoint(pos):
            if self.trade_give and self.trade_receive and self.trade_give != self.trade_receive:
                self.game.bank_trade(self.trade_give, self.trade_receive)
                self.trade_open = False

    # ============================================================
    # DRAW
    # ============================================================

    def draw(self, mouse):
        self.screen.fill(BG_COLOR)
        # draw outer "sea" rectangle
        pygame.draw.rect(self.screen, WATER_COLOR, pygame.Rect(20, 20, PANEL_X - 40, SCREEN_H - 40), border_radius=20)
        self._draw_board(mouse)
        self._draw_panel(mouse)
        self._draw_log()
        self._draw_message()
        if self.game.phase == Phase.DISCARD:
            self._draw_discard_overlay()
        if self.trade_open:
            self._draw_trade_dialog(mouse)
        if self.game.phase == Phase.GAME_OVER:
            self._draw_game_over()

    # ---------- board ----------
    def _draw_board(self, mouse):
        g = self.game
        # hexes
        for c, h in g.board.hexes.items():
            color = TERRAIN_COLORS[h.terrain]
            pygame.draw.polygon(self.screen, color, h.corners)
            pygame.draw.polygon(self.screen, (30, 30, 30), h.corners, 2)
            # number token
            if h.number is not None:
                pygame.draw.circle(self.screen, (245, 235, 200), (int(h.cx), int(h.cy)), 18)
                pygame.draw.circle(self.screen, (40, 40, 40), (int(h.cx), int(h.cy)), 18, 1)
                num_color = (190, 30, 30) if h.number in (6, 8) else (30, 30, 30)
                txt = self.font_md.render(str(h.number), True, num_color)
                self.screen.blit(txt, txt.get_rect(center=(h.cx, h.cy - 4)))
                # pips
                pip_count = NUMBER_PIPS[h.number]
                pip_y = h.cy + 12
                pip_w = 4
                tot_w = pip_count * pip_w + (pip_count - 1) * 2
                px = h.cx - tot_w / 2
                for _ in range(pip_count):
                    pygame.draw.circle(self.screen, num_color, (int(px + pip_w / 2), int(pip_y)), 2)
                    px += pip_w + 2
            # robber
            if c == g.board.robber:
                rect = pygame.Rect(0, 0, 24, 32)
                rect.center = (h.cx + 18, h.cy - 18)
                pygame.draw.rect(self.screen, (30, 30, 30), rect, border_radius=8)
                pygame.draw.circle(self.screen, (30, 30, 30), (rect.centerx, rect.top + 2), 8)

        # ports - draw small markers near port vertices
        seen_pairs = set()
        for coord, dir_idx, kind in PORT_PLACEMENTS:
            h = g.board.hexes[coord]
            v1 = h.vkeys[dir_idx]
            v2 = h.vkeys[(dir_idx + 1) % 6]
            pair = frozenset({v1, v2})
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            p1 = g.board.vertices[v1].pos
            p2 = g.board.vertices[v2].pos
            mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            # Find direction outward from center
            dx = mid[0] - BOARD_CX
            dy = mid[1] - BOARD_CY
            length = math.hypot(dx, dy) or 1
            ox = mid[0] + dx / length * 28
            oy = mid[1] + dy / length * 28
            color = RESOURCE_COLORS.get(kind, (220, 220, 220)) if kind != '3:1' else (255, 250, 230)
            pygame.draw.circle(self.screen, color, (int(ox), int(oy)), 14)
            pygame.draw.circle(self.screen, (40, 40, 40), (int(ox), int(oy)), 14, 2)
            label = "3:1" if kind == '3:1' else f"2:1\n{kind[:2]}"
            for j, line in enumerate(label.split("\n")):
                t = self.font_sm.render(line, True, (20, 20, 20))
                self.screen.blit(t, t.get_rect(center=(ox, oy - 6 + j * 12)))
            # Lines connecting port to its two vertices
            pygame.draw.line(self.screen, (40, 40, 40), (ox, oy), p1, 1)
            pygame.draw.line(self.screen, (40, 40, 40), (ox, oy), p2, 1)

        # draw roads
        for ek, e in g.board.edges.items():
            if e.road_owner is None:
                continue
            color = PLAYER_COLORS[e.road_owner]
            v1 = g.board.vertices[e.v1].pos
            v2 = g.board.vertices[e.v2].pos
            pygame.draw.line(self.screen, color, v1, v2, 7)
            pygame.draw.line(self.screen, (20, 20, 20), v1, v2, 1)

        # draw highlight for valid placements
        highlight = self._current_highlights()
        if highlight:
            kind, items = highlight
            for item in items:
                if kind == 'vertex':
                    v = g.board.vertices[item]
                    pygame.draw.circle(self.screen, HIGHLIGHT_COLOR,
                                       (int(v.pos[0]), int(v.pos[1])), 12, 2)
                elif kind == 'edge':
                    e = g.board.edges[item]
                    v1 = g.board.vertices[e.v1].pos
                    v2 = g.board.vertices[e.v2].pos
                    pygame.draw.line(self.screen, HIGHLIGHT_COLOR, v1, v2, 3)
                elif kind == 'hex':
                    h = g.board.hexes[item]
                    pygame.draw.polygon(self.screen, HIGHLIGHT_COLOR, h.corners, 4)

        # draw buildings
        for vk, v in g.board.vertices.items():
            if v.building is None:
                continue
            color = PLAYER_COLORS[v.owner]
            x, y = v.pos
            if v.building == 'settlement':
                pts = [(x - 10, y + 8), (x + 10, y + 8), (x + 10, y - 4),
                       (x, y - 14), (x - 10, y - 4)]
                pygame.draw.polygon(self.screen, color, pts)
                pygame.draw.polygon(self.screen, (20, 20, 20), pts, 2)
            else:  # city
                pts = [(x - 14, y + 10), (x + 14, y + 10), (x + 14, y - 4),
                       (x + 4, y - 4), (x + 4, y - 14), (x - 6, y - 14), (x - 14, y - 4)]
                pygame.draw.polygon(self.screen, color, pts)
                pygame.draw.polygon(self.screen, (20, 20, 20), pts, 2)

    def _current_highlights(self):
        g = self.game
        p = g.cur()
        if g.phase == Phase.SETUP_PLACE_SETTLEMENT:
            return ('vertex', g.valid_settlement_spots(p.idx, setup=True))
        if g.phase == Phase.SETUP_PLACE_ROAD:
            return ('edge', g.valid_road_spots(p.idx, setup_after_vertex=g.setup_last_settlement))
        if g.phase == Phase.PLACE_SETTLEMENT:
            return ('vertex', g.valid_settlement_spots(p.idx))
        if g.phase == Phase.PLACE_ROAD or g.phase == Phase.ROAD_BUILDING:
            return ('edge', g.valid_road_spots(p.idx))
        if g.phase == Phase.PLACE_CITY:
            return ('vertex', g.valid_city_spots(p.idx))
        if g.phase == Phase.MOVE_ROBBER:
            return ('hex', [c for c in g.board.hexes if c != g.board.robber])
        return None

    # ---------- right panel ----------
    def _draw_panel(self, mouse):
        g = self.game
        pygame.draw.rect(self.screen, PANEL_COLOR,
                         pygame.Rect(PANEL_X, 0, SCREEN_W - PANEL_X, SCREEN_H))
        pygame.draw.line(self.screen, PANEL_BORDER, (PANEL_X, 0), (PANEL_X, SCREEN_H), 2)

        # Player summary cards
        for i, rect in self._player_panel_rects():
            self._draw_player_card(rect, i)

        # Action buttons
        for b in self.buttons:
            enabled = self._button_enabled(b)
            hover = b.rect.collidepoint(mouse) and enabled
            color = BUTTON_DISABLED if not enabled else (BUTTON_HOVER if hover else BUTTON_COLOR)
            pygame.draw.rect(self.screen, color, b.rect, border_radius=6)
            pygame.draw.rect(self.screen, PANEL_BORDER, b.rect, 1, border_radius=6)
            t = self.font.render(b.label, True, TEXT_COLOR if enabled else DIM_TEXT)
            self.screen.blit(t, t.get_rect(center=b.rect.center))

        # Current player's resources/dev cards (bottom-ish)
        self._draw_current_hand()

        # Resource picker for YOP/monopoly
        if g.phase in (Phase.YEAR_OF_PLENTY, Phase.MONOPOLY):
            for rect, r in self._resource_picker_rects():
                pygame.draw.rect(self.screen, RESOURCE_COLORS[r], rect, border_radius=6)
                pygame.draw.rect(self.screen, (20, 20, 20), rect, 2, border_radius=6)
                t = self.font_sm.render(r[:2].upper(), True, (20, 20, 20))
                self.screen.blit(t, t.get_rect(center=rect.center))

    def _draw_player_card(self, rect, i):
        g = self.game
        p = g.players[i]
        is_current = (i == g.current)
        bg = (60, 60, 80) if is_current else (45, 45, 55)
        if g.phase == Phase.STEAL and i in g.steal_targets:
            bg = (120, 80, 30)
        pygame.draw.rect(self.screen, bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, p.color, rect, 3, border_radius=8)

        # Name + VP
        name = self.font_md.render(p.name, True, p.color)
        self.screen.blit(name, (rect.x + 10, rect.y + 6))
        vp_label = f"VP: {p.public_victory_points()}"
        if is_current:
            vp_label = f"VP: {p.victory_points()}"  # show full only for current
        vp = self.font.render(vp_label, True, TEXT_COLOR)
        self.screen.blit(vp, vp.get_rect(topright=(rect.right - 10, rect.y + 8)))

        # Resources (count visible only for current player; others see total)
        y0 = rect.y + 32
        if is_current:
            for j, r in enumerate(RESOURCES):
                ix = rect.x + 10 + j * 36
                iy = y0
                pygame.draw.rect(self.screen, RESOURCE_COLORS[r],
                                 pygame.Rect(ix, iy, 30, 22), border_radius=4)
                pygame.draw.rect(self.screen, (20, 20, 20),
                                 pygame.Rect(ix, iy, 30, 22), 1, border_radius=4)
                t = self.font_sm.render(r[:2].upper(), True, (20, 20, 20))
                self.screen.blit(t, t.get_rect(center=(ix + 15, iy + 11)))
                cnt = self.font_sm.render(str(p.resources[r]), True, TEXT_COLOR)
                self.screen.blit(cnt, (ix + 11, iy + 24))
        else:
            t = self.font.render(f"Cards: {p.total_resources()}   "
                                 f"Dev: {p.total_dev_cards()}",
                                 True, TEXT_COLOR)
            self.screen.blit(t, (rect.x + 10, y0))
        # roads / settlements / cities counts
        y1 = rect.y + rect.height - 22
        info = (f"R:{len(p.roads)}  S:{len(p.settlements)}  C:{len(p.cities)}  "
                f"K:{p.played_knights}  LR:{p.longest_road_length}")
        tags = []
        if p.has_largest_army:
            tags.append("[LA]")
        if p.has_longest_road:
            tags.append("[LR]")
        if tags:
            info += "  " + " ".join(tags)
        t = self.font_sm.render(info, True, DIM_TEXT)
        self.screen.blit(t, (rect.x + 10, y1))

    def _draw_current_hand(self):
        g = self.game
        p = g.cur()
        x0 = PANEL_X + 14
        y0 = 620
        title = self.font.render(f"{p.name}'s dev cards (click to play):", True, TEXT_COLOR)
        self.screen.blit(title, (x0, y0 - 22))
        # show playable
        for rect, c, n in self._dev_card_rects():
            pygame.draw.rect(self.screen, (200, 200, 230), rect, border_radius=6)
            pygame.draw.rect(self.screen, (20, 20, 20), rect, 2, border_radius=6)
            t = self.font_sm.render(DEV_CARD_NAMES[c][:3], True, (20, 20, 20))
            self.screen.blit(t, t.get_rect(center=(rect.centerx, rect.centery - 8)))
            t2 = self.font_sm.render(f"x{n}", True, (20, 20, 20))
            self.screen.blit(t2, t2.get_rect(center=(rect.centerx, rect.centery + 12)))
        # also show vp + new card counts
        new_total = sum(p.dev_cards_new.values())
        vp_total = p.dev_cards['vp'] + p.dev_cards_new['vp']
        info = self.font_sm.render(f"Newly bought (locked until next turn): {new_total}   VP cards: {vp_total}",
                                    True, DIM_TEXT)
        self.screen.blit(info, (x0, 720))

    # ---------- log + message ----------
    def _draw_log(self):
        x = PANEL_X + 14
        y = 760
        pygame.draw.line(self.screen, PANEL_BORDER, (x - 6, y - 6),
                         (SCREEN_W - 14, y - 6), 1)
        for i, line in enumerate(self.game.log[-5:]):
            t = self.font_sm.render(line, True, DIM_TEXT)
            self.screen.blit(t, (x, y + i * 16))

    def _draw_message(self):
        g = self.game
        bar = pygame.Rect(20, SCREEN_H - 36, PANEL_X - 40, 24)
        pygame.draw.rect(self.screen, (20, 20, 30), bar, border_radius=6)
        # current player tag
        p = g.cur()
        cap = f"  [{p.name}]  {g.message}"
        if g.has_rolled and g.dice != (0, 0):
            cap += f"   (roll: {g.dice[0]}+{g.dice[1]}={sum(g.dice)})"
        t = self.font.render(cap, True, TEXT_COLOR)
        self.screen.blit(t, (bar.x + 8, bar.y + 4))

    def _draw_discard_overlay(self):
        g = self.game
        if not g.discard_needed:
            return
        pidx = next(iter(g.discard_needed))
        p = g.players[pidx]
        # banner
        banner = pygame.Rect(20, SCREEN_H - 110, PANEL_X - 40, 70)
        pygame.draw.rect(self.screen, (60, 30, 30), banner, border_radius=8)
        pygame.draw.rect(self.screen, (180, 80, 80), banner, 2, border_radius=8)
        t = self.font_md.render(
            f"{p.name}: discard {g.discard_needed[pidx]} card(s) - click a resource",
            True, TEXT_COLOR)
        self.screen.blit(t, (banner.x + 10, banner.y + 6))
        for rect, r in self._discard_icon_rects():
            pygame.draw.rect(self.screen, RESOURCE_COLORS[r], rect, border_radius=6)
            pygame.draw.rect(self.screen, (20, 20, 20), rect, 2, border_radius=6)
            t = self.font_sm.render(r.upper(), True, (20, 20, 20))
            self.screen.blit(t, t.get_rect(center=(rect.centerx, rect.centery - 4)))
            cnt = self.font_md.render(str(p.resources[r]), True, (20, 20, 20))
            self.screen.blit(cnt, cnt.get_rect(center=(rect.centerx, rect.centery + 14)))

    def _draw_trade_dialog(self, mouse):
        outer, give_row, recv_row, confirm = self._trade_rects()
        pygame.draw.rect(self.screen, (30, 30, 45), outer, border_radius=10)
        pygame.draw.rect(self.screen, (180, 180, 200), outer, 2, border_radius=10)
        title = self.font_md.render("Bank/Port Trade", True, TEXT_COLOR)
        self.screen.blit(title, (outer.x + 16, outer.y + 12))
        p = self.game.cur()

        give_label = self.font.render("Give:", True, TEXT_COLOR)
        self.screen.blit(give_label, (outer.x + 16, outer.y + 56))
        for rect, r in give_row:
            ratio = self.game.best_ratio(p, r)
            sel = (self.trade_give == r)
            color = RESOURCE_COLORS[r]
            pygame.draw.rect(self.screen, color, rect, border_radius=8)
            pygame.draw.rect(self.screen,
                             HIGHLIGHT_COLOR if sel else (20, 20, 20),
                             rect, 3 if sel else 2, border_radius=8)
            t = self.font.render(r.upper(), True, (20, 20, 20))
            self.screen.blit(t, t.get_rect(center=(rect.centerx, rect.centery - 12)))
            t2 = self.font_sm.render(f"{ratio}:1  ({p.resources[r]})", True, (20, 20, 20))
            self.screen.blit(t2, t2.get_rect(center=(rect.centerx, rect.centery + 16)))

        recv_label = self.font.render("Receive:", True, TEXT_COLOR)
        self.screen.blit(recv_label, (outer.x + 16, outer.y + 158))
        for rect, r in recv_row:
            sel = (self.trade_receive == r)
            color = RESOURCE_COLORS[r]
            pygame.draw.rect(self.screen, color, rect, border_radius=8)
            pygame.draw.rect(self.screen,
                             HIGHLIGHT_COLOR if sel else (20, 20, 20),
                             rect, 3 if sel else 2, border_radius=8)
            t = self.font.render(r.upper(), True, (20, 20, 20))
            self.screen.blit(t, t.get_rect(center=rect.center))

        ready = (self.trade_give and self.trade_receive
                 and self.trade_give != self.trade_receive
                 and p.resources[self.trade_give] >= self.game.best_ratio(p, self.trade_give))
        c = (50, 130, 60) if ready else BUTTON_DISABLED
        pygame.draw.rect(self.screen, c, confirm, border_radius=6)
        ct = self.font.render("Confirm", True, TEXT_COLOR)
        self.screen.blit(ct, ct.get_rect(center=confirm.center))

    def _draw_game_over(self):
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))
        winner = self.game.players[self.game.winner]
        t = self.font_lg.render(f"{winner.name} wins with {winner.victory_points()} VP!",
                                True, winner.color)
        self.screen.blit(t, t.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2)))


@dataclass
class Button:
    x: int
    y: int
    w: int
    h: int
    label: str
    action: str
    key: Optional[int] = None

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(self.x, self.y, self.w, self.h)


# ============================================================
# ENTRY
# ============================================================

def main():
    num_players = 3
    if len(sys.argv) > 1:
        try:
            num_players = int(sys.argv[1])
        except ValueError:
            pass
    num_players = max(3, min(4, num_players))

    game = Game(num_players)
    UI(game).run()


if __name__ == "__main__":
    main()
