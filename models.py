"""
Pydantic models for all FreeCAD Tool Server inputs and outputs.

Design rule: every tool response carries success/message/data/warnings/errors
so agents always have a consistent envelope to parse.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from typing import Literal
from pydantic import BaseModel, Field, field_validator
import re


# ---------------------------------------------------------------------------
# Shared response envelope
# ---------------------------------------------------------------------------

class ToolResponse(BaseModel):
    """Standard envelope returned by every tool endpoint."""
    success: bool
    message: str
    data: Optional[dict[str, Any]] = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")

class CreateDocumentRequest(BaseModel):
    name: str = Field(
        default="Model",
        description=(
            "Alphanumeric name for the FreeCAD document. "
            "Must start with a letter or underscore. Max 64 chars."
        ),
        min_length=1,
        max_length=64,
    )

    @field_validator("name")
    @classmethod
    def name_is_valid_identifier(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(
                f"Document name '{v}' is invalid. "
                "Use only letters, digits, underscores, or hyphens; start with a letter or underscore."
            )
        return v


class DocumentInfo(BaseModel):
    session_id: str
    document_name: str
    created_at: datetime
    shape_count: int = 0


# ---------------------------------------------------------------------------
# Shapes — inputs
# ---------------------------------------------------------------------------

class AddBoxRequest(BaseModel):
    name: str = Field(
        description=(
            "Unique label for this box within the document. "
            "Use descriptive names like 'base_plate' or 'mounting_block'."
        ),
        min_length=1,
        max_length=64,
    )
    length: float = Field(gt=0, description="Dimension along X axis (mm).")
    width: float = Field(gt=0, description="Dimension along Y axis (mm).")
    height: float = Field(gt=0, description="Dimension along Z axis (mm).")
    x: float = Field(default=0.0, description="X coordinate of the box origin (mm).")
    y: float = Field(default=0.0, description="Y coordinate of the box origin (mm).")
    z: float = Field(default=0.0, description="Z coordinate of the box origin (mm).")
    rotation_z: float = Field(
        default=0.0,
        description=(
            "Rotation of the box around its Z axis in degrees (0–360). "
            "The box rotates about the point (x, y, z). "
            "Useful for creating angled cutting tools for non-axis-aligned features."
        ),
    )

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"Shape name '{v}' must match [A-Za-z_][A-Za-z0-9_\\-]*")
        return v


class AddCylinderRequest(BaseModel):
    name: str = Field(
        description=(
            "Unique label for this cylinder within the document. "
            "Use descriptive names like 'shaft' or 'hole_plug'."
        ),
        min_length=1,
        max_length=64,
    )
    radius: float = Field(gt=0, description="Radius of the cylinder (mm).")
    height: float = Field(gt=0, description="Height (length) of the cylinder (mm).")
    x: float = Field(default=0.0, description="X coordinate of cylinder base-center (mm).")
    y: float = Field(default=0.0, description="Y coordinate of cylinder base-center (mm).")
    z: float = Field(default=0.0, description="Z coordinate of cylinder base-center (mm).")

    axis: Literal["x", "y", "z"] = Field(
        default="z",
        description=(
            "Axis along which the cylinder extends:\n"
            "  z — upright cylinder (default)\n"
            "  x — horizontal cylinder pointing in X direction\n"
            "  y — horizontal cylinder pointing in Y direction\n"
            "Position (x, y, z) is the center of the base face."
        ),
    )

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"Shape name '{v}' must match [A-Za-z_][A-Za-z0-9_\\-]*")
        return v


class AddConeRequest(BaseModel):
    name: str = Field(description="Unique label for this cone/frustum.")
    radius1: float = Field(gt=0, description="Radius at the base (start of cone along axis) in mm.")
    radius2: float = Field(ge=0, description="Radius at the top (end of cone along axis) in mm. Set to 0 for a point-tip cone.")
    height: float = Field(gt=0, description="Height (length) of the cone along the chosen axis in mm.")
    x: float = Field(default=0.0, description="X coordinate of the cone base center (mm).")
    y: float = Field(default=0.0, description="Y coordinate of the cone base center (mm).")
    z: float = Field(default=0.0, description="Z coordinate of the cone base center (mm).")
    axis: Literal["x", "y", "z"] = Field(default="z", description="Axis the cone extends along.")

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"Shape name '{v}' must match [A-Za-z_][A-Za-z0-9_\\-]*")
        return v


class AddWingRequest(BaseModel):
    """Generate a tapered wing half using NACA 4-digit airfoil loft."""
    name: str = Field(description="Unique label for this wing half.", min_length=1, max_length=64)
    root_chord: float = Field(gt=0, description="Chord length at root (mm).")
    tip_chord: float = Field(gt=0, description="Chord length at tip (mm).")
    half_span: float = Field(gt=0, description="Span from root to tip (mm). Wing extends in +Y.")
    thickness_ratio: float = Field(
        default=0.12, gt=0.04, le=0.30,
        description="Max thickness as fraction of chord (e.g. 0.12 = NACA **12). Default 0.12.",
    )
    naca_camber: float = Field(
        default=0.02, ge=0.0, le=0.10,
        description="Max camber as fraction of chord (e.g. 0.02 = NACA 2***). 0 = symmetric.",
    )
    naca_camber_pos: float = Field(
        default=0.40, gt=0.0, lt=1.0,
        description="Position of max camber as fraction of chord (e.g. 0.4 = NACA *4**). Ignored if camber=0.",
    )
    x: float = Field(default=0.0, description="X coordinate of root leading edge (mm).")
    y: float = Field(default=0.0, description="Y coordinate of root (mm). Wing extends to y+half_span.")
    z: float = Field(default=0.0, description="Z coordinate of root airfoil center (mm).")
    sweep_le: float = Field(default=0.0, description="Leading-edge sweep angle in degrees (positive = aft).")
    dihedral: float = Field(default=0.0, description="Dihedral angle in degrees (positive = tip raised). Ignored when span_axis='z'.")
    span_axis: Literal["y", "z"] = Field(
        default="y",
        description=(
            "Direction the wing/fin spans:\n"
            "  y (default) — horizontal wing, chord along X, thickness along Z, span toward +Y\n"
            "  z — vertical fin, chord along X, thickness along Y, span toward +Z\n"
            "For a vertical stabilizer use span_axis='z' with y=0 (centered) and z=fuselage_top."
        ),
    )

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"Shape name '{v}' must match [A-Za-z_][A-Za-z0-9_\\-]*")
        return v


class MirrorShapeRequest(BaseModel):
    source_shape: str = Field(description="Name of the shape to mirror.")

    @field_validator("plane", mode="before")
    @classmethod
    def plane_lowercase(cls, v):
        return v.lower() if isinstance(v, str) else v

    plane: Literal["xy", "xz", "yz"] = Field(
        description=(
            "Mirror plane through the origin:\n"
            "  xy — mirror across Z=0 (flips Z coordinates)\n"
            "  xz — mirror across Y=0 (flips Y coordinates)\n"
            "  yz — mirror across X=0 (flips X coordinates)\n"
            "Typical use: build one half of a symmetric part, mirror it, then boolean_union both halves."
        )
    )
    result_name: str = Field(description="Name for the mirrored copy.")
    keep_original: bool = Field(
        default=True,
        description=(
            "If true (default), the source shape is kept in the document alongside the mirror. "
            "If false, the source is consumed (useful when you only need the mirrored version)."
        ),
    )


class ChamferEdgesRequest(BaseModel):
    target_shape: str = Field(description="Name of the shape to chamfer.")
    size: float = Field(gt=0, description="Chamfer size (cut distance) in mm.")
    edge_selector: Literal["all", "all_vertical", "top", "bottom"] = Field(
        default="top",
        description="Which edges to chamfer — same semantics as fillet_edges.",
    )
    result_name: str = Field(description="Name for the result. May equal target_shape.")


# ---------------------------------------------------------------------------
# Shapes — outputs
# ---------------------------------------------------------------------------

class ShapeInfo(BaseModel):
    name: str
    shape_type: str                        # "Box" | "Cylinder" | "Cut" | "Union" | "Fillet" | "Pattern"
    volume_mm3: float
    surface_area_mm2: float
    face_count: Optional[int] = None
    edge_count: Optional[int] = None
    position: dict[str, float]            # {"x": ..., "y": ..., "z": ...}
    dimensions: dict[str, Any]            # shape-specific keys (values may be float or str)


class GetShapeInfoRequest(BaseModel):
    shape_name: str = Field(min_length=1, max_length=64, description="Name of the shape to inspect.")


# ---------------------------------------------------------------------------
# Bounding box
# ---------------------------------------------------------------------------

class BoundingBoxResult(BaseModel):
    x_min: float
    y_min: float
    z_min: float
    x_max: float
    y_max: float
    z_max: float
    x_size: float
    y_size: float
    z_size: float
    diagonal_mm: float
    shape_count: int
    shape_names: list[str]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class ExportStepRequest(BaseModel):
    output_path: str = Field(
        description=(
            "Absolute path for the output .step file. "
            "The directory must already exist. "
            "Example: 'C:/Users/me/models/part.step'"
        )
    )
    shape_name: str | None = Field(
        default=None,
        description=(
            "Name of the single shape to export. STRONGLY RECOMMENDED: pass the final "
            "part's name so leftover construction solids (cutters, witnesses) are not "
            "included in the STEP file. If omitted, ALL shapes in the document are "
            "exported, which usually causes solid_count > 1 in validation."
        ),
    )

    @field_validator("output_path")
    @classmethod
    def path_ends_with_step(cls, v: str) -> str:
        if not v.lower().endswith((".step", ".stp")):
            raise ValueError("output_path must end with .step or .stp")
        return v


# ---------------------------------------------------------------------------
# Boolean operations
# ---------------------------------------------------------------------------

class LinearPatternRequest(BaseModel):
    """Repeat a shape in a line and union all instances."""
    source_shape: str = Field(description="Name of the shape to pattern. Will be consumed.")
    direction: Literal["x", "y", "z"] = Field(description="Axis along which to repeat.")
    count: int = Field(ge=2, le=50, description="Total number of instances (including the original).")
    spacing: float = Field(gt=0, description="Distance between instance origins (mm).")
    result_name: str = Field(description="Name for the resulting unioned pattern body.")


class BooleanUnionRequest(BaseModel):
    shape_a: str = Field(
        description="Name of the first shape to merge. Will be consumed by the operation."
    )
    shape_b: str = Field(
        description="Name of the second shape to merge. Will be consumed by the operation."
    )
    result_name: str = Field(
        description=(
            "Name for the resulting unified solid. "
            "The two input shapes must touch or overlap for a clean union. "
            "May equal shape_a or shape_b to update in place."
        )
    )


class BooleanCutRequest(BaseModel):
    target_shape: str = Field(
        description=(
            "Name of the shape to cut FROM (the base body). "
            "This shape will be consumed and replaced by result_name."
        )
    )
    tool_shape: str = Field(
        description=(
            "Name of the shape to cut WITH (the tool body that becomes the void). "
            "This shape will be removed after the cut."
        )
    )
    result_name: str = Field(
        description=(
            "Name for the resulting shape after the cut. "
            "May be the same as target_shape to update in place."
        )
    )


class MakeHoleRequest(BaseModel):
    target_shape: str = Field(
        description=(
            "Name of the solid shape to drill the hole into. "
            "The original shape is replaced by the result."
        )
    )
    diameter: float = Field(
        gt=0,
        description="Diameter of the hole in mm.",
    )
    depth: Optional[float] = Field(
        default=None,
        description=(
            "Depth of the hole in mm along +Z from the entry point. "
            "Pass null (or omit) to drill completely through the target shape."
        ),
    )
    x: float = Field(description="X coordinate of the hole center at the entry face (mm).")
    y: float = Field(description="Y coordinate of the hole center at the entry face (mm).")
    z: float = Field(
        default=0.0,
        description=(
            "Z coordinate where the hole starts (mm). "
            "For a through-hole in a flat plate sitting on Z=0, use z=0."
        ),
    )
    axis: Literal["x", "y", "z"] = Field(
        default="z",
        description=(
            "Direction the hole is drilled:\n"
            "  z — vertically through a flat plate (default)\n"
            "  x — horizontally through a wall or vertical plate\n"
            "  y — through-depth for front-to-back holes\n"
            "The position (x,y,z) is the center of the hole at the entry face."
        ),
    )
    result_name: str = Field(
        description=(
            "Name for the resulting shape. "
            "Set equal to target_shape to update the shape in place."
        )
    )

    @field_validator("diameter")
    @classmethod
    def diameter_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("diameter must be > 0")
        return v


class FilletEdgesRequest(BaseModel):
    target_shape: str = Field(
        description="Name of the shape whose edges will be filleted."
    )
    radius: float = Field(
        gt=0,
        description=(
            "Fillet radius in mm. Must be smaller than the thinnest wall adjacent "
            "to the selected edges, or the operation will fail."
        ),
    )
    edge_selector: Literal["all", "all_vertical", "top", "bottom"] = Field(
        default="all_vertical",
        description=(
            "Which edges to fillet:\n"
            "  all_vertical — edges parallel to the Z axis (most common for rounded corners)\n"
            "  all          — every edge on the shape\n"
            "  top          — edges on the topmost face\n"
            "  bottom       — edges on the bottommost face"
        ),
    )
    result_name: str = Field(
        description=(
            "Name for the resulting shape. "
            "Set equal to target_shape to update in place."
        )
    )


# ---------------------------------------------------------------------------
# Wire / sweep API
# ---------------------------------------------------------------------------

class RevolveProfileRequest(BaseModel):
    name: str = Field(description="Unique name for the resulting solid.")
    profile: list[list[float]] = Field(
        description=(
            "List of [radius, z_position] pairs tracing the outer cross-section profile. "
            "All radius values must be ≥ 0. The profile is revolved 360° around the Z axis. "
            "The axis closing line (r=0) is added automatically — do not include it unless "
            "you want explicit control over the axis endpoints. "
            "Example (stepped shaft): [[4.5,0],[4.5,25],[5.5,25],[5.5,145],[4.5,145],[4.5,170]]"
        ),
        min_length=2,
    )
    x: float = Field(default=0.0, description="X offset of the revolution axis (mm).")
    y: float = Field(default=0.0, description="Y offset of the revolution axis (mm).")
    z: float = Field(default=0.0, description="Z translation applied to all profile points (mm).")

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"Shape name '{v}' must match [A-Za-z_][A-Za-z0-9_\\-]*")
        return v


class PolarPatternRequest(BaseModel):
    source_shape: str = Field(description="Name of the shape to pattern. Will be consumed.")
    count: int = Field(ge=2, le=360, description="Number of instances (including the original).")
    axis: Literal["x", "y", "z"] = Field(
        default="z",
        description="Axis to rotate around (through the origin). Usually 'z' for spoke holes.",
    )
    result_name: str = Field(description="Name for the resulting unioned pattern body.")


class ExtrudePolygonRequest(BaseModel):
    name: str = Field(description="Unique name for the resulting solid.")
    points: list[list[float]] = Field(
        description=(
            "List of 2D [a, b] point pairs defining the polygon boundary. "
            "For axis='z': [x, y] pairs in the XY plane. "
            "For axis='x': [y, z] pairs in the YZ plane. "
            "For axis='y': [x, z] pairs in the XZ plane. "
            "Minimum 3 points. Does not need to repeat the first point to close."
        ),
        min_length=3,
    )
    height: float = Field(gt=0, description="Extrusion height/depth in mm along the chosen axis.")
    axis: Literal["x", "y", "z"] = Field(
        default="z",
        description="Axis along which to extrude. Points are defined in the perpendicular plane.",
    )
    x: float = Field(default=0.0, description="X offset of the polygon origin (mm).")
    y: float = Field(default=0.0, description="Y offset of the polygon origin (mm).")
    z: float = Field(default=0.0, description="Z offset of the polygon origin (mm).")

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"Shape name '{v}' must match [A-Za-z_][A-Za-z0-9_\\-]*")
        return v


class CreateArcPathRequest(BaseModel):
    name: str = Field(description="Unique name for this path wire.")
    start: list[float] = Field(
        description="Start point [x, y, z] in mm.",
        min_length=3, max_length=3,
    )
    mid: list[float] = Field(
        description="Midpoint on the arc [x, y, z] in mm — controls curvature.",
        min_length=3, max_length=3,
    )
    end: list[float] = Field(
        description="End point [x, y, z] in mm.",
        min_length=3, max_length=3,
    )


class CreateRectProfileRequest(BaseModel):
    name: str = Field(description="Unique name for this profile wire.")
    width: float = Field(gt=0, description="Width of the rectangle in mm (Y direction).")
    height: float = Field(gt=0, description="Height of the rectangle in mm (Z direction).")
    corner_radius: float = Field(
        default=0.0,
        ge=0,
        description="Corner fillet radius in mm. 0 = sharp corners.",
    )


class SweepRequest(BaseModel):
    profile_name: str = Field(description="Name of the profile wire to sweep.")
    path_name: str = Field(description="Name of the arc/path wire to sweep along.")
    result_name: str = Field(description="Name for the resulting solid shape.")


# ---------------------------------------------------------------------------
# Solid validation
# ---------------------------------------------------------------------------

class AssemblyPartEntry(BaseModel):
    step_path: str = Field(description="Absolute path to an existing .step or .stp file.")
    name: str = Field(
        description="Label for this body in the assembly (shown in CAD tree). Use only letters, digits, underscores, hyphens.",
        min_length=1, max_length=64,
    )
    x: float = Field(default=0.0, description="X translation offset in mm.")
    y: float = Field(default=0.0, description="Y translation offset in mm.")
    z: float = Field(default=0.0, description="Z translation offset in mm.")
    rx: float = Field(default=0.0, description="Rotation around X axis in degrees (applied before ry/rz).")
    ry: float = Field(default=0.0, description="Rotation around Y axis in degrees (applied after rx, before rz).")
    rz: float = Field(default=0.0, description="Rotation around Z axis in degrees (applied last).")

    @field_validator("step_path")
    @classmethod
    def path_valid(cls, v: str) -> str:
        if not v.lower().endswith((".step", ".stp")):
            raise ValueError("step_path must end with .step or .stp")
        return v


class ExportAssemblyRequest(BaseModel):
    parts: list[AssemblyPartEntry] = Field(
        min_length=2,
        description=(
            "List of parts to combine. Each entry specifies a STEP file, a display name, "
            "and an optional (x, y, z) translation offset to position it in the assembly. "
            "Minimum 2 parts."
        ),
    )
    output_path: str = Field(
        description=(
            "Absolute path for the output assembly .step file. "
            "Example: 'C:/Users/me/models/hub_assembly.step'"
        )
    )

    @field_validator("output_path")
    @classmethod
    def output_valid(cls, v: str) -> str:
        if not v.lower().endswith((".step", ".stp")):
            raise ValueError("output_path must end with .step or .stp")
        return v


class ValidateStepRequest(BaseModel):
    step_path: str = Field(description="Absolute path to the .step file to validate.")

    @field_validator("step_path")
    @classmethod
    def path_ends_with_step(cls, v: str) -> str:
        if not v.lower().endswith((".step", ".stp")):
            raise ValueError("step_path must end with .step or .stp")
        return v


class SolidValidationResult(BaseModel):
    """Structured report from a BRep solid inspection."""
    is_clean: bool
    summary: str
    checks: dict[str, Any]
    issues: list[str]
    warnings: list[str]


class ScreenshotRequest(BaseModel):
    shape_name: str = Field(
        default="",
        description="Name of the shape to render. Leave empty to render all shapes.",
    )
    view: Literal["iso", "front", "back", "top", "bottom", "right", "left"] = Field(
        default="iso",
        description="Camera angle preset.",
    )
    width: int = Field(default=800, ge=200, le=3840, description="Image width in pixels.")
    height: int = Field(default=600, ge=200, le=2160, description="Image height in pixels.")
    output_path: str = Field(
        default="",
        description=(
            "If set, save PNG to this absolute path and return the path. "
            "If empty, return the image as base64 in the response."
        ),
    )


# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str                          # "ok" | "degraded" | "error"
    freecad_available: bool
    freecad_version: Optional[str] = None
    active_document: Optional[str] = None
    shape_count: int = 0
    server_version: str = "0.1.0"

# ---------------------------------------------------------------------------
# FEM — request models
# ---------------------------------------------------------------------------

_FEM_FACE_SELECTORS = Literal["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"]


class FEMCreateAnalysisRequest(BaseModel):
    shape_name: str = Field(min_length=1, max_length=64,
        description="Name of the solid shape to analyse.")


class FEMMeshRequest(BaseModel):
    shape_name: str = Field(min_length=1, max_length=64,
        description="Name of the solid shape to mesh.")
    max_cell_size: float = Field(default=10.0, gt=0.1, le=500.0,
        description="Max tetrahedral element size in mm. Smaller = finer = slower.")
    second_order: bool = Field(default=True,
        description="Use Tet10 (quadratic) elements for higher accuracy.")


class FEMMaterialRequest(BaseModel):
    material_name: str = Field(default="Steel-1C22",
        description="Human-readable material label.")
    youngs_modulus_mpa: float = Field(default=210000.0, gt=0,
        description="Young's modulus in MPa (steel ~210000, aluminium ~70000).")
    poisson_ratio: float = Field(default=0.30, ge=0.0, lt=0.5,
        description="Poisson's ratio (steel ~0.3).")
    density_kg_m3: float = Field(default=7872.0, gt=0,
        description="Density in kg/m^3 (steel ~7872).")


class FEMConstraintFixedRequest(BaseModel):
    shape_name: str = Field(min_length=1, max_length=64)
    face_selector: str = Field(
        description="Which face to fix: xmin|xmax|ymin|ymax|zmin|zmax "
                    "(min/max refers to the overall shape bounding box).")


class FEMForceLoadRequest(BaseModel):
    shape_name: str = Field(min_length=1, max_length=64)
    face_selector: str = Field(
        description="Face to apply load to: xmin|xmax|ymin|ymax|zmin|zmax.")
    force_n: float = Field(gt=0, description="Total force magnitude in Newtons.")
    direction: list[float] = Field(
        default=[0.0, 0.0, -1.0],
        description="Unit direction vector [x, y, z]. Will be normalised. "
                    "[0,0,-1] = downward (negative Z).")


class FEMRunSolverRequest(BaseModel):
    analysis_type: str = Field(default="static",
        description="Analysis type: 'static' (default) or 'frequency'.")
    working_dir: str = Field(default="",
        description="Directory for .inp and .frd files. "
                    "Defaults to output/fem/ inside the project.")


class FEMGetResultsRequest(BaseModel):
    quantity: str = Field(
        default="displacement_z",
        description=(
            "Result quantity to extract. Valid values: "
            "displacement_x, displacement_y, displacement_z, "
            "displacement_magnitude, von_mises_stress, "
            "principal_stress_1, principal_stress_2, principal_stress_3, "
            "temperature."
        ))


# ---------------------------------------------------------------------------
# Elmer FEM models
# ---------------------------------------------------------------------------

class ElmerBoundaryCondition(BaseModel):
    tags: list[int] = Field(
        description="One or more Elmer mesh boundary tag integers to target.")
    temperature: Optional[float] = Field(
        default=None,
        description="Dirichlet temperature (K). Omit for insulated (natural) BC.")
    heat_flux: Optional[float] = Field(
        default=None,
        description="Heat flux W/m² (positive = into domain). Omit for insulated.")


class ElmerMaterial(BaseModel):
    heat_conductivity: float = Field(
        default=237.0,
        description="Thermal conductivity W/(m·K). Default: Aluminium 237.")
    density: float = Field(
        default=2700.0,
        description="Mass density kg/m³. Default: Aluminium 2700.")
    heat_capacity: float = Field(
        default=897.0,
        description="Specific heat capacity J/(kg·K). Default: Aluminium 897.")


class ElmerSetupHeatRequest(BaseModel):
    working_dir: str = Field(
        description="Absolute path to working directory. Will be created if absent. "
                    "Must already contain Elmer mesh files (mesh.nodes, mesh.elements, "
                    "mesh.boundary, mesh.header) OR mesh_source_dir must be set.")
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description="If provided, mesh files are copied from this directory into working_dir.")
    material: ElmerMaterial = Field(
        default_factory=ElmerMaterial,
        description="Material properties for the body.")
    heat_source: float = Field(
        default=0.01,
        description="Volumetric heat generation W/kg (Elmer's Heat Source uses W/kg).")
    coordinate_scaling: Optional[float] = Field(
        default=None,
        description="If mesh is in mm and SI material units are desired, set 0.001. "
                    "If mesh is already in metres, omit or set None.")
    boundary_conditions: list[ElmerBoundaryCondition] = Field(
        description="List of boundary conditions (at least one Dirichlet BC required).")
    sif_name: str = Field(
        default="case.sif",
        description="Name of the .sif file to write inside working_dir.")


class ElmerRunRequest(BaseModel):
    working_dir: str = Field(
        description="Absolute path to the directory containing the .sif and mesh files.")
    timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Max time to wait for ElmerSolver to finish.")


class ElmerGetResultsRequest(BaseModel):
    working_dir: str = Field(
        description="Absolute path to directory where ElmerSolver was run.")
    field_name: str = Field(
        default="Temperature",
        description="Name of the scalar field to extract from the VTU file. "
                    "Common values: 'Temperature', 'Pressure'.")


# ---------------------------------------------------------------------------
# Elmer transient heat models (Tutorial 3 / t3_)
# ---------------------------------------------------------------------------

class ElmerInitialConditionSpec(BaseModel):
    """Specification for a single initial condition block in a transient .sif file."""
    body_indices: list[int] = Field(
        default=[1],
        description="List of Body IDs this IC applies to (usually [1]).")
    type: Literal["constant", "tabular"] = Field(
        description=(
            "IC type:\n"
            "  constant — single temperature value for all nodes\n"
            "  tabular  — piecewise-linear T interpolated from a 1-D coordinate table"
        )
    )
    value: Optional[float] = Field(
        default=None,
        description="Constant temperature value (K or °C). Required when type='constant'.")
    variable: Optional[str] = Field(
        default=None,
        description=(
            "Elmer coordinate variable name for tabular IC. "
            "Example: 'coordinate 2' (depth in Y/Z direction). "
            "Required when type='tabular'."
        )
    )
    table: Optional[list[list[float]]] = Field(
        default=None,
        description=(
            "Piecewise-linear table as [[coord, temp], ...] pairs, "
            "sorted by coordinate. Required when type='tabular'. "
            "Example: [[-8000, 320.0], [-6500, 260.0], ...]"
        )
    )


class ElmerTransientHeatSetupRequest(BaseModel):
    """Request body for POST /elmer/setup_transient_heat."""
    working_dir: str = Field(
        description=(
            "Absolute path to working directory. Will be created if absent. "
            "Must contain Elmer mesh files, or set mesh_source_dir."
        )
    )
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description="If provided, mesh.* files are copied from here into working_dir.")
    material: ElmerMaterial = Field(
        default_factory=ElmerMaterial,
        description="Material properties (heat_conductivity, density, heat_capacity).")
    heat_source: float = Field(
        default=0.0,
        description="Volumetric heat generation W/kg. 0 = no body force.")
    timestep_intervals: int = Field(
        default=10000,
        ge=1,
        description="Number of time steps to run.")
    timestep_size_expr: str = Field(
        default="$10*365*24*3600",
        description=(
            "Elmer expression for the size of each time step in seconds. "
            "Can be a plain number or an Elmer variable expression like '$10*365*24*3600'."
        )
    )
    bdf_order: int = Field(
        default=2,
        ge=1,
        le=2,
        description="BDF time-integration order (1 = first-order, 2 = second-order).")
    output_intervals: int = Field(
        default=100,
        ge=1,
        description="Write a VTU result file every N time steps.")
    coordinate_scaling: Optional[float] = Field(
        default=None,
        description="Coordinate scaling factor (e.g. 0.001 to convert mm mesh to metres).")
    initial_conditions: list[ElmerInitialConditionSpec] = Field(
        description="List of initial condition blocks (at least one required).")
    boundary_conditions: list[ElmerBoundaryCondition] = Field(
        description="List of boundary conditions (at least one Dirichlet BC required).")
    sif_name: str = Field(
        default="case.sif",
        description="Filename of the .sif to write inside working_dir.")


class ElmerGetTransientResultsRequest(BaseModel):
    """Request body for POST /elmer/get_transient_results."""
    working_dir: str = Field(
        description="Absolute path to directory where transient ElmerSolver was run.")
    field_name: str = Field(
        default="Temperature",
        description="Scalar field name to extract from each VTU file.")


# ---------------------------------------------------------------------------
# Passive elements models (Tutorial 5: Active and Passive Elements)
# ---------------------------------------------------------------------------

class ElmerPassiveBodyForce(BaseModel):
    """A body force entry for the passive elements SIF writer."""
    type: str = Field(
        description='Either "heat_source" (constant heat) or "passive" (time-dependent activation).')
    name: Optional[str] = Field(
        default=None,
        description="Optional label for this body force block.")
    value: Optional[float] = Field(
        default=None,
        description="Heat source magnitude (W/m³). Required when type='heat_source'.")
    table: Optional[list[list[float]]] = Field(
        default=None,
        description=(
            "Time–value pairs for type='passive'. Each inner list is [time, value]. "
            "Positive value = passive (excluded), negative = active (included). "
            "Example: [[0,1],[5,1],[5.2,-1],[15,-1]] activates at t=5.1s."
        ),
    )


class ElmerPassiveBody(BaseModel):
    """One body (sub-domain) in the passive elements SIF."""
    target_body_idx: int = Field(description="Elmer body index from mesh.elements column 2.")
    material_idx: int = Field(description="1-based index into the materials list.")
    body_force_idx: Optional[int] = Field(
        default=None, description="1-based index into body_forces list, if any.")
    ic_idx: Optional[int] = Field(
        default=None, description="1-based index into initial_conditions list, if any.")


class ElmerPassiveMaterial(BaseModel):
    """Material properties for passive elements simulation."""
    name: Optional[str] = Field(default=None)
    density: float = Field(default=1.0)
    heat_capacity: float = Field(default=1.0)
    heat_conductivity: float = Field(default=1.0)


class ElmerPassiveInitialCondition(BaseModel):
    """Initial condition block."""
    name: Optional[str] = Field(default=None)
    temperature: float = Field(description="Initial temperature value.")


class ElmerPassiveBoundaryCondition(BaseModel):
    """Boundary condition for passive elements SIF."""
    tag: int = Field(description="Boundary tag from mesh.boundary column 2.")
    temperature: float = Field(description="Fixed temperature value at this boundary.")
    name: Optional[str] = Field(default=None)


class ElmerPassiveElementsRequest(BaseModel):
    """
    Request body for POST /elmer/setup_passive_elements.

    Sets up and optionally runs a transient heat simulation using Elmer's
    passive element feature (Temperature Passive keyword). Passive elements
    are excluded from the FEM assembly until activated by a time condition.
    """
    working_dir: str = Field(
        description="Absolute path to directory containing mesh.* files.")
    bodies: list[ElmerPassiveBody] = Field(
        description="List of body definitions referencing materials/forces.")
    materials: list[ElmerPassiveMaterial] = Field(
        description="Material property sets (1-based, referenced by bodies).")
    body_forces: list[ElmerPassiveBodyForce] = Field(
        description="Body force entries (heat source or passive control).")
    initial_conditions: list[ElmerPassiveInitialCondition] = Field(
        default_factory=list,
        description="Initial condition blocks (1-based, referenced by bodies).")
    boundary_conditions: list[ElmerPassiveBoundaryCondition] = Field(
        description="Fixed-temperature boundary conditions.")
    timestep_intervals: int = Field(
        default=15, description="Number of timesteps to simulate.")
    timestep_sizes: float = Field(
        default=1.0, description="Duration of each timestep in seconds.")
    bdf_order: int = Field(
        default=2, description="BDF time integration order (1 or 2).")
    output_intervals: int = Field(
        default=1, description="Write VTU output every N timesteps.")
    run_solver: bool = Field(
        default=True,
        description="If true, run ElmerSolver immediately after writing the SIF.")
    sif_name: str = Field(
        default="case.sif", description="Filename of the .sif to write.")


# ---------------------------------------------------------------------------
# Radiation heat transfer models (Tutorial 4)
# ---------------------------------------------------------------------------

class RadiationBodyConfig(BaseModel):
    target_body: int = Field(description="Mesh body index (from mesh.elements body column).")
    material_idx: int = Field(description="1-based index into the materials list.")
    body_force_idx: Optional[int] = Field(
        default=None,
        description="1-based index into body_forces list, or null if no heat source.")
    ic_idx: int = Field(default=1, description="1-based index into initial_conditions list.")


class RadiationMaterialConfig(BaseModel):
    name: str = Field(default="Material", description="Human-readable name.")
    density: float = Field(default=1.0, description="kg/m^3")
    heat_capacity: float = Field(default=1.0, description="J/(kg K)")
    heat_conductivity: float = Field(default=1.0, description="W/(m K)")


class RadiationBodyForceConfig(BaseModel):
    name: str = Field(default="HeatSource", description="Human-readable name.")
    heat_source: float = Field(description="Volumetric heat source W/kg.")


class RadiationICConfig(BaseModel):
    name: str = Field(default="Initial", description="Human-readable name.")
    temperature: float = Field(default=250.0, description="Initial temperature K.")


class RadiationBCConfig(BaseModel):
    name: str = Field(default="BC", description="Human-readable name.")
    tags: list[int] = Field(description="Mesh boundary tag IDs for this condition.")
    temperature: Optional[float] = Field(
        default=None,
        description="Fixed temperature (Dirichlet BC) in K. Mutually exclusive with radiation.")
    radiation: Optional[str] = Field(
        default=None,
        description="Radiation model, e.g. Diffuse Gray. Set to enable radiation BC.")
    emissivity: Optional[float] = Field(
        default=None,
        description="Surface emissivity [0-1]. Required when radiation is set.")
    radiation_target_body: int = Field(
        default=-1,
        description="Target body index for radiation. Use -1 for open cavity.")


class ElmerSetupRadiationHeatRequest(BaseModel):
    working_dir: str = Field(
        description="Absolute path to working directory. Will be created if absent.")
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description="If provided, mesh files are copied from this directory into working_dir.")
    coordinate_system: str = Field(
        default="Axi Symmetric",
        description="Coordinate system: Axi Symmetric or Cartesian 2D etc.")
    bodies: list[RadiationBodyConfig] = Field(
        description="List of body definitions referencing material and BC indices.")
    materials: list[RadiationMaterialConfig] = Field(
        description="Material property list (1-based, referenced by body material_idx).")
    body_forces: list[RadiationBodyForceConfig] = Field(
        default_factory=list,
        description="Volumetric heat source definitions.")
    initial_conditions: list[RadiationICConfig] = Field(
        default_factory=lambda: [RadiationICConfig()],
        description="Initial condition list (1-based, referenced by body ic_idx).")
    boundary_conditions: list[RadiationBCConfig] = Field(
        description="List of boundary conditions: Dirichlet temperature or radiation.")
    steady_state_max_iter: int = Field(
        default=30,
        description="Max outer steady-state iterations.")
    nonlinear_max_iter: int = Field(
        default=50,
        description="Max nonlinear iterations per steady-state step.")
    nonlinear_tolerance: float = Field(
        default=1.0e-8,
        description="Convergence tolerance for nonlinear solver.")
    timeout_seconds: int = Field(
        default=300, ge=10, le=3600,
        description="Max seconds to wait for ElmerSolver.")
    sif_name: str = Field(
        default="case.sif",
        description="Name of the .sif file to write inside working_dir.")
    run_solver: bool = Field(
        default=True,
        description="If true, run ElmerSolver immediately after writing the SIF.")


# ---------------------------------------------------------------------------
# Mechanical integration checks
# ---------------------------------------------------------------------------

class PropellerBladeStation(BaseModel):
    r_mm: float = Field(description="Radial position from hub center (mm)")
    chord_mm: float = Field(description="Chord length at this station (mm)")
    twist_deg: float = Field(description="Blade angle (pitch angle) at this station (degrees)")
    naca: str = Field(default="4408", description="NACA 4-digit profile code (e.g. '4408')")
    tc_pct: float = Field(default=8.0, description="Thickness/chord percent override (0=use NACA default)")


class AddPropellerBladeRequest(BaseModel):
    name: str = Field(description="Shape name for the result")
    stations: list[PropellerBladeStation] = Field(description="Radial cross-sections, ordered root to tip")
    rotation_axis: str = Field(default="z", description="Propeller rotation axis: x, y, or z")
    hub_offset_mm: float = Field(default=0.0, description="Offset of hub center from origin along rotation axis")

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"Shape name '{v}' must match [A-Za-z_][A-Za-z0-9_\\-]*")
        return v


class CheckInterferenceRequest(BaseModel):
    shape_a: str = Field(
        description="Name of the first shape (the part being checked, e.g. 'stem_body').")
    shape_b: str = Field(
        description="Name of the second shape (the witness/mating part, e.g. 'handlebar_witness').")


class CheckMinDistanceRequest(BaseModel):
    shape_a: str = Field(
        description="Name of the first shape.")
    shape_b: str = Field(
        description="Name of the second shape.")
    required_clearance_mm: float = Field(
        default=0.0,
        description="Expected minimum clearance in mm. "
                    "A warning is returned if min_distance_mm < this value.")


class ElmerInspectMeshRequest(BaseModel):
    mesh_dir: str = Field(
        description="Absolute path to directory containing mesh.nodes and mesh.boundary.")
    max_tags: int = Field(
        default=200, ge=1, le=10000,
        description="Maximum number of distinct boundary tags to return.")


# ---------------------------------------------------------------------------
# Elasticity 2D model (Tutorial 6)
# ---------------------------------------------------------------------------

class ElmerElasticity2DRequest(BaseModel):
    working_dir: str = Field(description="Path to directory containing mesh files (mesh.nodes etc.)")
    poisson_ratio: float = Field(default=0.29)
    youngs_modulus: float = Field(default=193.053e9)
    density: float = Field(default=7870.0)
    wall_bc_tag: int = Field(default=4, description="Boundary tag for the fixed wall")
    load_bc_tag: int = Field(default=3, description="Boundary tag for the loaded surface")
    force_magnitude: float = Field(default=-1.0e7, description="Force at x=1 in N/m^2 (linearly varies from 0 at x=0)")
    plane_stress: bool = Field(default=True)


# ---------------------------------------------------------------------------
# Elasticity 3D model (Tutorial 7)
# ---------------------------------------------------------------------------

class ElmerElasticity3DRequest(BaseModel):
    working_dir: str = Field(description="Path to directory containing mesh files")
    poisson_ratio: float = Field(default=0.37)
    youngs_modulus: float = Field(default=10.0e9)
    density: float = Field(default=550.0)
    gravity_force_y: float = Field(default=-9.81, description="Gravity acceleration * density product sign, actual bodyforce = gravity_force_y * density")
    wall_bc_tag: int = Field(default=5)
    load_bc_tag: int = Field(default=6)
    force_y: float = Field(default=-45_800_000.0, description="Per-node nodal force in y direction at load BC. NOTE: in Elmer, 'Force 2' is NOT a surface traction; it is integrated per-node. The default -45800000 corresponds to ~2000 N total on this mesh (1996 elements, 6073 nodes).")


# ---------------------------------------------------------------------------
# Plate deflection model (Tutorial 9: Smitc solver)
# ---------------------------------------------------------------------------

class ElmerPlateDeflectionRequest(BaseModel):
    working_dir: str = Field(description="Path to directory containing mesh files")
    density: float = Field(default=7800.0)
    youngs_modulus: float = Field(default=209.0e9)
    poisson_ratio: float = Field(default=0.3)
    thickness: float = Field(default=1.0e-2)
    tension: float = Field(default=0.0)
    pressure: float = Field(default=5.0e4, description="Uniform pressure load in Pa")
    n_boundary_tags: int = Field(default=6, description="Number of boundary tags (will fix tags 1..n)")


# ---------------------------------------------------------------------------
# Plate eigenmode model (Tutorial 10: Smitc eigenmodes)
# ---------------------------------------------------------------------------

class ElmerPlateEigenmodesRequest(BaseModel):
    working_dir: str = Field(description="Path to directory containing mesh files")
    density: float = Field(default=1000.0)
    youngs_modulus: float = Field(default=1.0e9)
    poisson_ratio: float = Field(default=0.3)
    thickness: float = Field(default=0.001)
    tension: float = Field(default=0.0)
    n_eigen_values: int = Field(default=10)
    n_boundary_tags: int = Field(default=5, description="Number of boundary tags (will fix tags 1..n)")


# ---------------------------------------------------------------------------
# Non-linear elasticity 3D model (Tutorial 8)
# ---------------------------------------------------------------------------

class ElmerNonlinearElasticityRequest(BaseModel):
    working_dir: str = Field(description="Path to directory containing mesh files")
    density: float = Field(default=7900.0)
    youngs_modulus: float = Field(default=197.0e9)
    poisson_ratio: float = Field(default=0.27)
    n_timesteps: int = Field(default=20)
    timestep_size: float = Field(default=0.05)
    coordinate_scaling: float = Field(default=0.01)
    moving_right_bc_tag: int = Field(default=1, description="Boundary tag for the end that moves in +x")
    moving_left_bc_tag: int = Field(default=3, description="Boundary tag for the end that moves in -x")
    displacement_amplitude: float = Field(default=0.006, description="Max displacement in meters at t=1s")


# ---------------------------------------------------------------------------
# Electrostatics 2D model (Tutorial 11: Fringe Capacitance)
# ---------------------------------------------------------------------------

class ElmerElectrostatics2DRequest(BaseModel):
    working_dir: str = Field(description="Path to directory with mesh files")
    vacuum_permittivity: float = Field(default=1.0)
    relative_permittivity: float = Field(default=1.0)
    ground_bc_tag: int = Field(default=2)
    capacitor_bc_tag: int = Field(default=1)
    ground_potential: float = Field(default=0.0)
    capacitor_potential: float = Field(default=1.0)


# ---------------------------------------------------------------------------
# Electrostatics 3D model (Tutorial 12: Capacitance of Two Balls)
# ---------------------------------------------------------------------------

class ElmerElectrostatics3DRequest(BaseModel):
    working_dir: str = Field(description="Path to directory with mesh files")
    vacuum_permittivity: float = Field(default=1.0)
    relative_permittivity: float = Field(default=1.0)
    farfield_bc_tag: int = Field(default=3, description="Outer sphere boundary tag")
    cap_body1_bc_tag: int = Field(default=1, description="Ball 1 boundary tag")
    cap_body2_bc_tag: int = Field(default=2, description="Ball 2 boundary tag")


# ---------------------------------------------------------------------------
# Acoustics model (Tutorial 17: Helmholtz 2D Acoustic Waves)
# ---------------------------------------------------------------------------

class ElmerAcousticsRequest(BaseModel):
    working_dir: str = Field(description="Path to directory with mesh files")
    angular_frequency: float = Field(default=628.3, description="Angular frequency omega=2*pi*f")
    sound_speed: float = Field(default=343.0)
    density: float = Field(default=1.224)
    source_bc_tag: int = Field(default=1)
    rigid_bc_tag: int = Field(default=2)
    impedance_bc_tag: int = Field(default=3)
    wave_flux: float = Field(default=1.0)
    wave_impedance: float = Field(default=-343.0)


# ---------------------------------------------------------------------------
# Magnetostatics 2D model (Tutorial 15: horseshoe permanent magnet)
# ---------------------------------------------------------------------------

class ElmerMagnetostatics2DRequest(BaseModel):
    working_dir: str = Field(description="Path to dir with horseshoe.msh and mesh files")
    air_body: int = Field(default=4, description="Elmer body index for air (largest domain)")
    iron_body: int = Field(default=2, description="Elmer body index for curved iron yoke")
    ironplus_body: int = Field(default=1, description="Elmer body index for upper magnetized leg (+)")
    ironminus_body: int = Field(default=3, description="Elmer body index for lower magnetized leg (-)")
    outer_bc_tags: list[int] = Field(
        default=[15, 16, 17, 18],
        description="Boundary tags for the far-field (outer) BC where Az=0")
    magnetization: float = Field(
        default=750.0e3,
        description="Magnetization magnitude in A/m (applied as +M to IronPlus, -M to IronMinus)")
    relative_permeability: float = Field(
        default=5000.0,
        description="Relative permeability of the iron bodies")
    auto_detect_bodies: bool = Field(
        default=True,
        description="Auto-detect outer boundary tags from mesh (tags with max_dist >= 2.9 m)")


# ---------------------------------------------------------------------------
# Glacier heat model (Tutorial 27: Temperature distribution of a toy glacier)
# ---------------------------------------------------------------------------

class ElmerGlacierHeatRequest(BaseModel):
    working_dir: str = Field(description="Path to directory with mesh files")
    density: float = Field(default=910.0, description="Ice density kg/m3")
    heat_conductivity: float = Field(default=2.1, description="W/(m·K)")
    heat_capacity: float = Field(default=2093.0, description="J/(kg·K)")
    surface_bc_tag: int = Field(default=3, description="Boundary tag for glacier surface")
    bottom_bc_tag: int = Field(default=1, description="Boundary tag for glacier bottom")
    surface_temperature: float = Field(default=273.15, description="Surface temperature in K")
    bottom_heat_flux: float = Field(default=0.02, description="Geothermal heat flux W/m2")


# ---------------------------------------------------------------------------
# Induction heating model (Tutorial 16: MagnetoDynamics2D + eddy currents)
# ---------------------------------------------------------------------------

class ElmerInductionHeatingRequest(BaseModel):
    working_dir: str = Field(description="Path to directory with mesh files (mesh.nodes, mesh.elements, etc.)")


# ---------------------------------------------------------------------------
# Laminar flow model (Tutorial 19: Navier-Stokes flow past a step)
# ---------------------------------------------------------------------------

class ElmerDrivenCavityRequest(BaseModel):
    working_dir: str = Field(description="Path to mesh directory")
    lid_velocity: float = Field(default=1.0)
    viscosity: float = Field(default=0.01)


class ElmerFlowLaminarRequest(BaseModel):
    working_dir: str = Field(description="Path to directory with mesh files")
    density: float = Field(default=1.0, description="Fluid density kg/m3")
    viscosity: float = Field(default=0.01, description="Dynamic viscosity kg/(m s)")
    wall_tags: list[int] = Field(default=[3], description="Boundary tags for no-slip walls")
    inlet_tag: int = Field(default=1, description="Boundary tag for inlet")
    outlet_tag: int = Field(default=2, description="Boundary tag for outlet")
    max_inlet_velocity: float = Field(default=1.5, description="Peak inlet velocity m/s")
    inlet_y_min: float = Field(default=1.0, description="Y coordinate of inlet lower edge")
    inlet_y_max: float = Field(default=2.0, description="Y coordinate of inlet upper edge")
    steady_state_max_iter: int = Field(default=20, description="Max steady-state iterations")


# ---------------------------------------------------------------------------
# Von Karman vortex street model (Tutorial 23)
# ---------------------------------------------------------------------------

class ElmerVonKarmanRequest(BaseModel):
    working_dir: str = Field(description="Path to mesh directory (must contain mesh.* files)")


# ---------------------------------------------------------------------------
# ModelPDE 3D model (Tutorial 29: General PDE solver)
# ---------------------------------------------------------------------------

class ElmerModelPDERequest(BaseModel):
    """
    Request body for POST /elmer/setup_model_pde.

    Solves the general PDE on a 3D mesh:
        c * du/dt - div(k * grad(u)) + a*u = f

    For the default steady-state Poisson case: k=1, a=0, c=0, f=1, u=0 on all walls.
    Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\ModelPDE3D\\
    """
    working_dir: str = Field(
        description="Path to directory containing Elmer mesh files (mesh.*)."
    )
    diffusion_coefficient: float = Field(
        default=1.0,
        description="Diffusion coefficient k in -div(k*grad(u))=f."
    )
    reaction_coefficient: float = Field(
        default=0.0,
        description="Reaction coefficient a in a*u term."
    )
    time_derivative_coefficient: float = Field(
        default=0.0,
        description="Mass/time-derivative coefficient c (0 = steady-state)."
    )
    field_source: float = Field(
        default=1.0,
        description="Volumetric source term f on the right-hand side."
    )
    dirichlet_tags: list[int] = Field(
        default=[1, 2, 3, 4, 5, 6, 7],
        description="Boundary tags for Dirichlet (Field=dirichlet_value) conditions."
    )
    dirichlet_value: float = Field(
        default=0.0,
        description="Dirichlet boundary value (default 0.0)."
    )
    neumann_tags: list[int] = Field(
        default=[],
        description="Boundary tags for Neumann (flux) conditions."
    )
    neumann_value: float = Field(
        default=0.0,
        description="Neumann flux value (default 0.0 = insulating)."
    )
    timeout_seconds: int = Field(
        default=120,
        description="Max seconds to wait for ElmerSolver."
    )


# ---------------------------------------------------------------------------
# Electrostatics floating potential model (Tutorial 13)
# ---------------------------------------------------------------------------

class ElmerElectrostaticsFloatingRequest(BaseModel):
    working_dir: str = Field(description="Path to mesh directory")


# ---------------------------------------------------------------------------
# Magnetic field wire model (Tutorial 18: MagnetoDynamics harmonic A-V)
# ---------------------------------------------------------------------------

class ElmerMagneticWireRequest(BaseModel):
    """
    Request body for POST /elmer/setup_magnetic_wire.

    Solves the harmonic magnetodynamics problem (WhitneyAVHarmonicSolver) for a
    current-carrying copper wire embedded in air. Based on Elmer Tutorial 18
    (MagneticFieldWire): computes the complex magnetic vector potential A-V,
    magnetic field strength H, and Joule heating.

    Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\MagneticFieldWire\\
    Boundary tags: 1=voltage, 3=ground, 4+5+6=axial/outer field.
    """
    working_dir: str = Field(
        description="Path to directory that will receive mesh files and case.sif."
    )
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description=(
            "Source directory for mesh.* files. "
            "Defaults to the Tutorial 18 directory if not provided."
        ),
    )
    angular_frequency: float = Field(
        default=1.0e5,
        description="Angular frequency omega (rad/s). Default 1e5 ≈ 15.9 kHz.",
    )
    coordinate_scaling: float = Field(
        default=1.0e-3,
        description="Coordinate scaling factor (1e-3 converts mm mesh to metres).",
    )
    copper_conductivity: float = Field(
        default=59.59e6,
        description="Electric conductivity of copper in S/m.",
    )
    copper_permeability: float = Field(
        default=0.999994,
        description="Relative permeability of copper.",
    )
    air_permeability: float = Field(
        default=1.00000037,
        description="Relative permeability of air.",
    )
    voltage_amplitude: float = Field(
        default=0.01,
        description="Real part of applied voltage on the inlet face (V).",
    )
    voltage_tag: int = Field(default=1, description="Boundary tag for the voltage inlet.")
    ground_tag: int = Field(default=3, description="Boundary tag for the ground face.")
    axial_tags: list[int] = Field(
        default=[4, 5, 6],
        description="Boundary tags for outer/axial field boundaries (AV edge DOFs = 0).",
    )
    timeout_seconds: int = Field(
        default=300, ge=30, le=3600,
        description="Max seconds to wait for ElmerSolver.",
    )


# ---------------------------------------------------------------------------
# Rayleigh-Benard convection model (Tutorial 26)
# ---------------------------------------------------------------------------

class ElmerRayleighBenardRequest(BaseModel):
    """
    Request body for POST /elmer/setup_rayleigh_benard.

    Sets up and runs a transient 2D coupled Navier-Stokes + Heat equation
    simulation of Rayleigh-Benard natural convection (Boussinesq approximation).
    A rectangular cavity is heated from below and cooled from above.

    Mesh: C:\\Elmer\\tutorials-CL\\tutorials-CL-files\\RayleighBenard\\Mesh\\
    Boundary tags:
      1 = top (cold) wall
      2 = right side wall (insulated, no-slip)
      3 = bottom (hot) wall
      4 = left side wall (insulated, no-slip)
    """
    working_dir: str = Field(
        description="Absolute path to working directory. Must contain or receive mesh files.")
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description=(
            "If set, mesh.* files are copied from this directory into working_dir. "
            "Defaults to the Tutorial 26 mesh directory if not provided."
        ),
    )
    density: float = Field(default=1000.0, description="Fluid density kg/m3 (water default).")
    viscosity: float = Field(default=1040e-6, description="Dynamic viscosity kg/(m s).")
    heat_capacity: float = Field(default=4190.0, description="Specific heat J/(kg K).")
    heat_conductivity: float = Field(default=0.6, description="Thermal conductivity W/(m K).")
    heat_expansion_coefficient: float = Field(
        default=1.8e-4, description="Volumetric thermal expansion coefficient 1/K.")
    reference_temperature: float = Field(
        default=283.0, description="Reference temperature for Boussinesq buoyancy (K).")
    cold_wall_temperature: float = Field(
        default=283.0, description="Temperature of the cold (top) wall in K.")
    hot_wall_temperature: float = Field(
        default=283.5, description="Temperature of the hot (bottom) wall in K.")
    n_timesteps: int = Field(
        default=200, ge=1, description="Number of time steps to simulate.")
    timestep_size: float = Field(
        default=2.0, gt=0, description="Duration of each timestep in seconds.")
    newmark_beta: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Newmark beta parameter (1.0 = fully implicit).")
    initial_temperature: float = Field(
        default=283.0, description="Uniform initial temperature (K).")
    timeout_seconds: int = Field(
        default=300, ge=10, le=3600,
        description="Max seconds to wait for ElmerSolver.")


# ---------------------------------------------------------------------------
# Turbulent flow k-epsilon model (Tutorial 14: FlowStepKe)
# ---------------------------------------------------------------------------

class ElmerFlowKEpsilonRequest(BaseModel):
    """
    Request body for POST /elmer/setup_flow_kepsilon.

    Sets up and runs a 2D steady-state turbulent Navier-Stokes flow simulation
    using the k-epsilon model. Based on Elmer Tutorial 14 (FlowStepKe):
    incompressible flow past a backward-facing step at high Reynolds number
    (Re ~ 15000 with default parameters).
    """
    working_dir: str = Field(
        description="Path to directory containing mesh files.")
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description="If provided, mesh files are copied from this directory into working_dir.")
    density: float = Field(default=1.0, description="Fluid density kg/m3")
    viscosity: float = Field(
        default=1.0e-4,
        description="Dynamic viscosity kg/(m s). Default gives Re ~ 15000.")
    wall_tags: list[int] = Field(default=[3], description="Boundary tags for no-slip walls")
    inlet_tag: int = Field(default=1, description="Boundary tag for inlet")
    outlet_tag: int = Field(default=2, description="Boundary tag for outlet")
    max_inlet_velocity: float = Field(
        default=1.5, description="Peak parabolic inlet velocity m/s")
    inlet_y_min: float = Field(default=1.0, description="Y coordinate of inlet lower edge")
    inlet_y_max: float = Field(default=2.0, description="Y coordinate of inlet upper edge")
    kinetic_energy_init: float = Field(
        default=0.00457, description="Initial turbulent kinetic energy k (m^2/s^2)")
    kinetic_dissipation_init: float = Field(
        default=1.0e-4, description="Initial turbulent dissipation rate epsilon (m^2/s^3)")
    steady_state_max_iter: int = Field(
        default=100, description="Max steady-state outer iterations")


# ---------------------------------------------------------------------------
# Tutorial 30: Vector Helmholtz — 3D bent waveguide (WaveguideGUI)
# ---------------------------------------------------------------------------

class ElmerWaveguideRequest(BaseModel):
    """
    Request body for POST /elmer/setup_waveguide.

    Solves the Vector Helmholtz equation for electromagnetic wave propagation
    in a 3D bent rectangular waveguide using Elmer's VectorHelmholtz solver.

    Physics: curl(curl(E)) - omega^2 * mu * eps * E = 0
    The waveguide is filled with air (eps_r = mu_r = 1) by default.

    Mesh source: C:\\Elmer\\tutorials\\tutorials-GUI-files\\WaveguideGUI\\
    The mesh has 14 boundary tags; by default tag 1 = input port,
    tag 2 = output port, tags 3–14 = PEC conducting walls.

    Expected result: complex E-field distribution inside the bent waveguide,
    with energy transmitted from port 1 to port 2. ElmerSolver exits 0
    and writes case_t0001.vtu containing 'E re' and 'E im' vector fields.
    """
    working_dir: str = Field(
        description="Absolute path to the working directory (must exist or be creatable).")
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description=(
            "Directory containing Elmer mesh files (mesh.header, mesh.nodes, "
            "mesh.elements, mesh.boundary). Defaults to the WaveguideGUI tutorial directory."
        ),
    )
    angular_frequency: float = Field(
        default=2.0e10,
        description="Angular frequency omega = 2*pi*f in rad/s. Default ~3.18 GHz.",
    )
    relative_permittivity: float = Field(
        default=1.0,
        description="Relative permittivity of waveguide fill material (1.0 = air).",
    )
    relative_permeability: float = Field(
        default=1.0,
        description="Relative permeability of waveguide fill material (1.0 = air).",
    )
    port_in_tag: int = Field(
        default=1,
        description="Boundary tag of the excitation (input) port.",
    )
    port_out_tag: int = Field(
        default=2,
        description="Boundary tag of the output (absorbing) port.",
    )
    e_re_z: float = Field(
        default=1.0,
        description="Real part of E-field Z-component imposed at the input port.",
    )
    timeout_seconds: int = Field(
        default=300, ge=10, le=3600,
        description="Max seconds to wait for ElmerSolver.",
    )


# ---------------------------------------------------------------------------
# Electrokinetics model (Tutorial 25: electroosmotic flow in T-microchannel)
# ---------------------------------------------------------------------------

class ElmerElectrokineticsRequest(BaseModel):
    """
    Request body for POST /elmer/setup_electrokinetics.

    Sets up and runs Tutorial 25: Electrokinetic (electroosmotic) flow in a
    T-shaped microchannel. Three coupled solvers run each timestep:
      1. Electrostatics — electric potential driven by applied voltages.
      2. Navier-Stokes  — fluid velocity with Helmholtz-Smoluchowski slip at walls.
      3. Advection-Diffusion — concentration of a solute injected at inlet A.

    Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\Electrokinetics\\ (Tcross.grd)
    Boundary tags:
      1, 5 = channel walls (electroosmotic slip)
      2    = inlet electrode A (top arm, 100 V, concentration injection)
      3    = outlet electrode B (right arm, 30 V)
      4    = outlet electrode C (bottom arm, 0 V / ground)
    """
    working_dir: str = Field(
        description="Absolute path to working directory. Must contain mesh files, "
                    "or set mesh_source_dir to use the tutorial default.")
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description="If provided, mesh.* files are copied from this directory. "
                    "Defaults to the Electrokinetics tutorial mesh directory.")
    density: float = Field(default=1000.0, description="Fluid density kg/m3 (water).")
    viscosity: float = Field(default=1.0e-3, description="Dynamic viscosity Pa.s (water).")
    diffusivity: float = Field(default=1.0e-10, description="Solute diffusivity m2/s.")
    relative_permittivity: float = Field(default=1.0, description="Relative permittivity of fluid.")
    eo_mobility: float = Field(
        default=5.0e-8,
        description="Electroosmotic mobility m2/(V.s). Wall slip velocity = mobility * E_tangential.")
    wall_tags: list[int] = Field(
        default=[1, 5],
        description="Boundary tags for channel walls (electroosmotic slip applied here).")
    inlet_tag: int = Field(default=2, description="Boundary tag for inlet electrode A.")
    outlet_b_tag: int = Field(default=3, description="Boundary tag for outlet electrode B.")
    outlet_c_tag: int = Field(default=4, description="Boundary tag for outlet electrode C (ground).")
    inlet_potential: float = Field(default=100.0, description="Electric potential at inlet A (V).")
    outlet_b_potential: float = Field(default=30.0, description="Electric potential at outlet B (V).")
    outlet_c_potential: float = Field(default=0.0, description="Electric potential at outlet C (V, ground).")
    n_timesteps: int = Field(default=120, ge=1, description="Number of timesteps.")
    timestep_size: float = Field(default=1.0e-5, gt=0, description="Timestep size in seconds.")
    output_intervals: int = Field(default=2, ge=1, description="Write VTU every N timesteps.")
    coordinate_scaling: float = Field(
        default=1.0e-5,
        description="Mesh coordinate scaling factor (1e-5: 1 mesh unit = 10 micrometres).")
    timeout_seconds: int = Field(
        default=300, ge=30, le=3600, description="Max seconds to wait for ElmerSolver.")


# ---------------------------------------------------------------------------
# Thermal actuator model (Tutorial 22: coupled Joule + Heat + Stress)
# ---------------------------------------------------------------------------

class ElmerThermalActuatorRequest(BaseModel):
    """
    Request body for POST /elmer/setup_thermal_actuator.

    Simulates a silicon MEMS thermal actuator using three coupled solvers:
      1. StatCurrentSolve  - electric potential / Joule heating
      2. Heat Equation     - temperature from Joule heat source
      3. Stress Analysis   - thermal displacement and stress

    A simple box mesh is generated automatically by ElmerGrid; no external
    mesh files are needed.  Based on Elmer Tutorial 22 (ThermalActuator).
    """
    working_dir: str = Field(
        description="Directory where mesh, SIF, and results will be written."
    )
    voltage: float = Field(
        default=7.0,
        description="Applied voltage in V across the actuator length."
    )
    ground_bc_tag: int = Field(
        default=1,
        description="Boundary tag for the ground end (potential=0, fixed displacement)."
    )
    voltage_bc_tag: int = Field(
        default=2,
        description="Boundary tag for the high-voltage end (fixed displacement)."
    )
    reference_temperature: float = Field(
        default=298.0,
        description="Reference (ambient) temperature in K."
    )
    youngs_modulus: float = Field(
        default=169.0e9,
        description="Young's modulus of silicon in Pa."
    )
    poisson_ratio: float = Field(
        default=0.22,
        description="Poisson ratio of silicon."
    )
    heat_expansion_coefficient: float = Field(
        default=2.9e-6,
        description="Coefficient of thermal expansion in 1/K."
    )
    steady_state_max_iter: int = Field(
        default=30,
        description="Max outer steady-state iterations for the coupled solve."
    )
    mesh_nx: int = Field(
        default=10,
        description="Mesh divisions along actuator length (X)."
    )
    mesh_ny: int = Field(
        default=5,
        description="Mesh divisions across actuator width (Y)."
    )
    mesh_nz: int = Field(
        default=3,
        description="Mesh divisions through actuator thickness (Z)."
    )
    timeout_seconds: int = Field(
        default=300,
        description="Max seconds to wait for ElmerSolver."
    )


# ---------------------------------------------------------------------------
# Glacier temperature + flow model (Tutorial 28)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Perforated plate capacitance model (Tutorial 14)
# ---------------------------------------------------------------------------

class ElmerPerforatedPlateRequest(BaseModel):
    """
    Request body for POST /elmer/setup_perforated_plate.

    Tutorial 14: 3D electrostatics of a perforated parallel-plate capacitor.
    Computes electric potential and energy in the air gap of a unit-cell model
    of a square plate with a cylindrical hole. The perforation reduces effective
    capacitance relative to a solid plate.

    Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\CapacitanceOfPerforatedPlate\\
    Mesh is in mm; Coordinate Scaling = 0.001 converts to SI metres.

    Boundary tags (default, from reference case.sif):
      4          = ground plane (Potential = 0)
      1, 2, 3, 7 = perforated plate faces (Potential = 1)
    """
    working_dir: str = Field(
        description="Absolute path to working directory. Mesh files will be copied here.")
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description=(
            "Directory with Elmer mesh files. "
            "Defaults to the CapacitanceOfPerforatedPlate tutorial directory."
        ),
    )
    ground_bc_tag: int = Field(
        default=4,
        description="Boundary tag for the ground plane (Potential = ground_potential).")
    capacitor_bc_tags: list[int] = Field(
        default=[1, 2, 3, 7],
        description="Boundary tags for the perforated plate faces (Potential = capacitor_potential).")
    ground_potential: float = Field(
        default=0.0, description="Electric potential on the ground plane (V).")
    capacitor_potential: float = Field(
        default=1.0, description="Electric potential on the plate (V).")
    relative_permittivity: float = Field(
        default=1.00059,
        description="Relative permittivity of air (dimensionless).")
    coordinate_scaling: float = Field(
        default=0.001,
        description="Coordinate scaling factor (0.001 converts mm mesh to metres).")
    timeout_seconds: int = Field(
        default=300, ge=10, le=3600,
        description="Max seconds to wait for ElmerSolver.")


# ---------------------------------------------------------------------------
# TEAM7 model (Tutorial 31: Asymmetrical Conductor with a Hole)
# ---------------------------------------------------------------------------

class ElmerTEAM7Request(BaseModel):
    """
    Request body for POST /elmer/setup_team7.

    Runs Elmer Tutorial 31: TEAM Workshop Problem 7 — transient 3D eddy currents
    in an aluminium plate with an eccentric hole driven by a sinusoidal coil current.

    Solvers: CoilSolver + WhitneyAVSolver + MagnetoDynamicsCalcFields.
    Mesh: elmer-elmag/TEAM7/TEAM7/ (bodies: 1=Coil, 2=Plate/Al, 3=Air; BC 6=Inf).

    Default parameters match the reference case from elmer-elmag repo:
      - 16 timesteps × 0.0025 s = 0.04 s (2 full periods at 50 Hz)
      - Aluminium: sigma = 3.526e7 S/m, mu_r = 1
      - Coil: 2742 A desired current, normalised by CoilSolver

    Expected: non-zero magnetic flux density in the aluminium plate, Bz field
    consistent with the TEAM7 benchmark measurements.
    """
    working_dir: str = Field(
        description=(
            "Absolute path to working directory. "
            "Elmer mesh files will be copied here (TEAM7/ subdirectory). "
            "Results and VTU files are written to working_dir/res/."
        )
    )
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description=(
            "Directory containing Elmer mesh files for TEAM7 (mesh.nodes, mesh.elements, "
            "mesh.boundary, mesh.header, mesh.names). "
            "Defaults to the elmer-elmag TEAM7 mesh directory."
        ),
    )
    timestep_interval: int = Field(
        default=16,
        ge=1,
        description="Number of transient timesteps to simulate (default 16 = 2 periods at 50 Hz).",
    )
    timestep_size: float = Field(
        default=0.0025,
        gt=0,
        description="Duration of each timestep in seconds (default 0.0025 = 1/8 period at 50 Hz).",
    )
    timeout_seconds: int = Field(
        default=600,
        ge=30,
        le=3600,
        description="Max seconds to wait for ElmerSolver (TEAM7 may take 2-10 min).",
    )


class ElmerGlacierFlowRequest(BaseModel):
    """
    Request body for POST /elmer/setup_glacier_flow.

    Tutorial 28: Coupled steady-state heat equation and Navier-Stokes flow
    in a toy glacier cross-section. Two bodies:
      - Ice: temperature-dependent viscosity (Glen/Arrhenius), gravity body force
      - Bedrock: heat conduction only

    Mesh: C:\\Elmer\\tutorials\\tutorials-GUI-files\\ToyGlacierTemperatureAndFlow\\
    Boundary tags (default):
      1 = bedrock bottom (geothermal heat flux, no-slip)
      2 = left side (symmetry)
      3 = glacier surface (cold temperature, free-slip)
      4 = right side (symmetry)
    """
    working_dir: str = Field(
        description="Absolute path to working directory. Mesh files will be copied here.")
    mesh_source_dir: Optional[str] = Field(
        default=None,
        description=(
            "Directory with Elmer mesh files (mesh.header, mesh.nodes, mesh.elements, "
            "mesh.boundary). Defaults to ToyGlacierTemperatureAndFlow tutorial directory."
        ),
    )
    ice_density: float = Field(default=910.0, description="Ice density in kg/m3.")
    bedrock_density: float = Field(default=2800.0, description="Bedrock density in kg/m3.")
    surface_temperature: float = Field(
        default=-10.0, description="Glacier surface temperature in degC.")
    bottom_heat_flux: float = Field(
        default=0.02, description="Geothermal heat flux at bedrock bottom in W/m2.")
    ice_body_tag: int = Field(default=1, description="Elmer body index for ice.")
    bedrock_body_tag: int = Field(default=2, description="Elmer body index for bedrock.")
    surface_bc_tag: int = Field(default=3, description="Boundary tag for glacier surface.")
    bottom_bc_tag: int = Field(default=1, description="Boundary tag for bedrock bottom.")
    side_bc_tags: list[int] = Field(
        default=[2, 4], description="Boundary tags for side walls (symmetry/no-slip).")
    steady_state_max_iter: int = Field(
        default=50, ge=1, description="Max outer steady-state iterations.")
    nonlinear_max_iter: int = Field(
        default=10, ge=1, description="Max inner nonlinear iterations per solver.")
    timeout_seconds: int = Field(
        default=300, ge=30, le=3600, description="Max seconds to wait for ElmerSolver.")
