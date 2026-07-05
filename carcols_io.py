from __future__ import annotations

import xml.etree.ElementTree as ET

from model import (
    CarcolsDocument,
    Corona,
    Light,
    SirenSetting,
    TimingBlock,
    infer_light_type,
)


def _parse_int(text: str) -> int:
    text = text.strip()
    if text.lower().startswith(("0x", "-0x")):
        value = int(text, 16)
    else:
        value = int(float(text))
    if value < 0:
        value += 1 << 32
    return value


def normalize_argb_hex(text: str):
    """The app's canonical color format is '0xAARRGGBB' (matching real carcols.meta).
    Accepts that form, '#RRGGBB', 'RRGGBB', '0xRRGGBB' or 'AARRGGBB' and returns a
    normalized '0xAARRGGBB' string (assuming full alpha if none given), or None if the
    text can't be parsed as a color."""
    if text is None:
        return None
    value = text.strip()
    if value.lower().startswith("0x"):
        value = value[2:]
    value = value.lstrip("#")
    if len(value) == 8 and all(c in "0123456789ABCDEFabcdef" for c in value):
        return f"0x{value.upper()}"
    if len(value) == 6 and all(c in "0123456789ABCDEFabcdef" for c in value):
        return f"0xFF{value.upper()}"
    return None


def argb_to_tk(value: str) -> str:
    """Convert our canonical '0xAARRGGBB' color into a '#RRGGBB' string Tkinter can render."""
    normalized = normalize_argb_hex(value)
    if normalized is None:
        return "#FFFFFF"
    return f"#{normalized[4:10]}"


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _set_val(parent: ET.Element, tag: str, value) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.set("value", _fmt(value))
    return el


def _get_value(elem: ET.Element, tag: str, default=None, cast=float):
    child = elem.find(tag)
    if child is None:
        return default
    val = child.get("value")
    if val is None:
        return default
    val = val.strip()
    if cast is bool:
        return val.lower() == "true"
    if cast is int:
        return _parse_int(val)
    try:
        return float(val)
    except ValueError:
        return default


def _get_text(elem: ET.Element, tag: str, default: str = "") -> str:
    child = elem.find(tag)
    if child is None:
        return default
    return (child.text or "").strip() or default


def _indent(elem: ET.Element, level: int = 0) -> None:
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            _indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = i + "  "
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def _parse_timing_block(elem) -> TimingBlock:
    if elem is None:
        return TimingBlock()
    return TimingBlock(
        delta=_get_value(elem, "delta", default=0.0),
        start=_get_value(elem, "start", default=0.0),
        speed=_get_value(elem, "speed", default=1.0),
        sequencer=_get_value(elem, "sequencer", default=0xFFFFFFFF, cast=int),
        multiples=_get_value(elem, "multiples", default=1, cast=int),
        direction_cw=_get_value(elem, "direction", default=True, cast=bool),
        sync_to_bpm=_get_value(elem, "syncToBpm", default=True, cast=bool),
    )


def _write_timing_block(parent: ET.Element, tag: str, block: TimingBlock) -> ET.Element:
    el = ET.SubElement(parent, tag)
    _set_val(el, "delta", block.delta)
    _set_val(el, "start", block.start)
    _set_val(el, "speed", block.speed)
    _set_val(el, "sequencer", block.sequencer)
    _set_val(el, "multiples", block.multiples)
    _set_val(el, "direction", block.direction_cw)
    _set_val(el, "syncToBpm", block.sync_to_bpm)
    return el


def _parse_corona(elem) -> Corona:
    if elem is None:
        return Corona()
    return Corona(
        intensity=_get_value(elem, "intensity", default=0.0),
        size=_get_value(elem, "size", default=0.0),
        pull=_get_value(elem, "pull", default=0.0),
        face_camera=_get_value(elem, "faceCamera", default=False, cast=bool),
    )


def _write_corona(parent: ET.Element, corona: Corona) -> ET.Element:
    el = ET.SubElement(parent, "corona")
    _set_val(el, "intensity", corona.intensity)
    _set_val(el, "size", corona.size)
    _set_val(el, "pull", corona.pull)
    _set_val(el, "faceCamera", corona.face_camera)
    return el


