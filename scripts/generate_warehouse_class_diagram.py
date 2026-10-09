#!/usr/bin/env python3
"""Generate the NeoLab warehouse class-diagram PDF from the reviewed schema.

The PDF is intentionally a readable architectural view. The complete editable
relationship source lives in docs/warehouse_class_diagram.mmd.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "warehouse_database_class_diagram.pdf"
PAGE_W, PAGE_H = landscape(A3)

NAVY = colors.HexColor("#15324B")
BLUE = colors.HexColor("#2D6A8A")
TEAL = colors.HexColor("#2A7F83")
GREEN = colors.HexColor("#4C7A57")
ORANGE = colors.HexColor("#C16A3A")
PURPLE = colors.HexColor("#75558A")
RED = colors.HexColor("#A64B4B")
INK = colors.HexColor("#20313D")
MUTED = colors.HexColor("#60717C")
LIGHT = colors.HexColor("#F4F7F8")
LINE = colors.HexColor("#CBD6DC")
WHITE = colors.white


TABLES = {
    "Provenance": [
        ("dataset_version", "Version, manifeste et empreinte de chaque source"),
        ("ecopart_project_import", "Manifeste d'import EcoPart"),
        ("ecopart_auxiliary_row", "Lignes source metadata/zooplankton"),
    ],
    "EcoTaxa": [
        ("ecotaxa_project", "Projet et inventaire"),
        ("ecotaxa_sample", "Echantillon, temps, position et zone"),
        ("ecotaxa_object", "Objet annote et profondeur"),
    ],
    "UVP / EcoPart": [
        ("uvp_profile", "Profil EcoPart"),
        ("uvp_bin", "Bin vertical et volume echantillonne"),
        ("uvp_particle", "Classe de taille par bin"),
        ("ecopart_bin_source", "Ligne source complete du bin"),
        ("uvp_object_bin", "Affectation objet EcoTaxa vers bin"),
        ("uvp_taxon_abundance", "Abondance UVP derivee"),
    ],
    "CTD": [
        ("ctd_profile", "Profil CTD source"),
        ("ctd_variable", "Catalogue canonique"),
        ("ctd_measurement", "Mesure native par profil"),
    ],
    "FILET": [
        ("filet_sample", "Deploiement et metadonnees"),
        ("filet_sample_net", "Appartenance des filets"),
        ("filet_analysis", "Analyse du sample"),
        ("filet_abundance", "Taxon x stade, valeurs source"),
    ],
    "Liens inter-domaines": [
        ("uvp_ecotaxa", "Profil UVP vers sample EcoTaxa"),
        ("uvp_ctd", "Profil UVP vers profil CTD"),
        ("ecotaxa_ctd", "Sample EcoTaxa vers profil CTD"),
        ("filet_ecotaxa", "Analyse FILET vers sample EcoTaxa"),
        ("filet_ctd", "Sample FILET vers profil CTD"),
        ("filet_uvp_match", "Match station + temps FILET-UVP"),
        ("taxon_mapping", "Correspondance taxonomique versionnee"),
    ],
}


DETAILS = {
    "dataset_version": ["PK id", "source_instance", "dataset_key", "version_key", "file_manifest_uri", "sha256", "UQ source + dataset + version"],
    "ecotaxa_project": ["PK project_id", "FK dataset_version_id", "title", "instrument", "status", "object_count", "source_instance"],
    "ecotaxa_sample": ["PK id", "FK dataset_version_id", "project_id (reference logique)", "sample_id + sample_orig_id", "station_id / cruise_id / profile_id", "ctd_rosette_filename", "lat_avg / lon_avg", "datetime_min / datetime_max", "depth_min / depth_max", "instrument", "marine_zone_*", "comptes annotation", "free_fields_json"],
    "ecotaxa_object": ["PK id", "FK sample_id", "object_id", "acquisition_id / process_id", "category_id / category_name", "annotation_status", "object_datetime", "depth_min_m / depth_max_m", "object_lat / object_lon", "image_uri", "UQ sample + object"],
    "ecopart_project_import": ["PK/FK dataset_version_id", "ecopart_project_id", "ecotaxa_project_ids[]", "manifest_json", "imported_at"],
    "ecopart_auxiliary_row": ["PK/FK dataset_version_id", "PK member_name", "PK row_number", "content_kind", "profile_name", "source_row_json"],
    "uvp_profile": ["PK id", "FK dataset_version_id", "ecotaxa_project_id (logique)", "ecopart_project_id", "ecopart_sample_id", "sample_name", "cruise_key / station_key / cast_key", "marine_zone_*", "sampled_at", "latitude / longitude", "UQ version + projet + sample"],
    "uvp_bin": ["PK id", "FK profile_id", "source_bin_key", "depth_min_m / depth_max_m", "pressure_dbar", "sampled_volume_l > 0", "UQ profil + bin"],
    "uvp_particle": ["PK/FK bin_id", "PK size_class_key", "size_min_um / size_max_um", "size_definition", "particle_count", "observed_volume_m3", "supplied_concentration", "concentration_unit"],
    "ecopart_bin_source": ["PK/FK bin_id", "source_depth_m", "source_row_json"],
    "uvp_object_bin": ["PK/FK ecotaxa_object_id", "PK/FK uvp_bin_id", "depth_delta_m", "mapping_method", "mapping_status"],
    "uvp_taxon_abundance": ["PK/FK dataset_version_id", "FK profile_id", "PK/FK bin_id", "PK taxon_key", "PK annotation_policy", "n_objects_taxon", "sampled_volume_l", "abundance_uvp_ind_m3 (generee)", "calculation_version"],
    "ctd_profile": ["PK id", "FK dataset_version_id", "source_profile_key", "cruise_key / station_key", "sampled_at", "latitude / longitude", "UQ version + profil source"],
    "ctd_variable": ["PK variable_key", "canonical_name", "canonical_unit", "description", "source_code", "source_instance", "UQ source + code"],
    "ctd_measurement": ["PK/FK profile_id", "PK source_row_key", "scan_key", "depth_m / pressure_dbar", "FK variable_key", "variable_definition", "sensor_channel", "value / unit / qc"],
    "filet_sample": ["PK id", "FK dataset_version_id", "sample_id / deployment_id", "sampling_year / platform", "station_name / cast_number", "debut / fin de deploiement", "latitude / longitude", "marine_zone_*", "gear / tow_type", "profondeurs min/max", "net_mesh_size", "volumes depth et flowmeter", "number_of_nets / sample_nets", "net_sampling_ids", "subsampling_quantity / unit", "UQ version + sample"],
    "filet_sample_net": ["PK/FK sample_ref", "PK net_sampling_id"],
    "filet_analysis": ["PK id", "FK composite sample_ref + version + sample_id", "analysis_id", "analysis_type / contract", "analysis_datetime", "analysis_protocol_id", "UQ version + sample + analyse"],
    "filet_abundance": ["PK/FK dataset_version_id", "source_row_number", "PK/FK sample_id + analysis_id", "PK taxon_id + stage", "is_aggregate (generee)", "sample_abundance", "abondances depth / flowmeter", "biomasses depth / flowmeter", "FK metadata_dataset_version_id nullable", "UQ version + ligne + stade"],
    "uvp_ecotaxa": ["PK/FK uvp_profile_id", "PK/FK ecotaxa_sample_id", "source_evidence"],
    "uvp_ctd": ["PK/FK uvp_profile_id", "PK/FK ctd_profile_id", "source_evidence"],
    "ecotaxa_ctd": ["PK/FK ecotaxa_sample_id", "PK/FK ctd_profile_id", "relation_type", "filename_match / station_match", "distance_km / time_gap_minutes", "match_status", "evidence"],
    "filet_ecotaxa": ["PK/FK filet_analysis_id", "PK/FK ecotaxa_sample_id", "source_evidence"],
    "filet_ctd": ["PK/FK filet_sample_id", "PK/FK ctd_profile_id", "source_evidence"],
    "filet_uvp_match": ["PK id", "FK dataset_version_id", "station_id", "FK filet_sample_id", "FK filet_analysis_id nullable", "FK uvp_profile_id", "filet_sampled_at / uvp_sampled_at", "time_gap_hours", "match_status / match_method", "evidence", "UQ version + FILET + UVP"],
    "taxon_mapping": ["PK filet_taxon_id", "PK uvp_taxon_id", "PK mapping_version", "mapping_relation", "mapping_status", "evidence", "References taxons logiques, sans FK SQL"],
}

VIEWS = [
    "explore.uvp_ctd", "explore.uvp_projects", "explore.uvp_samples",
    "explore.uvp_objects", "explore.uvp_taxon_abundance",
    "explore.ecopart_bins", "explore.ecopart_source_metadata",
    "explore.ecopart_supplied_zooplankton", "explore.filet_data",
    "explore.filet_totals", "explore.filet_samples", "explore.filet_ctd",
    "explore.ecotaxa_ctd_profile", "explore.ecotaxa_ctd",
    "explore.filet_uvp_matches", "explore.filet_uvp_abundance",
]


def footer(pdf: canvas.Canvas, page: int) -> None:
    pdf.setStrokeColor(LINE)
    pdf.line(35, 26, PAGE_W - 35, 26)
    pdf.setFont("Helvetica", 7.5)
    pdf.setFillColor(MUTED)
    pdf.drawString(35, 13, "IDEA NeoLab - schema logique consolide du depot - 7 octobre 2026")
    pdf.drawRightString(PAGE_W - 35, 13, f"Page {page}")


def header(pdf: canvas.Canvas, title: str, subtitle: str, page: int) -> None:
    pdf.setFillColor(NAVY)
    pdf.rect(0, PAGE_H - 66, PAGE_W, 66, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(35, PAGE_H - 31, title)
    pdf.setFont("Helvetica", 9.5)
    pdf.drawString(35, PAGE_H - 49, subtitle)
    footer(pdf, page)


def wrapped_lines(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def rounded_panel(pdf: canvas.Canvas, x: float, y: float, w: float, h: float,
                  title: str, items: list[tuple[str, str]], color: colors.Color) -> None:
    pdf.setFillColor(colors.white)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(x, y, w, h, 8, fill=1, stroke=1)
    pdf.setFillColor(color)
    pdf.roundRect(x, y + h - 31, w, 31, 8, fill=1, stroke=0)
    pdf.rect(x, y + h - 31, w, 8, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(x + 12, y + h - 20, title)
    cursor = y + h - 49
    for name, note in items:
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica-Bold", 8.2)
        pdf.drawString(x + 12, cursor, name)
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 7.1)
        for line in wrapped_lines(note, "Helvetica", 7.1, w - 25):
            cursor -= 9
            pdf.drawString(x + 12, cursor, line)
        cursor -= 10


def arrow(pdf: canvas.Canvas, x1: float, y1: float, x2: float, y2: float,
          label: str = "") -> None:
    pdf.setStrokeColor(BLUE)
    pdf.setLineWidth(1.2)
    pdf.line(x1, y1, x2, y2)
    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    tip = 7
    pdf.line(x2, y2, x2 - ux * tip + px * 3, y2 - uy * tip + py * 3)
    pdf.line(x2, y2, x2 - ux * tip - px * 3, y2 - uy * tip - py * 3)
    if label:
        pdf.setFont("Helvetica", 7)
        pdf.setFillColor(MUTED)
        pdf.drawCentredString((x1 + x2) / 2, (y1 + y2) / 2 + 5, label)


def overview(pdf: canvas.Canvas, page: int) -> None:
    header(pdf, "Warehouse NeoLab - diagramme de classes", "Vue globale des 26 tables persistantes et des flux de relation", page)
    x_gap, y_gap = 18, 18
    left = 35
    top = PAGE_H - 90
    col_w = (PAGE_W - 70 - 3 * x_gap) / 4
    provenance_h = 175
    domain_h = 254
    link_h = 225
    rounded_panel(pdf, left, top - provenance_h, col_w, provenance_h, "PROVENANCE", TABLES["Provenance"], PURPLE)
    rounded_panel(pdf, left + col_w + x_gap, top - domain_h, col_w, domain_h, "ECOTAXA", TABLES["EcoTaxa"], BLUE)
    rounded_panel(pdf, left + 2 * (col_w + x_gap), top - domain_h, col_w, domain_h, "UVP / ECOPART", TABLES["UVP / EcoPart"], TEAL)
    rounded_panel(pdf, left + 3 * (col_w + x_gap), top - domain_h, col_w, domain_h, "CTD", TABLES["CTD"], GREEN)
    filet_y = 55
    rounded_panel(pdf, left, filet_y, col_w, link_h, "FILET", TABLES["FILET"], ORANGE)
    rounded_panel(pdf, left + col_w + x_gap, filet_y, 3 * col_w + 2 * x_gap, link_h, "LIENS INTER-DOMAINES", TABLES["Liens inter-domaines"], RED)
    # Relations de famille. Les relations FK exactes sont detaillees aux pages suivantes.
    pdf.setFillColor(LIGHT)
    pdf.roundRect(left, top - provenance_h - 46, col_w, 30, 5, fill=1, stroke=0)
    pdf.setFillColor(PURPLE)
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawCentredString(left + col_w / 2, top - provenance_h - 34, "dataset_version versionne chaque domaine")
    arrow(pdf, left + col_w / 2, top - provenance_h, left + col_w / 2, filet_y + link_h, "versionne")
    arrow(pdf, left + 2 * (col_w + x_gap) + col_w, top - domain_h / 2, left + 3 * (col_w + x_gap), top - domain_h / 2, "mesures")
    arrow(pdf, left + col_w + x_gap + col_w / 2, top - domain_h, left + col_w + x_gap + col_w / 2, filet_y + link_h, "liaisons")
    arrow(pdf, left + 2 * (col_w + x_gap) + col_w / 2, top - domain_h, left + 2 * (col_w + x_gap) + col_w / 2, filet_y + link_h, "liaisons")
    arrow(pdf, left + 3 * (col_w + x_gap) + col_w / 2, top - domain_h, left + 3 * (col_w + x_gap) + col_w / 2, filet_y + link_h, "liaisons")
    pdf.setFont("Helvetica-Oblique", 8)
    pdf.setFillColor(MUTED)
    pdf.drawString(35, 35, "Les vues explore.* sont une surface de lecture, pas des classes persistantes; elles sont inventoriees en fin de document.")
    pdf.showPage()


def entity_card(pdf: canvas.Canvas, x: float, y: float, w: float, h: float,
                name: str, fields: list[str], color: colors.Color) -> None:
    pdf.setFillColor(WHITE)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(x, y, w, h, 7, fill=1, stroke=1)
    pdf.setFillColor(color)
    pdf.roundRect(x, y + h - 28, w, 28, 7, fill=1, stroke=0)
    pdf.rect(x, y + h - 28, w, 7, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(x + 10, y + h - 18, name)
    cursor = y + h - 43
    for field in fields:
        key = field.startswith("PK") or field.startswith("FK")
        pdf.setFillColor(NAVY if key else INK)
        pdf.setFont("Helvetica-Bold" if key else "Helvetica", 7.7)
        for line in wrapped_lines(field, "Helvetica-Bold" if key else "Helvetica", 7.7, w - 26):
            pdf.drawString(x + 16, cursor, line)
            cursor -= 10
        pdf.setFillColor(color)
        pdf.circle(x + 9, cursor + 8, 1.6, fill=1, stroke=0)
        cursor -= 1
        if cursor < y + 10:
            pdf.setFillColor(MUTED)
            pdf.setFont("Helvetica-Oblique", 7)
            pdf.drawString(x + 12, y + 7, "Voir le DDL pour la liste complete")
            break


def catalog_page(pdf: canvas.Canvas, page: int, title: str, subtitle: str,
                 names: list[str], color: colors.Color, columns: int = 3) -> None:
    header(pdf, title, subtitle, page)
    rows = (len(names) + columns - 1) // columns
    gap_x, gap_y = 16, 16
    margin_x, bottom, top = 35, 45, PAGE_H - 82
    card_w = (PAGE_W - 2 * margin_x - (columns - 1) * gap_x) / columns
    card_h = (top - bottom - (rows - 1) * gap_y) / rows
    for idx, name in enumerate(names):
        row, col = divmod(idx, columns)
        x = margin_x + col * (card_w + gap_x)
        y = top - (row + 1) * card_h - row * gap_y
        entity_card(pdf, x, y, card_w, card_h, name, DETAILS[name], color)
    pdf.showPage()


def relation_map_page(pdf: canvas.Canvas, page: int) -> None:
    header(pdf, "Carte des relations inter-domaines", "Sens des rapprochements materialises dans les tables d'association", page)
    nodes = {
        "EcoTaxa sample": (95, 610, BLUE),
        "UVP profile": (425, 610, TEAL),
        "CTD profile": (755, 610, GREEN),
        "FILET sample": (95, 335, ORANGE),
        "FILET analysis": (425, 335, ORANGE),
        "Taxons": (755, 335, PURPLE),
    }
    for label, (x, y, color) in nodes.items():
        pdf.setFillColor(color)
        pdf.roundRect(x, y, 225, 54, 7, fill=1, stroke=0)
        pdf.setFillColor(WHITE)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawCentredString(x + 112.5, y + 21, label)

    arrow(pdf, 320, 637, 425, 637, "uvp_ecotaxa")
    arrow(pdf, 650, 637, 755, 637, "uvp_ctd")
    arrow(pdf, 320, 362, 425, 362, "analyse")
    arrow(pdf, 650, 362, 755, 362, "taxon_mapping")
    arrow(pdf, 320, 389, 867, 610, "filet_ctd")
    arrow(pdf, 537, 389, 207, 610, "filet_ecotaxa")
    arrow(pdf, 537, 389, 537, 610, "filet_uvp_match")
    arrow(pdf, 207, 664, 867, 664, "ecotaxa_ctd")

    pdf.setFillColor(LIGHT)
    pdf.roundRect(95, 80, 990, 165, 7, fill=1, stroke=0)
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(112, 218, "Regles de lecture")
    bullets = [
        "Les tables de liaison conservent la preuve, le statut ou la methode d'appariement.",
        "filet_uvp_match materialise une correspondance station + fenetre temporelle; ce n'est pas une equivalence biologique.",
        "taxon_mapping relie des identifiants logiques sans contrainte FK vers les tables d'abondance.",
        "Les relations pointillees dans la source Mermaid sont logiques et non imposees par PostgreSQL.",
    ]
    cursor = 196
    for bullet in bullets:
        pdf.setFillColor(RED)
        pdf.circle(118, cursor + 2, 2, fill=1, stroke=0)
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica", 9)
        for line in wrapped_lines(bullet, "Helvetica", 9, 935):
            pdf.drawString(130, cursor, line)
            cursor -= 13
        cursor -= 5
    pdf.showPage()


def views_page(pdf: canvas.Canvas, page: int) -> None:
    header(pdf, "Surface de lecture explore.*", "Vues SQL destinees a IDEA; elles ne stockent pas de lignes propres", page)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.setFillColor(NAVY)
    pdf.drawString(35, PAGE_H - 100, "Vues consolidees")
    col_w = (PAGE_W - 90) / 2
    for idx, view in enumerate(VIEWS):
        col = 0 if idx < 8 else 1
        row = idx if idx < 8 else idx - 8
        x = 45 + col * (col_w + 20)
        y = PAGE_H - 135 - row * 42
        pdf.setFillColor(LIGHT)
        pdf.roundRect(x, y - 22, col_w, 30, 5, fill=1, stroke=0)
        pdf.setFillColor(BLUE)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(x + 12, y - 10, view)

    pdf.setFillColor(LIGHT)
    pdf.roundRect(35, 80, PAGE_W - 70, 205, 8, fill=1, stroke=0)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(52, 257, "Legende et limites")
    notes = [
        "PK = cle primaire; FK = cle etrangere SQL; UQ = contrainte unique.",
        "Les colonnes marine_zone_* conservent la cle, le nom, la source, la version et le statut d'affectation.",
        "Les abondances UVP sont derivees des objets EcoTaxa et du volume EcoPart; les abondances FILET restent des valeurs source.",
        "Le diagramme couvre 26 tables et leurs relations declarees. Les cartes de colonnes sont synthetiques; le DDL reste la reference detaillee.",
        "Source: docs/warehouse_schema_proposal.sql + migrations EcoPart et zones FILET.",
        "Limite de preuve: PostgreSQL n'etait pas actif pendant cette generation; aucune introspection live n'a ete executee.",
    ]
    cursor = 232
    for note in notes:
        pdf.setFillColor(TEAL)
        pdf.circle(58, cursor + 2, 2, fill=1, stroke=0)
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica", 9.2)
        for line in wrapped_lines(note, "Helvetica", 9.2, PAGE_W - 130):
            pdf.drawString(70, cursor, line)
            cursor -= 14
        cursor -= 4
    pdf.showPage()


def generate() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=landscape(A3))
    pdf.setTitle("Diagramme de classes - Warehouse NeoLab")
    pdf.setAuthor("IDEA NeoLab")
    pdf.setSubject("Schema logique consolide des tables warehouse et des vues explore")
    overview(pdf, 1)
    catalog_page(pdf, 2, "Provenance et EcoTaxa", "Tables sources, projets, samples et objets", [
        "dataset_version", "ecotaxa_project", "ecotaxa_sample", "ecotaxa_object",
        "ecopart_project_import", "ecopart_auxiliary_row",
    ], BLUE)
    catalog_page(pdf, 3, "UVP et EcoPart", "Profils, bins, particules, objets et abondances derivees", [
        "uvp_profile", "uvp_bin", "uvp_particle", "ecopart_bin_source",
        "uvp_object_bin", "uvp_taxon_abundance",
    ], TEAL)
    catalog_page(pdf, 4, "CTD et FILET", "Mesures CTD et chaine sample - analyse - abondance FILET", [
        "ctd_profile", "ctd_variable", "ctd_measurement", "filet_sample",
        "filet_sample_net", "filet_analysis", "filet_abundance",
    ], ORANGE, columns=4)
    catalog_page(pdf, 5, "Tables de relations inter-domaines", "Associations explicites, preuves et statuts de correspondance", [
        "uvp_ecotaxa", "uvp_ctd", "ecotaxa_ctd", "filet_ecotaxa",
        "filet_ctd", "filet_uvp_match", "taxon_mapping",
    ], RED, columns=4)
    relation_map_page(pdf, 6)
    views_page(pdf, 7)
    pdf.save()
    return OUTPUT


if __name__ == "__main__":
    print(generate())
