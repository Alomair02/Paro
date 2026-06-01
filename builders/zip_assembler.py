"""ZIP assembler for PPTX packages."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree

from builders.common import make_root, package_path, relationship_target
from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import to_xml_string


class ZIPAssembler:
    """Write generated PPTX parts and relationships into a package."""

    def __init__(
        self,
        content_types: ContentTypeRegistry,
        relationships: RelationshipRegistry,
    ):
        self.content_types = content_types
        self.relationships = relationships

    def assemble(self, output_path: str | Path, parts: dict[str, str | bytes]) -> Path:
        """Assemble a .pptx file and return its path."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        package_parts = dict(parts)
        self._ensure_package_relationships()
        self._ensure_doc_props(package_parts)
        self._ensure_shell_parts(package_parts)

        with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as pptx:
            for part_path, payload in package_parts.items():
                if part_path == package_path("content_types"):
                    continue
                pptx.writestr(part_path, payload)

            for source_part_path in self.relationships.registry:
                rels_xml = self.relationships.render(source_part_path)
                if rels_xml:
                    pptx.writestr(
                        RelationshipRegistry.rels_path(source_part_path),
                        rels_xml,
                    )

            pptx.writestr(package_path("content_types"), self.content_types.render())

        return output_path

    def _ensure_package_relationships(self):
        presentation_path = package_path("presentation")
        self.relationships.add(
            RelationshipRegistry.PACKAGE_ROOT,
            relationship_target(RelationshipRegistry.PACKAGE_ROOT, presentation_path),
            RelationshipRegistry.OFFICE_DOC,
        )
        core_props_path = package_path("core_props")
        self.relationships.add(
            RelationshipRegistry.PACKAGE_ROOT,
            relationship_target(RelationshipRegistry.PACKAGE_ROOT, core_props_path),
            RelationshipRegistry.CORE_PROPERTIES,
        )
        app_props_path = package_path("app_props")
        self.relationships.add(
            RelationshipRegistry.PACKAGE_ROOT,
            relationship_target(RelationshipRegistry.PACKAGE_ROOT, app_props_path),
            RelationshipRegistry.EXTENDED_PROPERTIES,
        )

    def _ensure_doc_props(self, parts: dict[str, str | bytes]):
        core_props_path = package_path("core_props")
        app_props_path = package_path("app_props")

        parts.setdefault(core_props_path, self._make_core_props_xml())
        parts.setdefault(app_props_path, self._make_app_props_xml(self._slide_count(parts)))
        self.content_types.add_override(core_props_path, ContentTypeRegistry.CORE_PROPS)
        self.content_types.add_override(app_props_path, ContentTypeRegistry.APP_PROPS)

    def _ensure_shell_parts(self, parts: dict[str, str | bytes]):
        presentation_path = package_path("presentation")
        shells = [
            (
                package_path("presProps"),
                ContentTypeRegistry.PRES_PROPS,
                RelationshipRegistry.PRES_PROPS,
                self._make_pres_props_xml,
            ),
            (
                package_path("viewProps"),
                ContentTypeRegistry.VIEW_PROPS,
                RelationshipRegistry.VIEW_PROPS,
                self._make_view_props_xml,
            ),
            (
                package_path("tableStyles"),
                ContentTypeRegistry.TABLE_STYLES,
                RelationshipRegistry.TABLE_STYLES,
                self._make_table_styles_xml,
            ),
        ]

        for part_path, content_type, rel_type, factory in shells:
            parts.setdefault(part_path, factory())
            self.content_types.add_override(part_path, content_type)
            self.relationships.add(
                presentation_path,
                relationship_target(presentation_path, part_path),
                rel_type,
            )

    def _make_pres_props_xml(self) -> str:
        root = make_root("p", "presentationPr")
        return to_xml_string(root)

    def _make_view_props_xml(self) -> str:
        root = make_root("p", "viewPr")
        return to_xml_string(root)

    def _make_table_styles_xml(self) -> str:
        root = make_root("a", "tblStyleLst")
        root.set("def", "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}")
        return to_xml_string(root)

    def _make_core_props_xml(self) -> str:
        cp_ns = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
        dc_ns = "http://purl.org/dc/elements/1.1/"
        dcterms_ns = "http://purl.org/dc/terms/"
        dcmitype_ns = "http://purl.org/dc/dcmitype/"
        xsi_ns = "http://www.w3.org/2001/XMLSchema-instance"
        timestamp = "2026-06-01T00:00:00Z"

        root = etree.Element(
            f"{{{cp_ns}}}coreProperties",
            nsmap={
                "cp": cp_ns,
                "dc": dc_ns,
                "dcterms": dcterms_ns,
                "dcmitype": dcmitype_ns,
                "xsi": xsi_ns,
            },
        )
        etree.SubElement(root, f"{{{dc_ns}}}title").text = "Paro Generated Presentation"
        etree.SubElement(root, f"{{{dc_ns}}}creator").text = "Paro PPTX Engine"
        created = etree.SubElement(root, f"{{{dcterms_ns}}}created")
        created.set(f"{{{xsi_ns}}}type", "dcterms:W3CDTF")
        created.text = timestamp
        modified = etree.SubElement(root, f"{{{dcterms_ns}}}modified")
        modified.set(f"{{{xsi_ns}}}type", "dcterms:W3CDTF")
        modified.text = timestamp
        return to_xml_string(root)

    def _make_app_props_xml(self, slide_count: int) -> str:
        app_ns = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
        vt_ns = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"

        root = etree.Element(f"{{{app_ns}}}Properties", nsmap={None: app_ns, "vt": vt_ns})
        etree.SubElement(root, f"{{{app_ns}}}Application").text = "Paro PPTX Engine"
        etree.SubElement(root, f"{{{app_ns}}}Slides").text = str(slide_count)
        return to_xml_string(root)

    def _slide_count(self, parts: dict[str, str | bytes]) -> int:
        slide_dir = "ppt/slides/"
        return sum(
            1
            for part_path in parts
            if part_path.startswith(slide_dir)
            and part_path.endswith(".xml")
            and part_path[len(slide_dir):].startswith("slide")
        )