def _get_nested_sequencer(item_el: ET.Element, tag: str, default: int = 0) -> int:
    child = item_el.find(tag)
    if child is None:
        return default
    seq = child.find("sequencer")
    if seq is None or seq.get("value") is None:
        return default
    return _parse_int(seq.get("value"))


def _write_nested_sequencer(parent: ET.Element, tag: str, value: int) -> None:
    el = ET.SubElement(parent, tag)
    _set_val(el, "sequencer", value)


def _leading_comment(elem: ET.Element) -> str:
    """Some carcols.meta files put the '<!-- Siren N -->' comment as the first child
    inside the <Item>, rather than as a preceding sibling before it. Check both spots."""
    for child in elem:
        if child.tag is ET.Comment:
            return (child.text or "").strip()
        break
    return ""


def _parse_light(light_item: ET.Element, idx: int, comment: str = "") -> Light:
    comment = comment or _leading_comment(light_item)
    rotate = _get_value(light_item, "rotate", default=False, cast=bool)
    corona = _parse_corona(light_item.find("corona"))
    color_el = light_item.find("color")

    light = Light(
        name=f"Light {idx}",
        comment=comment,
        color=(normalize_argb_hex(color_el.get("value")) or "0xFFFFFFFF") if color_el is not None else "0xFFFFFFFF",
        intensity=_get_value(light_item, "intensity", default=1.0),
        light_group=_get_value(light_item, "lightGroup", default=0, cast=int),
        rotate=rotate,
        scale=_get_value(light_item, "scale", default=True, cast=bool),
        scale_factor=_get_value(light_item, "scaleFactor", default=10.0),
        flash=_get_value(light_item, "flash", default=True, cast=bool),
        emits_light=_get_value(light_item, "light", default=True, cast=bool),
        spot_light=_get_value(light_item, "spotLight", default=True, cast=bool),
        cast_shadows=_get_value(light_item, "castShadows", default=False, cast=bool),
        rotation=_parse_timing_block(light_item.find("rotation")),
        flashiness=_parse_timing_block(light_item.find("flashiness")),
        corona=corona,
    )
    light.light_type = infer_light_type(rotate, corona.intensity, corona.size)
    return light


def _write_light(sirens_el: ET.Element, light: Light, idx: int) -> None:
    comment_text = light.comment.strip() if light.comment.strip() else f"Siren {idx}"
    sirens_el.append(ET.Comment(f" {comment_text} "))
    item = ET.SubElement(sirens_el, "Item")
    _write_timing_block(item, "rotation", light.rotation)
    _write_timing_block(item, "flashiness", light.flashiness)
    _write_corona(item, light.corona)
    ET.SubElement(item, "color").set("value", normalize_argb_hex(light.color) or "0xFFFFFFFF")
    _set_val(item, "intensity", light.intensity)
    _set_val(item, "lightGroup", light.light_group)
    _set_val(item, "rotate", light.rotate)
    _set_val(item, "scale", light.scale)
    _set_val(item, "scaleFactor", light.scale_factor)
    _set_val(item, "flash", light.flash)
    _set_val(item, "light", light.emits_light)
    _set_val(item, "spotLight", light.spot_light)
    _set_val(item, "castShadows", light.cast_shadows)


