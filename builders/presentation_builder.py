"""Builder for ppt/presentation.xml."""

from lxml import etree

from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import qn, to_xml_string

from builders.common import REFERENCE, make_root, package_path, relationship_target


class PresentationBuilder:
    """Build the deck table-of-contents part."""

    DEFAULT_PART_PATH = package_path("presentation")
    DEFAULT_MASTER_PART_PATH = package_path("slideMaster", 1)

    def __init__(
        self,
        content_types: ContentTypeRegistry,
        relationships: RelationshipRegistry,
    ):
        self.content_types = content_types
        self.relationships = relationships

    def build(
        self,
        slide_part_paths: list[str],
        master_part_path: str = DEFAULT_MASTER_PART_PATH,
        part_path: str = DEFAULT_PART_PATH,
        slide_size: str = "16:9",
    ) -> str:
        """Build presentation.xml after slide parts are known."""
        self.content_types.add_override(part_path, ContentTypeRegistry.PRESENTATION)
        self.relationships.add(
            RelationshipRegistry.PACKAGE_ROOT,
            relationship_target(RelationshipRegistry.PACKAGE_ROOT, part_path),
            RelationshipRegistry.OFFICE_DOC,
        )

        root = make_root("p", "presentation")

        root.append(self._make_slide_master_id_list(part_path, master_part_path))
        root.append(self._make_slide_id_list(part_path, slide_part_paths))
        root.append(self._make_slide_size(slide_size))
        root.append(self._make_notes_size())

        return to_xml_string(root)

    def _make_slide_master_id_list(
        self,
        part_path: str,
        master_part_path: str,
    ) -> etree._Element:
        sld_master_id_lst = etree.Element(qn("p", "sldMasterIdLst"))
        rid = self.relationships.add(
            part_path,
            relationship_target(part_path, master_part_path),
            RelationshipRegistry.SLIDE_MASTER,
        )
        sld_master_id = etree.SubElement(sld_master_id_lst, qn("p", "sldMasterId"))
        sld_master_id.set("id", "2147483648")
        sld_master_id.set(qn("r", "id"), rid)
        return sld_master_id_lst

    def _make_slide_id_list(
        self,
        part_path: str,
        slide_part_paths: list[str],
    ) -> etree._Element:
        sld_id_lst = etree.Element(qn("p", "sldIdLst"))
        slide_id_minimum = REFERENCE["constraints"]["slide_id_minimum"]
        for index, slide_part_path in enumerate(slide_part_paths):
            rid = self.relationships.add(
                part_path,
                relationship_target(part_path, slide_part_path),
                RelationshipRegistry.SLIDE,
            )
            sld_id = etree.SubElement(sld_id_lst, qn("p", "sldId"))
            sld_id.set("id", str(slide_id_minimum + index))
            sld_id.set(qn("r", "id"), rid)
        return sld_id_lst

    def _make_slide_size(self, slide_size: str) -> etree._Element:
        size = REFERENCE["slide_sizes"][slide_size]
        sld_sz = etree.Element(qn("p", "sldSz"))
        sld_sz.set("cx", str(size["cx"]))
        sld_sz.set("cy", str(size["cy"]))
        sld_sz.set("type", size["type"])
        return sld_sz

    def _make_notes_size(self) -> etree._Element:
        notes_size = REFERENCE["notes_size"]
        notes_sz = etree.Element(qn("p", "notesSz"))
        notes_sz.set("cx", str(notes_size["cx"]))
        notes_sz.set("cy", str(notes_size["cy"]))
        return notes_sz
