"""Builder for ppt/slides/slideN.xml parts."""

from lxml import etree

from builders.common import make_root, make_sp_tree, package_path, relationship_target
from builders.layout_builder import LAYOUT_DEFINITIONS
from builders.shape_emitters import (
    SlideState,
    emit_autoshape,
    emit_image,
    emit_line,
    emit_placeholder_text,
    emit_slide_background,
    emit_table,
    emit_text_box,
)
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import qn, to_xml_string


class SlideBuilder:
    """Build slide parts from ordered shape data."""

    def __init__(
        self,
        content_types: ContentTypeRegistry,
        relationships: RelationshipRegistry,
        media_parts: dict[str, bytes] | None = None,
        media_sources: dict[str, str] | None = None,
    ):
        self.content_types = content_types
        self.relationships = relationships
        self.media_parts = media_parts if media_parts is not None else {}
        self.media_sources = media_sources if media_sources is not None else {}

    def build(self, slide_data: dict, part_path: str | None = None) -> str:
        """Build one slide part and register its layout relationship."""
        part_path = part_path or package_path("slide", slide_data["index"])
        layout_part_path = self._layout_part_path(slide_data)

        self.content_types.add_override(part_path, ContentTypeRegistry.SLIDE)
        self.relationships.add(
            part_path,
            relationship_target(part_path, layout_part_path),
            RelationshipRegistry.SLIDE_LAYOUT,
        )

        slide_state = SlideState(
            part_path=part_path,
            media_parts=self.media_parts,
            media_sources=self.media_sources,
        )
        root = make_root("p", "sld")

        c_sld = etree.SubElement(root, qn("p", "cSld"))
        if slide_data.get("name"):
            c_sld.set("name", slide_data["name"])

        if slide_data.get("background"):
            c_sld.append(
                emit_slide_background(
                    slide_data["background"],
                    slide_state,
                    self.relationships,
                    self.content_types,
                )
            )

        sp_tree = make_sp_tree()
        c_sld.append(sp_tree)

        for shape_data in slide_data.get("shapes", []):
            sp_tree.append(self._emit_shape(shape_data, slide_state))

        clr_map_ovr = etree.SubElement(root, qn("p", "clrMapOvr"))
        etree.SubElement(clr_map_ovr, qn("a", "masterClrMapping"))

        return to_xml_string(root)

    def _layout_part_path(self, slide_data: dict) -> str:
        if slide_data.get("layout_part_path"):
            return slide_data["layout_part_path"]

        layout_name = slide_data.get("layout", "blank")
        return LAYOUT_DEFINITIONS[layout_name]["part_path"]

    def _emit_shape(
        self,
        shape_data: dict,
        slide_state: SlideState,
    ) -> etree._Element:
        shape_type = shape_data["type"]

        if shape_type in ("placeholder", "placeholder_text"):
            return emit_placeholder_text(shape_data, slide_state, self.relationships)
        if shape_type in ("text_box", "textBox"):
            return emit_text_box(shape_data, slide_state, self.relationships)
        if shape_type == "image":
            return emit_image(
                shape_data,
                slide_state,
                self.relationships,
                self.content_types,
            )
        if shape_type in ("autoshape", "shape"):
            return emit_autoshape(shape_data, slide_state, self.relationships)
        if shape_type == "line":
            return emit_line(shape_data, slide_state)
        if shape_type == "table":
            return emit_table(shape_data, slide_state, self.relationships)

        raise ValueError(f"Unsupported shape type: {shape_type}")