def _parse_siren_setting(item_el: ET.Element) -> SirenSetting:
    setting = SirenSetting(
        id=_get_value(item_el, "id", default=1, cast=int),
        name=_get_text(item_el, "name", default="Unnamed"),
        texture_name=_get_text(item_el, "textureName", default="VehicleLight_sirenlight"),
        time_multiplier=_get_value(item_el, "timeMultiplier", default=1.0),
        light_falloff_max=_get_value(item_el, "lightFalloffMax", default=25.0),
        light_falloff_exponent=_get_value(item_el, "lightFalloffExponent", default=30.0),
        light_inner_cone_angle=_get_value(item_el, "lightInnerConeAngle", default=4.5),
        light_outer_cone_angle=_get_value(item_el, "lightOuterConeAngle", default=30.0),
        light_offset=_get_value(item_el, "lightOffset", default=0.0),
        sequencer_bpm=_get_value(item_el, "sequencerBpm", default=600, cast=int),
        left_head_light_sequencer=_get_nested_sequencer(item_el, "leftHeadLight"),
        right_head_light_sequencer=_get_nested_sequencer(item_el, "rightHeadLight"),
        left_tail_light_sequencer=_get_nested_sequencer(item_el, "leftTailLight"),
        right_tail_light_sequencer=_get_nested_sequencer(item_el, "rightTailLight"),
        left_head_light_multiples=_get_value(item_el, "leftHeadLightMultiples", default=1, cast=int),
        right_head_light_multiples=_get_value(item_el, "rightHeadLightMultiples", default=1, cast=int),
        left_tail_light_multiples=_get_value(item_el, "leftTailLightMultiples", default=1, cast=int),
        right_tail_light_multiples=_get_value(item_el, "rightTailLightMultiples", default=1, cast=int),
        use_real_lights=_get_value(item_el, "useRealLights", default=True, cast=bool),
    )

    sirens_el = item_el.find("sirens")
    if sirens_el is not None:
        idx = 0
        pending_comment = ""
        for child in sirens_el:
            if child.tag is ET.Comment:
                pending_comment = (child.text or "").strip()
            elif child.tag == "Item":
                idx += 1
                setting.lights.append(_parse_light(child, idx, comment=pending_comment))
                pending_comment = ""

    return setting


def _write_siren_setting(sirens_root: ET.Element, setting: SirenSetting) -> None:
    item = ET.SubElement(sirens_root, "Item")
    _set_val(item, "id", setting.id)
    ET.SubElement(item, "name").text = setting.name
    _set_val(item, "timeMultiplier", setting.time_multiplier)
    _set_val(item, "lightFalloffMax", setting.light_falloff_max)
    _set_val(item, "lightFalloffExponent", setting.light_falloff_exponent)
    _set_val(item, "lightInnerConeAngle", setting.light_inner_cone_angle)
    _set_val(item, "lightOuterConeAngle", setting.light_outer_cone_angle)
    _set_val(item, "lightOffset", setting.light_offset)
    ET.SubElement(item, "textureName").text = setting.texture_name
    _set_val(item, "sequencerBpm", setting.sequencer_bpm)
    _write_nested_sequencer(item, "leftHeadLight", setting.left_head_light_sequencer)
    _write_nested_sequencer(item, "rightHeadLight", setting.right_head_light_sequencer)
    _write_nested_sequencer(item, "leftTailLight", setting.left_tail_light_sequencer)
    _write_nested_sequencer(item, "rightTailLight", setting.right_tail_light_sequencer)
    _set_val(item, "leftHeadLightMultiples", setting.left_head_light_multiples)
    _set_val(item, "rightHeadLightMultiples", setting.right_head_light_multiples)
    _set_val(item, "leftTailLightMultiples", setting.left_tail_light_multiples)
    _set_val(item, "rightTailLightMultiples", setting.right_tail_light_multiples)
    _set_val(item, "useRealLights", setting.use_real_lights)

    sirens_el = ET.SubElement(item, "sirens")
    for idx, light in enumerate(setting.lights, start=1):
        _write_light(sirens_el, light, idx)


def import_carcols(path: str) -> CarcolsDocument:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(path, parser=parser)
    root = tree.getroot()

    sirens_root = root.find("Sirens")
    if sirens_root is None:
        raise ValueError(
            "No <Sirens> section found in this file. This tool expects a real "
            "carcols.meta with vehicle siren settings."
        )

    document = CarcolsDocument()

    kits_el = root.find("Kits")
    if kits_el is not None:
        document.raw_kits_element = kits_el

    lights_el = root.find("Lights")
    if lights_el is not None:
        document.raw_lights_element = lights_el

    for item_el in sirens_root.findall("Item"):
        document.siren_settings.append(_parse_siren_setting(item_el))

    return document


def export_carcols(document: CarcolsDocument, path: str) -> None:
    root = ET.Element("CVehicleModelInfoVarGlobal")

    if document.raw_kits_element is not None:
        root.append(document.raw_kits_element)

    if document.raw_lights_element is not None:
        root.append(document.raw_lights_element)

    sirens_root = ET.SubElement(root, "Sirens")
    for setting in document.siren_settings:
        _write_siren_setting(sirens_root, setting)

    _indent(root)
    tree = ET.ElementTree(root)
    tree.write(path, encoding="UTF-8", xml_declaration=True)
