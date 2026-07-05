from __future__ import annotations

from model import Corona, Light, LightType, TimingBlock, SirenSetting


def build_sample_settings() -> list:
    police = SirenSetting(
        id=1,
        name="Police Interceptor - Standard",
        texture_name="VehicleLight_sirenlight",
    )
    police.lights.extend([
        Light(
            name="Rotator - Red",
            light_type=LightType.ROTATOR,
            color="0xFFFF0000",
            intensity=1.2,
            rotate=True,
            scale=False,
            flash=False,
            corona=Corona(intensity=0.0, size=0.0),
            rotation=TimingBlock(speed=0.8, direction_cw=True, sequencer=0xFFFFFFFF),
            flashiness=TimingBlock(sequencer=0xFFFFFFFF),
        ),
        Light(
            name="Rotator - Blue",
            light_type=LightType.ROTATOR,
            color="0xFF0000FF",
            intensity=1.2,
            rotate=True,
            scale=False,
            flash=False,
            corona=Corona(intensity=0.0, size=0.0),
            rotation=TimingBlock(speed=0.8, direction_cw=False, sequencer=0xFFFFFFFF),
            flashiness=TimingBlock(sequencer=0xFFFFFFFF),
        ),
        Light(
            name="LED Corner - Red",
            light_type=LightType.LED,
            color="0xFFFF0000",
            intensity=1.5,
            rotate=False,
            scale=True,
            scale_factor=10.0,
            flash=True,
            corona=Corona(intensity=0.0, size=0.0),
            flashiness=TimingBlock(sequencer=0xAAAAAAAA),
        ),
        Light(
            name="LED Corner - Blue",
            light_type=LightType.LED,
            color="0xFF0000FF",
            intensity=1.5,
            rotate=False,
            scale=True,
            scale_factor=10.0,
            flash=True,
            corona=Corona(intensity=0.0, size=0.0),
            flashiness=TimingBlock(sequencer=0x55555555),
        ),
        Light(
            name="Halogen Wig-Wag - White",
            light_type=LightType.HALOGEN,
            color="0xFFFFFFFF",
            intensity=1.0,
            rotate=False,
            scale=False,
            flash=True,
            corona=Corona(intensity=1.0, size=1.0),
            flashiness=TimingBlock(sequencer=0x0000FFFF),
        ),
        Light(
            name="Halogen Deck - Amber",
            light_type=LightType.HALOGEN,
            color="0xFFFFA500",
            intensity=1.0,
            rotate=False,
            scale=False,
            flash=True,
            corona=Corona(intensity=1.0, size=1.0),
            flashiness=TimingBlock(sequencer=0xFFFF0000),
        ),
    ])

    unmarked = SirenSetting(
        id=2,
        name="Unmarked - Grille/Dash",
        texture_name="VehicleLight_sirenlight",
    )
    unmarked.lights.extend([
        Light(
            name="Grille - Red",
            light_type=LightType.LED,
            color="0xFFFF0000",
            rotate=False,
            scale=True,
            scale_factor=10.0,
            flash=True,
            corona=Corona(intensity=0.0, size=0.0),
            flashiness=TimingBlock(sequencer=0xF0F0F0F0),
        ),
        Light(
            name="Grille - Blue",
            light_type=LightType.LED,
            color="0xFF0000FF",
            rotate=False,
            scale=True,
            scale_factor=10.0,
            flash=True,
            corona=Corona(intensity=0.0, size=0.0),
            flashiness=TimingBlock(sequencer=0x0F0F0F0F),
        ),
        Light(
            name="Dash - Amber",
            light_type=LightType.HALOGEN,
            color="0xFFFFA500",
            rotate=False,
            scale=False,
            flash=True,
            corona=Corona(intensity=1.0, size=1.0),
            flashiness=TimingBlock(sequencer=0x00FF00FF),
        ),
    ])

    return [police, unmarked]
