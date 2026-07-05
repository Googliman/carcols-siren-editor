from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LightType(Enum):
    ROTATOR = "Rotator"
    LED = "LED"
    HALOGEN = "Halogen"


# Presets applied when the user picks a light type in the UI. Real carcols.meta has no
# explicit LED/Halogen/Rotator field - this tool infers/applies it via rotate + corona
# (a physical glow means Halogen-style bulb, no corona + scale trick means modern LED bar).
LIGHT_TYPE_PRESETS = {
    LightType.ROTATOR: dict(rotate=True, scale=False, scale_factor=1.0, flash=False,
                             corona_intensity=0.0, corona_size=0.0),
    LightType.LED: dict(rotate=False, scale=True, scale_factor=10.0, flash=True,
                         corona_intensity=0.0, corona_size=0.0),
    LightType.HALOGEN: dict(rotate=False, scale=False, scale_factor=1.0, flash=True,
                             corona_intensity=1.0, corona_size=1.0),
}


def infer_light_type(rotate: bool, corona_intensity: float, corona_size: float) -> LightType:
    """Reverse of LIGHT_TYPE_PRESETS, used to classify lights imported from real files."""
    if rotate:
        return LightType.ROTATOR
    if corona_intensity > 0 or corona_size > 0:
        return LightType.HALOGEN
    return LightType.LED


def sequencer_to_bits(value: int, length: int = 32) -> list:
    return [bool((value >> i) & 1) for i in range(length)]


def bits_to_sequencer(bits: list) -> int:
    value = 0
    for i, on in enumerate(bits):
        if on:
            value |= (1 << i)
    return value


SEQUENCER_PRESETS = {
    "Always On": 0xFFFFFFFF,
    "Always Off": 0x00000000,
    "Alternate (fast)": 0xAAAAAAAA,
    "Alternate (inverse)": 0x55555555,
    "Half Cycle": 0x0000FFFF,
    "Quarter Pulse": 0x000000FF,
    "Double Flash": 0x00CC00CC,
    "Wig-Wag Left": 0xF0F0F0F0,
    "Wig-Wag Right": 0x0F0F0F0F,
}


@dataclass
class TimingBlock:
    """Shared shape used by both <rotation> and <flashiness> blocks in real carcols.meta."""
    delta: float = 0.0
    start: float = 0.0
    speed: float = 1.0
    sequencer: int = 0xFFFFFFFF
    multiples: int = 1
    direction_cw: bool = True
    sync_to_bpm: bool = True


@dataclass
class Corona:
    intensity: float = 0.0
    size: float = 0.0
    pull: float = 0.0
    face_camera: bool = False


@dataclass
class Light:
    name: str = "Light"
    light_type: LightType = LightType.LED
    color: str = "0xFFFF0000"  # canonical form is 0xAARRGGBB, matching real carcols.meta
    intensity: float = 1.0
    light_group: int = 0
    rotate: bool = False
    scale: bool = True
    scale_factor: float = 10.0
    flash: bool = True
    emits_light: bool = True
    spot_light: bool = True
    cast_shadows: bool = False
    rotation: TimingBlock = field(default_factory=TimingBlock)
    flashiness: TimingBlock = field(default_factory=TimingBlock)
    corona: Corona = field(default_factory=Corona)
    comment: str = ""  # verbatim XML comment (e.g. "Siren 1") preceding this light on import

    def apply_light_type_preset(self) -> None:
        preset = LIGHT_TYPE_PRESETS[self.light_type]
        self.rotate = preset["rotate"]
        self.scale = preset["scale"]
        self.scale_factor = preset["scale_factor"]
        self.flash = preset["flash"]
        self.corona.intensity = preset["corona_intensity"]
        self.corona.size = preset["corona_size"]


@dataclass
class SirenSetting:
    id: int = 1
    name: str = "New Siren"
    texture_name: str = "VehicleLight_sirenlight"
    time_multiplier: float = 1.0
    light_falloff_max: float = 25.0
    light_falloff_exponent: float = 30.0
    light_inner_cone_angle: float = 4.5
    light_outer_cone_angle: float = 30.0
    light_offset: float = 0.0
    sequencer_bpm: int = 600
    left_head_light_sequencer: int = 0
    right_head_light_sequencer: int = 0
    left_tail_light_sequencer: int = 0
    right_tail_light_sequencer: int = 0
    left_head_light_multiples: int = 1
    right_head_light_multiples: int = 1
    left_tail_light_multiples: int = 1
    right_tail_light_multiples: int = 1
    use_real_lights: bool = True
    lights: list = field(default_factory=list)


@dataclass
class CarcolsDocument:
    """A parsed carcols.meta: the siren settings we edit, plus verbatim passthroughs
    of the <Kits> and <Lights> sections (vehicle mod kits, indicators/headlights/
    taillights) which this tool does not edit but must not destroy when re-exporting
    a real vehicle's file."""
    siren_settings: list = field(default_factory=list)
    raw_kits_element: object = None
    raw_lights_element: object = None
