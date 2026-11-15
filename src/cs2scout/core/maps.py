"""World (Hammer units) to radar pixels (design §5.5). Pure: the radar facts come in as data."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class Radar:
    map: str
    pos_x: float  # world x of the radar's left edge
    pos_y: float  # world y of the radar's top edge
    scale: float  # world units per pixel
    width: int
    height: int
    lower_max_z: float | None = None  # positions below this altitude use the lower radar

    @classmethod
    def from_info(cls, info: dict) -> Radar:
        return cls(info["map"], info["pos_x"], info["pos_y"], info["scale"], info["width"],
                   info["height"], info.get("lower_max_z"))  # fmt: skip

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.pos_x) / self.scale, (self.pos_y - y) / self.scale

    def px(self, col: str = "x") -> pl.Expr:
        return (pl.col(col) - self.pos_x) / self.scale

    def py(self, col: str = "y") -> pl.Expr:
        return (self.pos_y - pl.col(col)) / self.scale

    def level(self, col: str = "z") -> pl.Expr:
        if self.lower_max_z is None:
            return pl.lit("default")
        return (
            pl.when(pl.col(col) < self.lower_max_z)
            .then(pl.lit("lower"))
            .otherwise(pl.lit("default"))
        )
