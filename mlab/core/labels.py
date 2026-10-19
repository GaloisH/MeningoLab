"""标签（病灶类别）定义。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import numpy as np

# 区分度高、在深浅背景上都醒目的调色板
PALETTE = [
    (255, 99, 71), (255, 196, 61), (64, 196, 120), (79, 156, 255),
    (186, 104, 255), (0, 206, 209), (255, 128, 191), (160, 214, 76),
    (255, 160, 64), (120, 120, 255), (230, 80, 160), (90, 220, 200),
]


@dataclass
class Label:
    value: int
    name: str
    color: tuple[int, int, int]
    visible: bool = True

    @property
    def hex(self) -> str:
        return "#%02x%02x%02x" % self.color


class LabelSet:
    def __init__(self, labels: list[Label] | None = None):
        self.labels: list[Label] = sorted(labels or [], key=lambda l: l.value)

    def __iter__(self):
        return iter(self.labels)

    def __len__(self):
        return len(self.labels)

    def get(self, value: int) -> Label | None:
        for lab in self.labels:
            if lab.value == value:
                return lab
        return None

    def name_of(self, value: int) -> str:
        if value == 0:
            return "背景"
        lab = self.get(value)
        return lab.name if lab else f"标签 {value}"

    def next_free_value(self) -> int:
        used = {l.value for l in self.labels}
        v = 1
        while v in used:
            v += 1
        return v

    def add(self, name: str, value: int | None = None, color=None) -> Label:
        value = self.next_free_value() if value is None else value
        if not 1 <= value <= 255:
            raise ValueError("标签值必须在 1~255 之间")
        if self.get(value):
            raise ValueError(f"标签值 {value} 已存在")
        color = tuple(color) if color else PALETTE[(value - 1) % len(PALETTE)]
        lab = Label(value, name, color)  # type: ignore[arg-type]
        self.labels.append(lab)
        self.labels.sort(key=lambda l: l.value)
        return lab

    def ensure(self, value: int, name: str | None = None) -> Label:
        return self.get(value) or self.add(name or f"标签 {value}", value)

    def remove(self, value: int) -> None:
        self.labels = [l for l in self.labels if l.value != value]

    def lut(self) -> np.ndarray:
        """返回 (256, 4) 的 float32 颜色查找表，alpha 为 0/1 表示是否显示。"""
        lut = np.zeros((256, 4), np.float32)
        for v in range(1, 256):  # 未定义的值也给一个颜色，避免“看不见的标注”
            lut[v, :3] = PALETTE[(v - 1) % len(PALETTE)]
            lut[v, 3] = 1.0
        for lab in self.labels:
            lut[lab.value, :3] = lab.color
            lut[lab.value, 3] = 1.0 if lab.visible else 0.0
        return lut

    # ------------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {"labels": [{"value": l.value, "name": l.name, "color": list(l.color)} for l in self.labels]}

    @classmethod
    def from_dict(cls, d: dict) -> "LabelSet":
        return cls([Label(int(x["value"]), str(x["name"]), tuple(x["color"])) for x in d.get("labels", [])])  # type: ignore[arg-type]

    def save(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "LabelSet":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def default(cls) -> "LabelSet":
        text = resources.files("mlab.resources").joinpath("default_labels.json").read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text))
